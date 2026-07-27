"""switch.py: turn_on freezes a snapshot before starting the scheduler."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.presence_replay.const import CONF_LIGHTS, DEFAULT_OPTIONS, DOMAIN
from custom_components.presence_replay.models import LightEvent


async def _make_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        options={**DEFAULT_OPTIONS, CONF_LIGHTS: ["light.kitchen"]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_turn_on_takes_a_fresh_snapshot(hass: HomeAssistant) -> None:
    hass.states.async_set("light.kitchen", "off")
    entry = await _make_entry(hass)

    recent_ts = dt_util.utcnow().timestamp() - 3600
    entry.runtime_data.store.events.append(
        LightEvent(ts=recent_ts, entity_id="light.kitchen", level=123)
    )

    switch_entity = hass.data["entity_components"]["switch"].get_entity("switch.test_replay")
    assert switch_entity is not None

    with patch("homeassistant.core.ServiceRegistry.async_call"):
        await switch_entity.async_turn_on()
        await hass.async_block_till_done()

    snapshot = entry.runtime_data.store.snapshot
    assert snapshot is not None
    assert len(snapshot.events) == 1
    assert snapshot.events[0].level == 123
