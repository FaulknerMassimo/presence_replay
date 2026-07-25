"""Edge cases from PLAN.md: empty log, unavailable lights, dead entities."""

from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.presence_replay.const import (
    CONF_DELTA_DAYS,
    CONF_LIGHTS,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.presence_replay.models import LightEvent


def _set_tz() -> None:
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Los_Angeles"))


async def _make_entry(hass: HomeAssistant, lights: list[str], **overrides) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        options={**DEFAULT_OPTIONS, CONF_LIGHTS: lights, **overrides},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_empty_log_leaves_lights_untouched_and_warns(
    hass: HomeAssistant, freezer, caplog: pytest.LogCaptureFixture
) -> None:
    _set_tz()
    hass.states.async_set("light.kitchen", "on", {"brightness": 77})
    entry = await _make_entry(hass, ["light.kitchen"], **{CONF_DELTA_DAYS: 7})

    calls = []

    async def _fake_call(domain, service, service_data=None, **kwargs):
        calls.append(service)

    with caplog.at_level(logging.WARNING), patch(
        "homeassistant.core.ServiceRegistry.async_call", side_effect=_fake_call
    ):
        await entry.runtime_data.scheduler.async_start()
        await hass.async_block_till_done()

    assert calls == []
    assert hass.states.get("light.kitchen").attributes["brightness"] == 77
    assert any("no recorded events" in message.lower() for message in caplog.messages)


async def test_unavailable_light_is_skipped_not_fatal(hass: HomeAssistant, freezer) -> None:
    _set_tz()
    hass.states.async_set("light.kitchen", STATE_UNAVAILABLE)
    entry = await _make_entry(hass, ["light.kitchen"], **{CONF_DELTA_DAYS: 1})

    yesterday_midnight = dt_util.start_of_local_day((dt_util.now() - timedelta(days=1)).date())
    entry.runtime_data.store.events.append(
        LightEvent(
            ts=(yesterday_midnight + timedelta(hours=1)).timestamp(),
            entity_id="light.kitchen",
            level=100,
        )
    )

    calls = []

    async def _fake_call(domain, service, service_data=None, **kwargs):
        calls.append(service)

    with patch("homeassistant.core.ServiceRegistry.async_call", side_effect=_fake_call):
        # Must not raise even though the only configured light is unavailable.
        await entry.runtime_data.scheduler.async_start()
        await hass.async_block_till_done()

    assert calls == []


async def test_dead_entity_is_counted_and_skipped(hass: HomeAssistant, freezer) -> None:
    _set_tz()
    # light.gone is never added to the state machine -- simulates a removed entity.
    entry = await _make_entry(hass, ["light.gone"], **{CONF_DELTA_DAYS: 1})

    yesterday_midnight = dt_util.start_of_local_day((dt_util.now() - timedelta(days=1)).date())
    entry.runtime_data.store.events.append(
        LightEvent(
            ts=(yesterday_midnight + timedelta(hours=1)).timestamp(),
            entity_id="light.gone",
            level=100,
        )
    )

    await entry.runtime_data.scheduler.async_start()
    await hass.async_block_till_done()

    assert entry.runtime_data.scheduler.status.dead_entity_count == 1
