"""build_plan(): baseline selection, jitter, and DST-correct scheduling.

Pure-function tests -- no config entry needed, just the `hass` fixture to
get a deterministic, HA-managed timezone global for dt_util.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from homeassistant.util import dt as dt_util

from custom_components.presence_replay.models import LightEvent
from custom_components.presence_replay.scheduler import build_plan


def _set_tz(tz_name: str) -> None:
    dt_util.set_default_time_zone(dt_util.get_time_zone(tz_name))


async def test_baseline_picks_last_event_before_midnight(hass) -> None:
    _set_tz("America/Los_Angeles")
    target = date(2024, 3, 5)
    midnight_ts = dt_util.start_of_local_day(target).timestamp()

    events = [
        LightEvent(ts=midnight_ts - 3600, entity_id="light.kitchen", level=120),
        LightEvent(ts=midnight_ts - 60, entity_id="light.kitchen", level=200),
        LightEvent(ts=midnight_ts + 100, entity_id="light.kitchen", level=50),
    ]

    baseline, plan = build_plan(events, target)

    assert baseline == {"light.kitchen": 200}
    assert len(plan) == 1
    assert plan[0].level == 50
    assert plan[0].seconds_since_midnight == pytest.approx(100)


async def test_events_outside_target_day_are_excluded(hass) -> None:
    _set_tz("America/Los_Angeles")
    target = date(2024, 3, 5)
    midnight_ts = dt_util.start_of_local_day(target).timestamp()

    events = [
        LightEvent(ts=midnight_ts + 86400 + 10, entity_id="light.kitchen", level=77),
    ]

    baseline, plan = build_plan(events, target)
    assert baseline == {}
    assert plan == []


async def test_jitter_keeps_events_within_the_day(hass) -> None:
    _set_tz("America/Los_Angeles")
    target = date(2024, 3, 5)
    midnight_ts = dt_util.start_of_local_day(target).timestamp()
    next_midnight_ts = dt_util.start_of_local_day(target + timedelta(days=1)).timestamp()
    day_span = next_midnight_ts - midnight_ts

    events = [
        LightEvent(ts=midnight_ts + 5, entity_id="light.a", level=1),
        LightEvent(ts=next_midnight_ts - 5, entity_id="light.b", level=2),
    ]

    _, plan = build_plan(events, target, jitter_seconds=300)

    for scheduled in plan:
        assert 0.0 <= scheduled.seconds_since_midnight < day_span


async def test_dst_spring_forward_schedules_correct_wall_clock_time(hass) -> None:
    _set_tz("America/Los_Angeles")
    # 2024-03-10 is the US spring-forward date: 02:00 -> 03:00, a 23-hour day.
    target = date(2024, 3, 10)
    midnight = dt_util.start_of_local_day(target)
    next_midnight = dt_util.start_of_local_day(target + timedelta(days=1))
    # True elapsed seconds (via epoch, not naive datetime subtraction, which
    # silently drops the DST shift when both operands share one tzinfo object).
    assert next_midnight.timestamp() - midnight.timestamp() == 23 * 3600

    four_thirty = midnight + timedelta(hours=4, minutes=30)
    events = [LightEvent(ts=four_thirty.timestamp(), entity_id="light.kitchen", level=90)]

    _, plan = build_plan(events, target)

    assert len(plan) == 1
    # Replayed on an ordinary 24-hour day, this must still land on 04:30 --
    # not 03:30, which is what a naive epoch-offset would produce given the
    # source day was an hour short.
    replay_midnight = dt_util.start_of_local_day(date(2024, 6, 1))
    scheduled_time = replay_midnight + timedelta(seconds=plan[0].seconds_since_midnight)
    assert scheduled_time.hour == 4
    assert scheduled_time.minute == 30
