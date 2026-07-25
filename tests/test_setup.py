"""Full entry setup/unload: confirms the skeleton wires together cleanly."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.presence_replay.const import CONF_LIGHTS, DEFAULT_OPTIONS, DOMAIN


async def _make_entry(hass: HomeAssistant, lights: list[str]) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        options={**DEFAULT_OPTIONS, CONF_LIGHTS: lights},
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    hass.states.async_set("light.kitchen", "on", {"brightness": 180})
    entry = await _make_entry(hass, ["light.kitchen"])

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data is not None
    assert hass.states.get("switch.test_replay") is not None
    assert hass.states.get("sensor.test_events_recorded") is not None
    assert hass.states.get("button.test_take_snapshot") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
