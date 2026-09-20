"""Sensors exposed by Washer ML (phase state + confidence)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import StateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_NAME,
    DATA_COORDINATOR,
    DOMAIN,
    PHASE_ICONS,
)

if TYPE_CHECKING:
    from . import WasherMlCoordinator

_LOGGER = logging.getLogger(__name__)


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
    sensors: list[Entity] = [
        WasherStateSensor(coordinator, slug, name),
        WasherConfidenceSensor(coordinator, slug, name),
    ]
    coordinator.entities.extend(sensors)
    await async_add_entities(sensors)


class WasherStateSensor(SensorEntity):
    """Current detected washing phase (string state)."""

    _attr_has_entity_name = False

    def __init__(
        self, coordinator: "WasherMlCoordinator", slug: str, name: str
    ) -> None:
        self._coordinator = coordinator
        self._slug = slug
        self.entity_id = f"sensor.{slug}_stav"
        self._attr_name = f"{name} stav"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_state"
        self._attr_icon = PHASE_ICONS.get(
            coordinator.phase_state, "mdi:washing-machine"
        )
        self._attr_device_class = None
        self._attr_entity_category = None

    @property
    def native_value(self) -> str:
        return self._coordinator.phase_state

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return dict(self._coordinator.state_attributes)

    @property
    def available(self) -> bool:
        return self._coordinator.power_entity is not None

    def reload_name(self) -> None:
        self._attr_name = (
            f"{self._coordinator.options.get('name', 'Pračka')} stav"
        )

    @property
    def icon(self) -> str:
        return PHASE_ICONS.get(
            self._coordinator.phase_state, "mdi:washing-machine"
        )

    def reload_config(self) -> None:
        self._attr_name = (
            f"{self._coordinator.options.get('name', 'Pračka')} stav"
        )
        self._attr_unique_id = f"{self._coordinator.entry.entry_id}_state"


class WasherConfidenceSensor(SensorEntity):
    """Model confidence for the current prediction (0-100 %)."""

    _attr_has_entity_name = False

    def __init__(
        self, coordinator: "WasherMlCoordinator", slug: str, name: str
    ) -> None:
        self._coordinator = coordinator
        self._slug = slug
        self.entity_id = f"sensor.{slug}_confidence"
        self._attr_name = f"{name} confidence"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_confidence"
        self._attr_icon = "mdi:gauge"
        self._attr_state_class = StateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_class = None

    @property
    def native_value(self) -> float | None:
        return self._coordinator.confidence

    @property
    def available(self) -> bool:
        return self._coordinator.power_entity is not None

    def reload_name(self) -> None:
        self._attr_name = (
            f"{self._coordinator.options.get('name', 'Pračka')} confidence"
        )

    def reload_config(self) -> None:
        self._attr_name = (
            f"{self._coordinator.options.get('name', 'Pračka')} confidence"
        )
        self._attr_unique_id = f"{self._coordinator.entry.entry_id}_confidence"