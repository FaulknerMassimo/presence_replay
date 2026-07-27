"""Scheduler behaviour: catch-up, restore-on-stop, feedback loop, unload cleanup."""

from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.presence_replay.const import (
    CONF_DELTA_DAYS,
    CONF_LIGHTS,
    CONF_RESTORE_ON_STOP,
    CONF_USE_SNAPSHOT,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from custom_components.presence_replay.models import LightEvent, SnapshotData


def _set_tz() -> None:
    dt_util.set_default_time_zone(dt_util.get_time_zone("America/Los_Angeles"))


async def _make_entry(hass: HomeAssistant, **option_overrides) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        options={**DEFAULT_OPTIONS, CONF_LIGHTS: ["light.kitchen"], **option_overrides},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _patch_light_calls():
    calls: list[tuple[str, int | None]] = []

    async def _fake_call(domain, service, service_data=None, **kwargs):
        calls.append((service, (service_data or {}).get("brightness")))

    return calls, patch("homeassistant.core.ServiceRegistry.async_call", side_effect=_fake_call)


async def test_catchup_applies_only_latest_past_event(hass: HomeAssistant, freezer) -> None:
    _set_tz()
    hass.states.async_set("light.kitchen", "off")

    now = dt_util.start_of_local_day(dt_util.now()) + timedelta(hours=19)
    freezer.move_to(now)

    entry = await _make_entry(hass, **{CONF_DELTA_DAYS: 1})

    yesterday_midnight = dt_util.start_of_local_day((now - timedelta(days=1)).date())
    store = entry.runtime_data.store
    store.events.extend(
        [
            LightEvent(
                ts=(yesterday_midnight + timedelta(hours=6)).timestamp(),
                entity_id="light.kitchen",
                level=255,
            ),
            LightEvent(
                ts=(yesterday_midnight + timedelta(hours=18)).timestamp(),
                entity_id="light.kitchen",
                level=80,
            ),
            LightEvent(
                ts=(yesterday_midnight + timedelta(hours=22)).timestamp(),
                entity_id="light.kitchen",
                level=0,
            ),
        ]
    )

    calls, patcher = _patch_light_calls()
    with patcher:
        await entry.runtime_data.scheduler.async_start()
        await hass.async_block_till_done()

    assert calls == [("turn_on", 80)]


async def test_restore_on_stop_reverts_prior_state(hass: HomeAssistant, freezer) -> None:
    _set_tz()
    hass.states.async_set("light.kitchen", "on", {"brightness": 50})
    entry = await _make_entry(hass, **{CONF_RESTORE_ON_STOP: True})

    calls, patcher = _patch_light_calls()
    with patcher:
        await entry.runtime_data.scheduler.async_start()
        await hass.async_block_till_done()
        await entry.runtime_data.scheduler.async_stop()
        await hass.async_block_till_done()

    assert ("turn_on", 50) in calls


async def test_restore_on_stop_disabled_does_not_reapply(hass: HomeAssistant, freezer) -> None:
    _set_tz()
    hass.states.async_set("light.kitchen", "on", {"brightness": 50})
    entry = await _make_entry(hass, **{CONF_RESTORE_ON_STOP: False})

    calls, patcher = _patch_light_calls()
    with patcher:
        await entry.runtime_data.scheduler.async_start()
        await hass.async_block_till_done()
        calls.clear()
        await entry.runtime_data.scheduler.async_stop()
        await hass.async_block_till_done()

    assert calls == []


async def test_feedback_loop_warns_once(
    hass: HomeAssistant, freezer, caplog: pytest.LogCaptureFixture
) -> None:
    _set_tz()
    hass.states.async_set("light.kitchen", "off")
    entry = await _make_entry(hass, **{CONF_DELTA_DAYS: 1, CONF_USE_SNAPSHOT: False})

    yesterday_midnight = dt_util.start_of_local_day((dt_util.now() - timedelta(days=1)).date())
    store = entry.runtime_data.store
    store.events.append(
        LightEvent(
            ts=(yesterday_midnight + timedelta(hours=6)).timestamp(),
            entity_id="light.kitchen",
            level=100,
            replay=True,
        )
    )

    _, patcher = _patch_light_calls()
    with caplog.at_level(logging.WARNING), patcher:
        await entry.runtime_data.scheduler.async_start()
        await hass.async_block_till_done()

    assert any("previous replay" in message for message in caplog.messages)


async def test_snapshot_cycles_instead_of_freezing_past_delta_days(
    hass: HomeAssistant, freezer
) -> None:
    """Once real time runs past the days a snapshot actually covers, the
    replay must cycle back through those same dates, not silently freeze."""
    _set_tz()
    hass.states.async_set("light.kitchen", "off")

    now = dt_util.start_of_local_day(dt_util.now())
    freezer.move_to(now)

    entry = await _make_entry(hass, **{CONF_DELTA_DAYS: 2, CONF_USE_SNAPSHOT: True})

    day0 = (now - timedelta(days=2)).date()
    day1 = (now - timedelta(days=1)).date()
    entry.runtime_data.store.snapshot = SnapshotData(
        created=now.timestamp(),
        days=2,
        events=[
            LightEvent(
                ts=dt_util.start_of_local_day(day0).timestamp() + 3600,
                entity_id="light.kitchen",
                level=50,
            ),
            LightEvent(
                ts=dt_util.start_of_local_day(day1).timestamp() + 3600,
                entity_id="light.kitchen",
                level=150,
            ),
        ],
    )

    scheduler = entry.runtime_data.scheduler
    _, patcher = _patch_light_calls()
    with patcher:
        await scheduler._rebuild_and_apply(dt_util.now())
        assert scheduler.status.replaying_date == day0

        freezer.move_to(now + timedelta(days=1))
        await scheduler._rebuild_and_apply(dt_util.now())
        assert scheduler.status.replaying_date == day1

        # Old rolling formula would target `now`'s own date here -- inside
        # the trip, past anything the snapshot contains. It must wrap back
        # to day0 instead of finding no events and freezing the house.
        freezer.move_to(now + timedelta(days=2))
        await scheduler._rebuild_and_apply(dt_util.now())
        assert scheduler.status.replaying_date == day0

        freezer.move_to(now + timedelta(days=5))
        await scheduler._rebuild_and_apply(dt_util.now())
        assert scheduler.status.replaying_date == day1


async def test_unload_cancels_all_listeners_and_timers(hass: HomeAssistant, freezer) -> None:
    _set_tz()
    hass.states.async_set("light.kitchen", "on", {"brightness": 90})
    entry = await _make_entry(hass, **{CONF_DELTA_DAYS: 1})

    yesterday_midnight = dt_util.start_of_local_day((dt_util.now() - timedelta(days=1)).date())
    store = entry.runtime_data.store
    store.events.append(
        LightEvent(
            ts=(yesterday_midnight + timedelta(hours=23)).timestamp(),
            entity_id="light.kitchen",
            level=10,
        )
    )

    runtime = entry.runtime_data
    await runtime.scheduler.async_start()
    await hass.async_block_till_done()

    # A pending debounce timer too, to prove capture cleanup also fires.
    hass.states.async_set("light.kitchen", "on", {"brightness": 20})
    await hass.async_block_till_done()
    assert runtime.capture._timers  # a debounce timer is pending

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert runtime.capture._unsub_state is None
    assert runtime.capture._timers == {}
    assert runtime.scheduler._unsub_next is None
    assert runtime.scheduler._unsub_midnight is None
