"""Config and options flow for Presence Replay."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_DELTA_DAYS,
    CONF_JITTER_SECONDS,
    CONF_LIGHTS,
    CONF_MIN_DELTA,
    CONF_RESTORE_ON_STOP,
    CONF_RETENTION_DAYS,
    CONF_TRANSITION,
    CONF_USE_SNAPSHOT,
    DEFAULT_OPTIONS,
    DOMAIN,
)


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Build the shared lights + tunables schema used by both flows."""
    return vol.Schema(
        {
            vol.Required(
                CONF_LIGHTS, default=defaults.get(CONF_LIGHTS, [])
            ): EntitySelector(EntitySelectorConfig(domain="light", multiple=True)),
            vol.Required(
                CONF_DELTA_DAYS, default=defaults[CONF_DELTA_DAYS]
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=90, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_JITTER_SECONDS, default=defaults[CONF_JITTER_SECONDS]
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=3600, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_TRANSITION, default=defaults[CONF_TRANSITION]
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=300, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_RETENTION_DAYS, default=defaults[CONF_RETENTION_DAYS]
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=365, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_DEBOUNCE_SECONDS, default=defaults[CONF_DEBOUNCE_SECONDS]
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=120, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_MIN_DELTA, default=defaults[CONF_MIN_DELTA]
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=255, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_USE_SNAPSHOT, default=defaults[CONF_USE_SNAPSHOT]
            ): BooleanSelector(),
            vol.Required(
                CONF_RESTORE_ON_STOP, default=defaults[CONF_RESTORE_ON_STOP]
            ): BooleanSelector(),
        }
    )


class PresenceReplayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle initial setup of a Presence Replay entry."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            lights = user_input.get(CONF_LIGHTS) or []
            if not lights:
                errors["base"] = "no_lights_selected"
            else:
                options = {**DEFAULT_OPTIONS, CONF_LIGHTS: lights}
                return self.async_create_entry(
                    title="Presence Replay", data={}, options=options
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_LIGHTS): EntitySelector(
                    EntitySelectorConfig(domain="light", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PresenceReplayOptionsFlow:
        return PresenceReplayOptionsFlow()


class PresenceReplayOptionsFlow(OptionsFlow):
    """Handle the options flow, covering every tunable in one form."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_LIGHTS):
                errors["base"] = "no_lights_selected"
            else:
                return self.async_create_entry(data=user_input)

        defaults = {**DEFAULT_OPTIONS, **self.config_entry.options}
        schema = _options_schema(defaults)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
