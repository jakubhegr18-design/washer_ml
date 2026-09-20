"""Washer ML - detect washing machine phases from smart plug power data.

The whole inference chain (heuristics + local decision tree) runs fully on the
device. Training and prediction never call any external service and need no
internet connection.
"""

from __future__ import annotations

import logging
import statistics
import voluptuous as vol
from collections import deque
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    ACTIVATION_SAMPLES,
    ATTR_ACTIVE_MODEL_LAYER,
    ATTR_CONFIDENCE,
    ATTR_CURRENT_POWER,
    ATTR_CYCLE_COUNT_LEARNED,
    ATTR_CYCLE_ID,
    ATTR_DETECTED_PROGRAM,
    ATTR_ELAPSED_MINUTES,
    ATTR_ESTIMATED_REMAINING,
    ATTR_RAW_PREDICTION_SCORES,
    ATTR_SAMPLES_IN_CURRENT_CYCLE,
    CONF_CONFIDENCE_THRESHOLD,
    CONF_ENTITY_SLUG,
    CONF_IDLE_THRESHOLD,
    CONF_MAX_STORED_CYCLES,
    CONF_MODEL_TYPE,
    CONF_NAME,
    CONF_POWER_SENSOR,
    CONF_RETRAIN_INTERVAL,
    CONF_SPIN_THRESHOLD,
    DATA_COORDINATOR,
    DATA_DATASTORE,
    DB_FLUSH_INTERVAL_SECONDS,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_IDLE_THRESHOLD,
    DEFAULT_MAX_STORED_CYCLES,
    DEFAULT_MODEL_TYPE,
    DEFAULT_NAME,
    DEFAULT_RETRAIN_INTERVAL,
    DEFAULT_SPIN_THRESHOLD,
    DOMAIN,
    FINISHED_IDLE_SECONDS,
    MODEL_LAYER_HEURISTIC,
    OFF_AFTER_FINISHED_SECONDS,
    PLATFORMS,
    SERVICE_IMPORT_HISTORY,
    SERVICE_RESET_CALIBRATION,
    SERVICE_RETRAIN,
    STATE_FINISHED,
    STATE_OFF,
    STATE_RUNNING,
    STATE_SPINNING,
    STATE_UNKNOWN,
)
from .data_store import WasherMlDataStore
from .ml_model import (
    WasherModel,
    build_features,
    generate_training_samples,
    train_decision_tree,
)

CONF_ENTRY_ID = "entry_id"
ATTR_CSV_PATH = "csv_path"
ATTR_CSV_CONTENT = "csv_content"

_LOGGER = logging.getLogger(__name__)

SERVICE_IMPORT_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENTRY_ID): cv.string,
        vol.Exclusive(ATTR_CSV_PATH, "source"): cv.string,
        vol.Exclusive(ATTR_CSV_CONTENT, "source"): cv.string,
    }
)
SERVICE_SIMPLE_SCHEMA = vol.Schema({vol.Optional(CONF_ENTRY_ID): cv.string})


def _get_entry_data(hass: HomeAssistant, entry_id: str | None) -> dict[str, Any]:
    """Resolve the store/coordinator payload for a service call."""
    domain_data = hass.data.get(DOMAIN, {})
    if entry_id and entry_id in domain_data:
        return domain_data[entry_id]
    for value in domain_data.values():
        if isinstance(value, dict) and DATA_COORDINATOR in value:
            return value
    raise vol.Invalid("No Washer ML config entry found")


async def _async_import_history(hass: HomeAssistant, call: ServiceCall) -> None:
    data = _get_entry_data(hass, call.data.get(CONF_ENTRY_ID))
    coordinator: "WasherMlCoordinator" = data[DATA_COORDINATOR]
    csv_path: str | None = call.data.get(ATTR_CSV_PATH)
    csv_content: str | None = call.data.get(ATTR_CSV_CONTENT)
    if csv_path is not None:
        csv_content = await hass.async_add_executor_job(
            Path(csv_path).read_text, "utf-8"
        )
    if not csv_content:
        raise vol.Invalid("Provide either csv_path or csv_content")
    await coordinator.async_import_history(csv_content)


async def _async_retrain(hass: HomeAssistant, call: ServiceCall) -> None:
    data = _get_entry_data(hass, call.data.get(CONF_ENTRY_ID))
    coordinator: "WasherMlCoordinator" = data[DATA_COORDINATOR]
    await coordinator.async_retrain()


async def _async_reset_calibration(hass: HomeAssistant, call: ServiceCall) -> None:
    data = _get_entry_data(hass, call.data.get(CONF_ENTRY_ID))
    coordinator: "WasherMlCoordinator" = data[DATA_COORDINATOR]
    await coordinator.async_reset_calibration()


class WasherMlCoordinator:
    """Subscribes to the power sensor and drives phase detection."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, data_store: WasherMlDataStore
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.data_store = data_store

        self.entities: list[Entity] = []
        self.options: dict[str, Any] = {}
        self.recent_predictions: deque[dict[str, Any]] = deque(maxlen=20)

        self._power_entity: str | None = None
        self._unsub: Any | None = None

        self._samples: list[list[float]] = []
        self._auto_labels: list[str] = []
        self._manual_markers: list[list[Any]] = []
        self._cycle_id: int | None = None

        self._active = False
        self._has_spun = False
        self._consec_active = 0
        self._idle_since: float | None = None
        self._finished_since: float | None = None
        self._started_at: float | None = None

        self._last_power: float | None = None
        self._phase = STATE_OFF
        self._confidence: float | None = None
        self._scores: dict[str, float] = {}
        self._layer = MODEL_LAYER_HEURISTIC
        self._test_mode = False

        self._last_flush: float | None = None
        self._cycles_since_retrain = 0
        self._learned_cycle_count = 0
        self._avg_cycle_duration_min: float | None = None
        self._model: WasherModel | None = None
        self._model_trained_at: str | None = None

        self.reload_options()

    # ------------------------------------------------------------------ config

    def reload_options(self) -> None:
        merged = {**self.entry.data, **self.entry.options}
        self.options = {
            CONF_POWER_SENSOR: merged.get(CONF_POWER_SENSOR),
            CONF_NAME: str(merged.get(CONF_NAME, DEFAULT_NAME)),
            CONF_MODEL_TYPE: str(
                merged.get(CONF_MODEL_TYPE, DEFAULT_MODEL_TYPE)
            ),
            CONF_CONFIDENCE_THRESHOLD: float(
                merged.get(CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD)
            ),
            CONF_RETRAIN_INTERVAL: int(
                merged.get(CONF_RETRAIN_INTERVAL, DEFAULT_RETRAIN_INTERVAL)
            ),
            CONF_MAX_STORED_CYCLES: int(
                merged.get(CONF_MAX_STORED_CYCLES, DEFAULT_MAX_STORED_CYCLES)
            ),
            CONF_IDLE_THRESHOLD: float(
                merged.get(CONF_IDLE_THRESHOLD, DEFAULT_IDLE_THRESHOLD)
            ),
            CONF_SPIN_THRESHOLD: float(
                merged.get(CONF_SPIN_THRESHOLD, DEFAULT_SPIN_THRESHOLD)
            ),
        }
        if self._model is None:
            self._model = WasherModel(self.options)
        else:
            self._model.reload_from(self.options)

    @property
    def power_entity(self) -> str | None:
        return self._power_entity

    @property
    def entity_slug(self) -> str:
        return str(self.entry.data.get(CONF_ENTITY_SLUG) or "pracka")

    # ------------------------------------------------------------- properties

    @property
    def phase_state(self) -> str:
        return self._phase

    @property
    def confidence(self) -> float | None:
        return self._confidence

    @property
    def test_mode(self) -> bool:
        return self._test_mode

    @property
    def model_trained_at(self) -> str | None:
        return self._model_trained_at

    @property
    def learned_cycle_count(self) -> int:
        return self._learned_cycle_count

    def set_test_mode(self, value: bool) -> None:
        self._test_mode = bool(value)
        self._publish()

    @property
    def elapsed_minutes(self) -> int | None:
        if self._active and self._started_at is not None:
            return int(
                (dt_util.utcnow().timestamp() - self._started_at) / 60.0
            )
        return None

    @property
    def remaining_minutes(self) -> int | None:
        if (
            not self._active
            or self._started_at is None
            or self._avg_cycle_duration_min is None
        ):
            return None
        elapsed = (dt_util.utcnow().timestamp() - self._started_at) / 60.0
        remaining = int(self._avg_cycle_duration_min - elapsed)
        return remaining if remaining > 2 else None

    @property
    def detected_program(self) -> str | None:
        if not self._active:
            return None
        max_power = max((p for _, p in self._samples), default=0.0)
        if max_power > self.options[CONF_SPIN_THRESHOLD]:
            return "Standardní"
        if max_power > 400:
            return "Jemný program"
        return "Úsporný / rychlý program"

    @property
    def state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            ATTR_CONFIDENCE: (
                round(self._confidence, 1) if self._confidence is not None else None
            ),
            ATTR_CURRENT_POWER: self._last_power,
            ATTR_ELAPSED_MINUTES: self.elapsed_minutes,
            ATTR_ESTIMATED_REMAINING: self.remaining_minutes,
            ATTR_DETECTED_PROGRAM: self.detected_program,
            ATTR_CYCLE_COUNT_LEARNED: self._learned_cycle_count,
        }
        if self._cycle_id is not None:
            attrs[ATTR_CYCLE_ID] = self._cycle_id
        if self._test_mode:
            attrs[ATTR_RAW_PREDICTION_SCORES] = self._scores
            attrs[ATTR_ACTIVE_MODEL_LAYER] = self._layer
            attrs[ATTR_SAMPLES_IN_CURRENT_CYCLE] = len(self._samples)
        return attrs

    # ------------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        self.reload_options()
        self._model = WasherModel(self.options)
        model_path = self._model_file_path()
        loaded = await self.hass.async_add_executor_job(
            self._model.load_json_file, model_path
        )
        if loaded:
            self._model_trained_at = _file_timestamp(model_path)
            _LOGGER.info("Washer ML: loaded trained model for %s", self.entity_slug)
        await self.async_refresh_stats()
        await self._resubscribe()
        # Initial sample so the sensor shows something right away.
        state = self.hass.states.get(self._power_entity or "")
        if state and state.state not in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                await self._process_sample(
                    dt_util.utcnow().timestamp(), float(state.state)
                )
            except (TypeError, ValueError):
                pass
        self._publish()

    async def async_shutdown(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._cycle_id is not None:
            await self.data_store.async_upsert_cycle(
                self._cycle_id, raw_samples=self._samples, auto_labels=self._auto_labels
            )
        await self.data_store.async_close()

    async def _resubscribe(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        self._power_entity = self.options.get(CONF_POWER_SENSOR)
        if not self._power_entity:
            return
        self._unsub = async_track_state_change_event(
            self.hass, [self._power_entity], self._handle_power_event
        )

    def _model_file_path(self) -> Path:
        return Path(
            self.hass.config.path("washer_ml", self.entry.entry_id, "model.json")
        )

    # -------------------------------------------------------------- detection

    @callback
    def _handle_power_event(self, event: Any) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        value = new_state.state
        if value in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        try:
            power = float(value)
        except (TypeError, ValueError):
            return
        self.hass.async_create_task(
            self._process_sample(dt_util.utcnow().timestamp(), power)
        )

    async def _process_sample(self, ts: float, power: float) -> None:
        self._last_power = round(power, 2)
        idle = self.options[CONF_IDLE_THRESHOLD]

        if not self._active and power <= idle:
            self._consec_active = 0
            if self._finished_since is not None:
                if ts - self._finished_since >= OFF_AFTER_FINISHED_SECONDS:
                    self._finished_since = None
                    self._phase = STATE_OFF
                else:
                    self._phase = STATE_FINISHED
            else:
                self._phase = STATE_OFF
            self._publish()
            return

        if not self._active:
            self._consec_active += 1
            self._phase = STATE_RUNNING
            if self._consec_active < ACTIVATION_SAMPLES:
                self._publish()
                return
            self._active = True
            self._started_at = ts
            self._samples = [[ts, self._last_power]]
            self._auto_labels = []
            self._manual_markers = []
            self._has_spun = False
            self._idle_since = None
            self._finished_since = None
            self._cycle_id = await self.data_store.async_begin_cycle(ts)
            self._publish()
            return

        self._samples.append([ts, self._last_power])

        if power <= idle:
            if self._idle_since is None:
                self._idle_since = ts
            if ts - self._idle_since >= FINISHED_IDLE_SECONDS:
                await self._finish_cycle(ts)
                self._phase = STATE_FINISHED
                self._finished_since = ts
                self._active = False
                self._idle_since = None
                self._publish()
                return
        else:
            self._idle_since = None

        assert self._model is not None
        features = build_features(self._samples, len(self._samples) - 1)
        phase, confidence, scores, layer = self._model.predict(
            features, self._has_spun
        )
        if phase == STATE_SPINNING:
            self._has_spun = True
        self._auto_labels.append(phase)
        self._layer = layer
        self._scores = scores

        if confidence < self.options[CONF_CONFIDENCE_THRESHOLD]:
            self._phase = STATE_UNKNOWN
            self._confidence = round(confidence, 1)
        else:
            self._phase = phase
            self._confidence = round(confidence, 1)

        self._record_prediction(features, phase, confidence, layer)
        if self._test_mode:
            _LOGGER.debug(
                "Washer ML decision: features=%s phase=%s conf=%.1f layer=%s",
                features,
                phase,
                confidence,
                layer,
            )
        await self._maybe_flush()
        self._publish()

    async def _maybe_flush(self) -> None:
        if self._cycle_id is None:
            return
        now = dt_util.utcnow().timestamp()
        if self._last_flush is None or now - self._last_flush >= DB_FLUSH_INTERVAL_SECONDS:
            await self.data_store.async_upsert_cycle(
                self._cycle_id,
                raw_samples=self._samples,
                phase_labels=self._manual_markers,
                auto_labels=self._auto_labels,
            )
            self._last_flush = now

    async def _finish_cycle(self, ended_at: float) -> None:
        if self._cycle_id is not None:
            await self.data_store.async_upsert_cycle(
                self._cycle_id,
                ended_at=ended_at,
                raw_samples=self._samples,
                phase_labels=self._manual_markers,
                auto_labels=self._auto_labels,
                program_label=None,
            )
            await self.data_store.async_prune_cycles(
                self.options[CONF_MAX_STORED_CYCLES]
            )
            self._cycles_since_retrain += 1
            self._cycle_id = None
        self._samples = []
        self._auto_labels = []
        self._manual_markers = []
        if self._cycles_since_retrain >= self.options[CONF_RETRAIN_INTERVAL]:
            self._cycles_since_retrain = 0
            self.hass.async_create_task(self.async_retrain())
        await self.async_refresh_stats()

    def _record_prediction(
        self,
        features: list[float],
        phase: str,
        confidence: float,
        layer: str,
    ) -> None:
        self.recent_predictions.append(
            {
                "timestamp": dt_util.utcnow().isoformat(),
                "phase": phase,
                "confidence": round(confidence, 1),
                "layer": layer,
                "features": features,
            }
        )

    # ------------------------------------------------------------ calibration

    async def async_calibrate(self, phase: str) -> None:
        """Handle a calibration button press."""
        now = dt_util.utcnow().timestamp()
        if phase == STATE_FINISHED:
            if self._cycle_id is None:
                _LOGGER.warning(
                    "Washer ML: cannot finish cycle - no active recording"
                )
                return
            await self._finish_cycle(now)
            self._phase = STATE_FINISHED
            self._finished_since = now
            self._active = False
            self._publish()
            return
        if phase == STATE_RUNNING and not self._active:
            self._active = True
            self._started_at = now
            self._samples = []
            self._auto_labels = []
            self._manual_markers = []
            self._has_spun = False
            self._idle_since = None
            self._finished_since = None
            self._cycle_id = await self.data_store.async_begin_cycle(now)
        if not self._active or self._cycle_id is None:
            _LOGGER.warning(
                "Washer ML: calibration ignored (no active cycle), phase=%s", phase
            )
            return
        self._manual_markers.append([now, phase])
        await self.data_store.async_upsert_cycle(
            self._cycle_id, phase_labels=self._manual_markers
        )
        self._phase = phase
        self._publish()

    async def async_reset_calibration(self) -> None:
        """Abort the current recording (e.g. mislabelled cycle)."""
        if self._cycle_id is not None:
            await self.data_store.async_delete_cycle(self._cycle_id)
        self._cycle_id = None
        self._samples = []
        self._auto_labels = []
        self._manual_markers = []
        self._active = False
        self._has_spun = False
        self._started_at = None
        self._idle_since = None
        self._finished_since = None
        self._phase = STATE_OFF
        self._confidence: float | None = None
        self._publish()

    # ----------------------------------------------------------------- retrain

    async def async_retrain(self) -> None:
        """Rebuild the decision tree from all stored training samples."""
        cycles = await self.data_store.async_load_cycles()
        features, labels = generate_training_samples(cycles)
        if len(labels) < 50:
            _LOGGER.info(
                "Washer ML: skipping retrain, only %d training sample(s)",
                len(labels),
            )
            return
        assert self._model is not None
        tree = await self.hass.async_add_executor_job(
            train_decision_tree, features, labels, 6, 5
        )
        self._model.set_tree(tree)
        await self.hass.async_add_executor_job(
            self._model.to_json_file, self._model_file_path()
        )
        self._model_trained_at = _file_timestamp(self._model_file_path())
        _LOGGER.info(
            "Washer ML: retrained decision tree on %d samples from %d cycles",
            len(labels),
            len(cycles),
        )
        await self.async_refresh_stats()
        self._publish()

    async def async_import_history(self, csv_content: str) -> None:
        if not csv_content:
            raise vol.Invalid("csv_content is empty")
        await self.data_store.async_import_csv(
            csv_content,
            self._power_entity,
            self.options[CONF_IDLE_THRESHOLD],
        )
        await self.async_refresh_stats()
        self._publish()

    async def async_refresh_stats(self) -> None:
        cycles = await self.data_store.async_load_cycles()
        self._learned_cycle_count = sum(
            1
            for cycle in cycles
            if cycle["phase_labels"] or cycle["auto_labels"]
        )
        durations = [
            (cycle["ended_at"] - cycle["started_at"]) / 60.0
            for cycle in cycles
            if cycle["ended_at"] and len(cycle["raw_samples"]) > 20
        ]
        self._avg_cycle_duration_min = (
            round(statistics.mean(durations), 1) if durations else None
        )

    # ---------------------------------------------------------------- publish

    def _publish(self) -> None:
        for entity in self.entities:
            if entity.entity_id:
                entity.async_write_ha_state()


def _file_timestamp(path: Path) -> str:
    try:
        return dt_util.as_local(dt_util.utc_from_timestamp(path.stat().st_mtime)).isoformat()
    except OSError:
        return ""


def _register_services(hass: HomeAssistant) -> None:
    if hass.data[DOMAIN].get("services_ready"):
        return
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_HISTORY,
        _async_import_history,
        SERVICE_IMPORT_HISTORY_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RETRAIN, _async_retrain, SERVICE_SIMPLE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_CALIBRATION,
        _async_reset_calibration,
        SERVICE_SIMPLE_SCHEMA,
    )
    hass.data[DOMAIN]["services_ready"] = True


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up dedicated only via config entries."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Washer ML from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    data_store = WasherMlDataStore(hass, entry)
    await data_store.async_open()
    coordinator = WasherMlCoordinator(hass, entry, data_store)
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        DATA_DATASTORE: data_store,
    }
    _register_services(hass)
    await coordinator.async_start()
    from .panel import async_setup_panel

    await async_setup_panel(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(
        entry.add_update_listener(_async_update_entry_listener)
    )
    return True


async def _async_update_entry_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    coordinator: WasherMlCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    coordinator.reload_options()
    await coordinator._resubscribe()
    for entity in coordinator.entities:
        if hasattr(entity, "reload_name"):
            entity.reload_name()
    for entity in coordinator.entities:
        if hasattr(entity, "reload_config"):
            entity.reload_config()
    coordinator._publish()
    from .panel import async_setup_panel

    await async_setup_panel(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator: WasherMlCoordinator = data[DATA_COORDINATOR]
        await coordinator.async_shutdown()
        from .panel import async_unset_panel

        async_unset_panel(hass)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to a later version (schema changes)."""
    return True