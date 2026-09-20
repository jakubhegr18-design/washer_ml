"""Switch that enables the test mode (extra debug output + attributes)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_NAME, DATA_COORDINATOR, DOMAIN

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
    switches: list[Entity] = [WasherTestModeSwitch(coordinator, slug, name)]
    coordinator.entities.extend(switches)
    await async_add_entities(switches)


class WasherTestModeSwitch(SwitchEntity):
    """Switch toggling the test mode of the detector."""

    _attr_has_entity_name = False

    def __init__(
        self, coordinator: "WasherMlCoordinator", slug: str, name: str
    ) -> None:
        self._coordinator = coordinator
        self.entity_id = f"switch.{slug}_test_mode"
        self._attr_name = f"{name} test mode"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_test_mode"
        self._attr_icon = "mdi:magnify"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self._coordinator.test_mode

    async def async_turn_on(self, **kwargs: object) -> None:
        self._coordinator.set_test_mode(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        self._coordinator.set_test_mode(False)

    def reload_name(self) -> None:
        self._attr_name = (
            f"{self._coordinator.options.get('name', 'Pračka')} test mode"
        )

    def reload_config(self) -> None:
        self._attr_unique_id = (
            f"{self._coordinator.entry.entry_id}_test_mode"
        )