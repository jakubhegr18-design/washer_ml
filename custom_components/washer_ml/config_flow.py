"""Config flow and options flow for Washer ML."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_CONFIDENCE_THRESHOLD,
    CONF_ENTITY_SLUG,
    CONF_IDLE_THRESHOLD,
    CONF_MAX_STORED_CYCLES,
    CONF_MODEL_TYPE,
    CONF_NAME,
    CONF_POWER_SENSOR,
    CONF_RETRAIN_INTERVAL,
    CONF_SPIN_THRESHOLD,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_IDLE_THRESHOLD,
    DEFAULT_MAX_STORED_CYCLES,
    DEFAULT_MODEL_TYPE,
    DEFAULT_NAME,
    DEFAULT_RETRAIN_INTERVAL,
    DEFAULT_SPIN_THRESHOLD,
    DOMAIN,
    MODEL_DECISION_TREE,
    MODEL_SIMPLE_THRESHOLD,
)

_MODEL_OPTIONS = [
    selector.SelectOptionDict(
        value=MODEL_SIMPLE_THRESHOLD,
        label="Heuristika (jednoduché prahy, funguje hned)",
    ),
    selector.SelectOptionDict(
        value=MODEL_DECISION_TREE,
        label="Rozhodovací strom (učí se z označených cyklů)",
    ),
]


class WasherMlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    def _find_power_sensor(hass: HomeAssistant) -> str | None:
        """Suggest an existing power sensor as a sensible default."""
        for state in hass.states.async_all():
            if not state.entity_id.startswith("sensor."):
                continue
            attributes = state.attributes
            if attributes.get("device_class") == "power" or attributes.get(
                "unit_of_measurement"
            ) in ("W", "kW"):
                return state.entity_id
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = (user_input.get(CONF_NAME) or DEFAULT_NAME).strip() or DEFAULT_NAME
            entity_slug = slugify(name) or "pracka"
            self._data = {
                **user_input,
                CONF_NAME: name,
                CONF_ENTITY_SLUG: entity_slug,
            }
            return await self.async_step_model()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POWER_SENSOR, default=self._find_power_sensor(self.hass)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): selector.TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title=str(self._data[CONF_NAME]), data=self._data
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_MODEL_TYPE,
                    default=self._data.get(CONF_MODEL_TYPE, DEFAULT_MODEL_TYPE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_MODEL_OPTIONS)
                ),
                vol.Required(
                    CONF_CONFIDENCE_THRESHOLD,
                    default=self._data.get(
                        CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, unit_of_measurement="%"
                    )
                ),
            }
        )
        return self.async_show_form(step_id="model", data_schema=schema)

    @staticmethod
    async def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return WasherMlOptionsFlow(config_entry)


class WasherMlOptionsFlow(config_entries.OptionsFlow):
    """Options flow - every value can be edited after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._options: dict[str, Any] = {}

    @staticmethod
    async def async_show_advanced_options() -> None:
        """Expose the optional advanced screen to the frontend."""

    def _base_options(self) -> dict[str, Any]:
        return {**self._entry.data, **self._entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_advanced()

        base = self._base_options()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POWER_SENSOR, default=base.get(CONF_POWER_SENSOR)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_NAME, default=base.get(CONF_NAME, DEFAULT_NAME)
                ): selector.TextSelector(),
                vol.Required(
                    CONF_MODEL_TYPE,
                    default=base.get(CONF_MODEL_TYPE, DEFAULT_MODEL_TYPE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=_MODEL_OPTIONS)
                ),
                vol.Required(
                    CONF_CONFIDENCE_THRESHOLD,
                    default=float(
                        base.get(
                            CONF_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, unit_of_measurement="%"
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(title="", data=self._options)

        base = self._base_options()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RETRAIN_INTERVAL,
                    default=int(
                        base.get(
                            CONF_RETRAIN_INTERVAL, DEFAULT_RETRAIN_INTERVAL
                        )
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=100, step=1)
                ),
                vol.Required(
                    CONF_MAX_STORED_CYCLES,
                    default=int(
                        base.get(CONF_MAX_STORED_CYCLES, DEFAULT_MAX_STORED_CYCLES)
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=1000, step=10)
                ),
                vol.Required(
                    CONF_IDLE_THRESHOLD,
                    default=float(
                        base.get(CONF_IDLE_THRESHOLD, DEFAULT_IDLE_THRESHOLD)
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=1, unit_of_measurement="W"
                    )
                ),
                vol.Required(
                    CONF_SPIN_THRESHOLD,
                    default=float(
                        base.get(CONF_SPIN_THRESHOLD, DEFAULT_SPIN_THRESHOLD)
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=2500, step=50, unit_of_measurement="W"
                    )
                ),
            }
        )
        return self.async_show_form(step_id="advanced", data_schema=schema)