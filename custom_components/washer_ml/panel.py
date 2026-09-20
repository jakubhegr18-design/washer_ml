"""Register the Washer ML sidebar panel and serve its frontend files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components.frontend import async_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENTITY_SLUG,
    CONF_NAME,
    CONF_RETRAIN_INTERVAL,
    DEFAULT_RETRAIN_INTERVAL,
    DOMAIN,
    PANEL_REGISTERED_KEY,
    PANEL_STATIC_KEY,
)

_PANEL_URL = "washer-ml"
_WEBCOMPONENT = "washer-panel"
_STATIC_BASE = "/local/washer_ml"


def _build_config(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    base = {**entry.data, **entry.options}
    slug = base.get(CONF_ENTITY_SLUG) or "pracka"
    name = str(base.get(CONF_NAME) or "Pračka")
    return {
        "name": name,
        "entry_id": entry.entry_id,
        "retrain_interval": int(
            base.get(CONF_RETRAIN_INTERVAL, DEFAULT_RETRAIN_INTERVAL)
        ),
        "state_entity": f"sensor.{slug}_stav",
        "confidence_entity": f"sensor.{slug}_confidence",
        "test_mode_entity": f"switch.{slug}_test_mode",
        "buttons": {
            "running": f"button.{slug}_kalibrace_spusteno",
            "heating": f"button.{slug}_kalibrace_ohrivani",
            "washing": f"button.{slug}_kalibrace_prani",
            "rinsing": f"button.{slug}_kalibrace_machani",
            "spinning": f"button.{slug}_kalibrace_odstredovani",
            "finished": f"button.{slug}_kalibrace_skonceno",
        },
    }


async def async_setup_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the custom panel and the static frontend assets."""
    frontend_dir = Path(__file__).parent / "frontend"
    if not hass.data[DOMAIN].get(PANEL_STATIC_KEY):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_STATIC_BASE, str(frontend_dir), True)]
        )
        hass.data[DOMAIN][PANEL_STATIC_KEY] = True

    config = _build_config(hass, entry)
    if hass.data[DOMAIN].get(PANEL_REGISTERED_KEY):
        try:
            async_remove_panel(hass, _PANEL_URL)
        except (KeyError, ValueError):
            pass
    await async_register_panel(
        hass,
        webcomponent_name=_WEBCOMPONENT,
        frontend_url_path=_PANEL_URL,
        module_url=f"{_STATIC_BASE}/washer-panel.js?v={entry.entry_id}",
        config=config,
        sidebar_title=config["name"],
        sidebar_icon="mdi:washing-machine",
        require_admin=False,
    )
    hass.data[DOMAIN][PANEL_REGISTERED_KEY] = True


def async_unset_panel(hass: HomeAssistant) -> None:
    """Remove the custom panel when the entry is unloaded."""
    try:
        async_remove_panel(hass, _PANEL_URL)
    except (KeyError, ValueError):
        pass
    hass.data[DOMAIN][PANEL_REGISTERED_KEY] = False