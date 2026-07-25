"""Config flow: happy path, validation, and options-triggers-reload."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.presence_replay.const import (
    CONF_DELTA_DAYS,
    CONF_LIGHTS,
    DEFAULT_OPTIONS,
    DOMAIN,
)


async def test_user_flow_happy_path(hass: HomeAssistant) -> None:
    hass.states.async_set("light.kitchen", "on", {"brightness": 180})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Downstairs", CONF_LIGHTS: ["light.kitchen"]},
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Downstairs"
    assert result["options"][CONF_LIGHTS] == ["light.kitchen"]


async def test_user_flow_requires_at_least_one_light(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Downstairs", CONF_LIGHTS: []},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "no_lights_selected"}


async def test_options_flow_requires_at_least_one_light(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Test", options={**DEFAULT_OPTIONS, CONF_LIGHTS: ["light.kitchen"]}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**entry.options, CONF_LIGHTS: []}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "no_lights_selected"}


async def test_options_update_triggers_reload(hass: HomeAssistant) -> None:
    hass.states.async_set("light.kitchen", "on", {"brightness": 180})
    entry = MockConfigEntry(
        domain=DOMAIN, title="Test", options={**DEFAULT_OPTIONS, CONF_LIGHTS: ["light.kitchen"]}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload"
    ) as mock_reload:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {**entry.options, CONF_DELTA_DAYS: 3}
        )
        await hass.async_block_till_done()

    mock_reload.assert_called_once_with(entry.entry_id)
