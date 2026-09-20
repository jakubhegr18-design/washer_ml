"""Diagnostics support for Washer ML."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant

from .const import DATA_COORDINATOR, DATA_DATASTORE, DOMAIN

if TYPE_CHECKING:
    from . import WasherMlCoordinator
    from .data_store import WasherMlDataStore

_TO_REDACT = {CONF_UNIQUE_ID, "entry_id", "power_sensor"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data[DOMAIN].get(entry.entry_id)
    if not data:
        return {"error": "entry_not_loaded"}
    coordinator: "WasherMlCoordinator" = data[DATA_COORDINATOR]
    store: "WasherMlDataStore" = data[DATA_DATASTORE]

    cycles = await store.async_load_cycles()
    labeled = sum(
        1 for cycle in cycles if cycle["phase_labels"] or cycle["auto_labels"]
    )

    return async_redact_data(
        {
            "config": entry.as_dict(),
            "washer_ml": {
                "options": coordinator.options,
                "entity_slug": coordinator.entity_slug,
                "stored_cycles": len(cycles),
                "cycles_used_for_training": labeled,
                "model_trained_at": coordinator.model_trained_at,
                "model_file": str(store.db_path.parent / "model.json"),
                "test_mode_enabled": coordinator.test_mode,
                "avg_cycle_duration_min": coordinator._avg_cycle_duration_min,
                "recent_predictions": list(coordinator.recent_predictions),
            },
        },
        _TO_REDACT,
    )