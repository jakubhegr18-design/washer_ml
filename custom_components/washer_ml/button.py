"""Buttons for manual calibration and the test mode toggle."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_NAME,
    DATA_COORDINATOR,
    DOMAIN,
    PHASE_ICONS,
    PHASE_SLUGS,
    STATE_FINISHED,
    STATE_HEATING,
    STATE_RINSING,
    STATE_RUNNING,
    STATE_WASHING,
)

if TYPE_CHECKING:
    from . import WasherMlCoordinator

_LOGGER = logging.getLogger(__name__)

_CALIBRATION_PHASES = (
    STATE_RUNNING,
    STATE_HEATING,
    STATE_WASHING,
    STATE_RINSING,
    STATE_FINISHED,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: "WasherMlCoordinator" = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    slug = coordinator.entity_slug
    name = coordinator.options.get(CONF_NAME, "Pračka")
    buttons: list[Entity] = [
        CalibrationButton(coordinator, slug, name, phase)
        for phase in _CALIBRATION_PHASES
    ]
    buttons.append(TestModeToggleButton(coordinator, slug, name))
    coordinator.entities.extend(buttons)
    await async_add_entities(buttons)


class CalibrationButton(ButtonEntity):
    """Mark the current cycle with a phase label for training."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: "WasherMlCoordinator",
        slug: str,
        name: str,
        phase: str,
    ) -> None:
        self._coordinator = coordinator
        self._phase = phase
        phase_slug = PHASE_SLUGS[phase]
        self.entity_id = f"button.{slug}_kalibrace_{phase_slug}"
        self._attr_name = f"{name} kalibrace - {phase}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{phase_slug}_calibration"
        self._attr_icon = PHASE_ICONS.get(phase, "mdi:washing-machine")
        self._attr_device_class = None

    async def async_press(self) -> None:
        await self._coordinator.async_calibrate(self._phase)

    def reload_name(self) -> None:
        self._attr_name = (
            f"{self._coordinator.options.get('name', 'Pračka')} kalibrace - "
            f"{self._phase}"
        )

    def reload_config(self) -> None:
        self._attr_unique_id = (
            f"{self._coordinator.entry.entry_id}_"
            f"{PHASE_SLUGS[self._phase]}_calibration"
        )


class TestModeToggleButton(ButtonEntity):
    """Toggle the test mode switch (convenience for the sidebar panel)."""

    _attr_has_entity_name = False

    def __init__(
        self, coordinator: "WasherMlCoordinator", slug: str, name: str
    ) -> None:
        self._coordinator = coordinator
        self.entity_id = f"button.{slug}_test_mode"
        self._attr_name = f"{name} přepnout test mode"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_test_mode"
        self._attr_icon = "mdi:magnify"

    async def async_press(self) -> None:
        await self.hass.services.async_call(
            "switch",
            "toggle",
            {"entity_id": f"switch.{self._coordinator.entity_slug}_test_mode"},
        )

    def reload_name(self) -> None:
        self._attr_name = (
            f"{self._coordinator.options.get('name', 'Pračka')} přepnout test mode"
        )