"""recorder.py: debounce collapses a burst into one event; min_delta drops noise."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.presence_replay.const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_LIGHTS,
    CONF_MIN_DELTA,
    DEFAULT_OPTIONS,
    DOMAIN,
)


async def _setup_entry(hass: HomeAssistant, **option_overrides) -> MockConfigEntry:
    hass.states.async_set("light.kitchen", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        options={**DEFAULT_OPTIONS, CONF_LIGHTS: ["light.kitchen"], **option_overrides},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_debounce_collapses_burst_into_one_event(hass: HomeAssistant, freezer) -> None:
    entry = await _setup_entry(hass, **{CONF_DEBOUNCE_SECONDS: 5, CONF_MIN_DELTA: 0})
    store = entry.runtime_data.store

    burst_start = dt_util.utcnow()
    for i in range(40):
        freezer.tick(timedelta(milliseconds=50))
        async_fire_time_changed(hass)
        hass.states.async_set("light.kitchen", "on", {"brightness": 100 + i})
        await hass.async_block_till_done()

    # Burst is still within the debounce window: nothing recorded yet.
    assert store.events == []

    # Let the debounce window elapse.
    freezer.tick(timedelta(seconds=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(store.events) == 1
    event = store.events[0]
    assert event.entity_id == "light.kitchen"
    assert event.level == 139  # final settled level of the burst
    assert event.ts == pytest.approx(burst_start.timestamp(), abs=1)


async def test_min_delta_drops_small_changes(hass: HomeAssistant, freezer) -> None:
    entry = await _setup_entry(hass, **{CONF_DEBOUNCE_SECONDS: 1, CONF_MIN_DELTA: 3})
    store = entry.runtime_data.store

    hass.states.async_set("light.kitchen", "on", {"brightness": 100})
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(store.events) == 1

    # 2-step brightness change is below min_delta=3 -- should produce no event.
    hass.states.async_set("light.kitchen", "on", {"brightness": 102})
    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(store.events) == 1
