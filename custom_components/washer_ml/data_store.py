"""Async SQLite storage for Washer ML.

All database access happens through the aiosqlite driver so the event loop of
Home Assistant is never blocked. Files live in
``config/washer_ml/<entry_id>/history.db``.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .ml_model import HeuristicConfig, auto_label_cycle, segment_cycles

_LOGGER = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    program_label TEXT,
    raw_samples TEXT NOT NULL DEFAULT '[]',
    phase_labels TEXT NOT NULL DEFAULT '[]',
    auto_labels TEXT NOT NULL DEFAULT '[]'
)
"""

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_cycles_entry_id ON cycles (entry_id, id)"
)

_JSON_COLUMNS = {"raw_samples", "phase_labels", "auto_labels"}
_UPDATEABLE_COLUMNS = {
    "started_at",
    "ended_at",
    "program_label",
    "raw_samples",
    "phase_labels",
    "auto_labels",
}


class WasherMlDataStore:
    """Persist wash cycles and import historical CSV data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._db_path = (
            Path(hass.config.path("washer_ml", entry.entry_id)) / "history.db"
        )
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def async_open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._db_path))
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute(_SCHEMA)
        await self._conn.execute(_INDEX_SQL)
        await self._conn.commit()

    async def async_close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def async_begin_cycle(self, started_at: float) -> int:
        async with self._lock:
            assert self._conn is not None
            cursor = await self._conn.execute(
                "INSERT INTO cycles (entry_id, started_at) VALUES (?, ?)",
                (self._entry.entry_id, started_at),
            )
            await self._conn.commit()
            return int(cursor.lastrowid)

    async def async_upsert_cycle(self, cycle_id: int, **fields: Any) -> None:
        """Update a cycle row; only known columns are accepted."""
        setters: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in _UPDATEABLE_COLUMNS:
                continue
            if key in _JSON_COLUMNS:
                value = json.dumps(value, ensure_ascii=False)
            setters.append(f"{key} = ?")
            values.append(value)
        if not setters:
            return
        values.append(cycle_id)
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                f"UPDATE cycles SET {', '.join(setters)} WHERE id = ?", values
            )
            await self._conn.commit()

    async def async_delete_cycle(self, cycle_id: int) -> None:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute("DELETE FROM cycles WHERE id = ?", (cycle_id,))
            await self._conn.commit()

    async def async_prune_cycles(self, max_stored_cycles: int) -> None:
        async with self._lock:
            assert self._conn is not None
            await self._conn.execute(
                "DELETE FROM cycles WHERE entry_id = ? AND id NOT IN ("
                "SELECT id FROM cycles WHERE entry_id = ? "
                "ORDER BY id DESC LIMIT ?)",
                (self._entry.entry_id, self._entry.entry_id, max_stored_cycles),
            )
            await self._conn.commit()

    async def async_load_cycles(self) -> list[dict[str, Any]]:
        async with self._lock:
            assert self._conn is not None
            cursor = await self._conn.execute(
                "SELECT id, started_at, ended_at, program_label, raw_samples, "
                "phase_labels, auto_labels FROM cycles "
                "WHERE entry_id = ? ORDER BY id",
                (self._entry.entry_id,),
            )
            rows = await cursor.fetchall()
        cycles: list[dict[str, Any]] = []
        for row in rows:
            cycles.append(
                {
                    "id": row[0],
                    "started_at": row[1],
                    "ended_at": row[2],
                    "program_label": row[3],
                    "raw_samples": json.loads(row[4] or "[]"),
                    "phase_labels": json.loads(row[5] or "[]"),
                    "auto_labels": json.loads(row[6] or "[]"),
                }
            )
        return cycles

    async def async_cycle_count(self) -> int:
        async with self._lock:
            assert self._conn is not None
            cursor = await self._conn.execute(
                "SELECT COUNT(*) FROM cycles WHERE entry_id = ?",
                (self._entry.entry_id,),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def async_import_csv(
        self,
        csv_content: str,
        power_entity_id: str | None,
        idle_threshold_w: float,
    ) -> int:
        """Segment a HA history CSV export into cycles and store them.

        Cycles imported this way receive heuristic auto labels so they can
        bootstrap the learned model even without manual calibration.
        """
        samples = _parse_csv(csv_content, power_entity_id)
        if not samples:
            return 0
        cycles = segment_cycles(samples, idle_threshold_w)
        config = HeuristicConfig(idle_threshold_w=idle_threshold_w)
        imported = 0
        for raw in cycles:
            auto = auto_label_cycle(raw, config)
            started = raw[0][0]
            ended = raw[-1][0]
            async with self._lock:
                assert self._conn is not None
                await self._conn.execute(
                    "INSERT INTO cycles (entry_id, started_at, ended_at, "
                    "program_label, raw_samples, auto_labels) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        self._entry.entry_id,
                        started,
                        ended,
                        None,
                        json.dumps(raw, ensure_ascii=False),
                        json.dumps(auto, ensure_ascii=False),
                    ),
                )
                await self._conn.commit()
            imported += 1
        _LOGGER.info(
            "Washer ML: imported %d cycle(s) (%d samples) for entry %s",
            imported,
            len(samples),
            self._entry.entry_id,
        )
        return imported


def _parse_csv(
    csv_content: str, power_entity_id: str | None
) -> list[list[float]]:
    """Parse a HA history CSV (header + ``entity_id,state,last_changed``...)."""
    out: list[list[float]] = []
    reader = csv.reader(csv_content.splitlines())
    next(reader, None)  # skip header row
    for row in reader:
        if len(row) < 3:
            continue
        entity_id, state, last_changed = row[0], row[1].strip(), row[2].strip()
        if power_entity_id and entity_id != power_entity_id:
            continue
        try:
            power = float(state)
        except (TypeError, ValueError):
            continue
        try:
            ts = datetime.fromisoformat(last_changed.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
        out.append([ts, round(power, 2)])
    out.sort(key=lambda item: item[0])
    return out