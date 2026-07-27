"""Plan building and point-in-time replay engine.

Deliberately not a sleeping asyncio task (the prototype's approach, which
cannot survive a restart and cannot be cancelled cleanly). Instead only the
*next* event is ever scheduled, via `async_track_point_in_time`; its
callback applies the light action and schedules the following one. A
separate point-in-time callback at local midnight rebuilds the day's plan.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_TRANSITION
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DELTA_DAYS,
    CONF_JITTER_SECONDS,
    CONF_LIGHTS,
    CONF_RESTORE_ON_STOP,
    CONF_TRANSITION,
    CONF_USE_SNAPSHOT,
    DEFAULT_DELTA_DAYS,
    DEFAULT_JITTER_SECONDS,
    DEFAULT_RESTORE_ON_STOP,
    DEFAULT_TRANSITION,
    DEFAULT_USE_SNAPSHOT,
)
from .models import LightEvent, ReplayStatus, ScheduledEvent
from .recorder import light_level_from_state
from .store import PresenceReplayStore

_LOGGER = logging.getLogger(__name__)


def build_plan(
    events: Iterable[LightEvent],
    target_date: date,
    jitter_seconds: int = 0,
) -> tuple[dict[str, int], list[ScheduledEvent]]:
    """Build a baseline + a sorted, jittered timeline for target_date.

    1. Local-midnight boundaries via start_of_local_day, never
       timedelta(days=1) arithmetic on the boundary itself.
    2. Baseline = last recorded level per entity at or before that midnight.
    3. Events strictly inside the day, converted to seconds-since-midnight.
    4. Jitter applied to events only, never the baseline, so every simulated
       day starts from a deterministic state.

    seconds_since_midnight is derived from the event's *local wall-clock*
    hour/minute/second, not from `event.ts - midnight_ts`. Replay almost
    always happens on a different calendar day than the one being replayed,
    and that day is usually a normal 24-hour day. If target_date was a
    23-hour (spring-forward) day, an epoch-time offset would under-count by
    an hour for anything recorded after the gap, and reapplying that offset
    to a normal replay day's midnight would fire an hour early. Reading the
    wall-clock components directly keeps "recorded at 18:00" meaning
    "replayed at 18:00", regardless of what the source day's clock did.
    A 25-hour (fall-back) source day has a genuine one-hour civil-time
    ambiguity -- two real instants both read the same local 01:30 -- which
    this cannot and does not try to disambiguate.
    """
    midnight = dt_util.start_of_local_day(target_date)
    next_midnight = dt_util.start_of_local_day(target_date + timedelta(days=1))
    midnight_ts = midnight.timestamp()
    next_midnight_ts = next_midnight.timestamp()

    baseline: dict[str, int] = {}
    todays: list[LightEvent] = []
    for event in sorted(events, key=lambda e: e.ts):
        if event.ts < midnight_ts:
            baseline[event.entity_id] = event.level
        elif event.ts < next_midnight_ts:
            todays.append(event)

    scheduled: list[ScheduledEvent] = []
    for event in todays:
        local_dt = dt_util.as_local(dt_util.utc_from_timestamp(event.ts))
        offset = (
            local_dt.hour * 3600
            + local_dt.minute * 60
            + local_dt.second
            + local_dt.microsecond / 1e6
        )
        if jitter_seconds:
            offset += random.uniform(-jitter_seconds, jitter_seconds)
        offset = min(max(offset, 0.0), 86400.0 - 1)
        scheduled.append(
            ScheduledEvent(
                seconds_since_midnight=offset, entity_id=event.entity_id, level=event.level
            )
        )
    scheduled.sort(key=lambda e: e.seconds_since_midnight)
    return baseline, scheduled


class ReplayScheduler:
    """Drives baseline application, catch-up, and point-in-time replay."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: PresenceReplayStore) -> None:
        self.hass = hass
        self._entry = entry
        self._store = store
        self.status = ReplayStatus()

        self._plan: list[ScheduledEvent] = []
        self._plan_index = 0
        self._today_midnight: datetime | None = None
        self._prior_levels: dict[str, int] = {}
        self._warned_feedback_loop = False

        self._unsub_next: CALLBACK_TYPE | None = None
        self._unsub_midnight: CALLBACK_TYPE | None = None

    @property
    def is_running(self) -> bool:
        return self.status.is_running

    async def async_start(self) -> None:
        if self.status.is_running:
            return
        self.status.is_running = True
        self._warned_feedback_loop = False
        self._prior_levels = self._capture_current_levels()
        self._schedule_midnight_rollover()
        await self._rebuild_and_apply(dt_util.now())

    async def async_stop(self, restore: bool = True) -> None:
        was_running = self.status.is_running
        self.status.is_running = False
        self._cancel_next()
        self._cancel_midnight()
        self.status.next_action_at = None
        self.status.replaying_date = None
        self._plan = []
        self._plan_index = 0

        if (
            was_running
            and restore
            and self._entry.options.get(CONF_RESTORE_ON_STOP, DEFAULT_RESTORE_ON_STOP)
        ):
            for entity_id, level in self._prior_levels.items():
                await self._async_apply_level(entity_id, level)
        self._prior_levels = {}

    def _capture_current_levels(self) -> dict[str, int]:
        levels: dict[str, int] = {}
        for entity_id in self._entry.options.get(CONF_LIGHTS, []):
            level = light_level_from_state(self.hass.states.get(entity_id))
            if level is not None:
                levels[entity_id] = level
        return levels

    def _source_events(self) -> list[LightEvent]:
        options = self._entry.options
        use_snapshot = options.get(CONF_USE_SNAPSHOT, DEFAULT_USE_SNAPSHOT)
        if use_snapshot and self._store.snapshot is not None:
            return self._store.snapshot.events
        return self._store.events

    def _target_date(self, now: datetime, use_snapshot: bool, delta_days: int) -> date:
        """Which historical date to replay tonight.

        Without a snapshot, this is a rolling `now - delta_days` window that
        keeps sliding forward -- fine until it slides past the day the
        replay itself started running, at which point it starts sourcing
        its own output (see `_check_feedback_loop`).

        With a snapshot in use, the frozen window can't supply new dates
        forever, so once real time runs past it we cycle back through the
        same `days` calendar dates the snapshot actually contains, anchored
        to when it was taken, instead of walking off the end into dates it
        has no events for (which would silently freeze the house instead of
        looping it).
        """
        snapshot = self._store.snapshot
        if use_snapshot and snapshot is not None and snapshot.created is not None and snapshot.days > 0:
            created_date = dt_util.as_local(dt_util.utc_from_timestamp(snapshot.created)).date()
            window_start = created_date - timedelta(days=snapshot.days)
            nights_elapsed = (now.date() - created_date).days
            return window_start + timedelta(days=nights_elapsed % snapshot.days)
        return (now - timedelta(days=delta_days)).date()

    def _check_feedback_loop(
        self, events: list[LightEvent], next_midnight_ts: float, use_snapshot: bool
    ) -> None:
        if use_snapshot or self._warned_feedback_loop:
            return
        if any(event.replay for event in events if event.ts < next_midnight_ts):
            _LOGGER.warning(
                "Presence Replay entry %s is replaying events that were themselves "
                "recorded during a previous replay. Without the snapshot option, a "
                "trip longer than delta_days causes the simulation to replay its own "
                "jittered output and drift will compound. Enable the 'use_snapshot' "
                "option to replay a frozen reference period instead.",
                self._entry.entry_id,
            )
            self._warned_feedback_loop = True

    async def _rebuild_and_apply(self, now: datetime) -> None:
        options = self._entry.options
        delta_days = options.get(CONF_DELTA_DAYS, DEFAULT_DELTA_DAYS)
        use_snapshot = options.get(CONF_USE_SNAPSHOT, DEFAULT_USE_SNAPSHOT)
        jitter_seconds = options.get(CONF_JITTER_SECONDS, DEFAULT_JITTER_SECONDS)
        target_date = self._target_date(now, use_snapshot, delta_days)
        next_midnight_ts = dt_util.start_of_local_day(
            target_date + timedelta(days=1)
        ).timestamp()

        source_events = self._source_events()
        self._check_feedback_loop(source_events, next_midnight_ts, use_snapshot)

        baseline, plan = build_plan(source_events, target_date, jitter_seconds)

        self._today_midnight = dt_util.start_of_local_day(now)
        self.status.replaying_date = target_date

        if not baseline and not plan:
            _LOGGER.warning(
                "No recorded events for %s; leaving lights untouched", target_date.isoformat()
            )
            self._plan = []
            self._plan_index = 0
            self.status.next_action_at = None
            self.status.dead_entity_count = 0
            self._cancel_next()
            return

        referenced = set(baseline) | {scheduled.entity_id for scheduled in plan}
        self.status.dead_entity_count = sum(
            1 for entity_id in referenced if self.hass.states.get(entity_id) is None
        )

        elapsed = (now - self._today_midnight).total_seconds()
        split_index = len(plan)
        for index, scheduled in enumerate(plan):
            if scheduled.seconds_since_midnight > elapsed:
                split_index = index
                break

        levels = dict(baseline)
        for scheduled in plan[:split_index]:
            levels[scheduled.entity_id] = scheduled.level

        for entity_id, level in levels.items():
            await self._async_apply_level(entity_id, level)

        self._plan = plan
        self._plan_index = split_index
        self._cancel_next()
        self._schedule_next()

    @callback
    def _schedule_next(self) -> None:
        if self._plan_index >= len(self._plan) or self._today_midnight is None:
            self.status.next_action_at = None
            return
        scheduled = self._plan[self._plan_index]
        target = self._today_midnight + timedelta(seconds=scheduled.seconds_since_midnight)
        self.status.next_action_at = target
        self._unsub_next = async_track_point_in_time(self.hass, self._async_fire_next, target)

    async def _async_fire_next(self, _now: datetime) -> None:
        self._unsub_next = None
        if self._plan_index >= len(self._plan):
            return
        current_offset = self._plan[self._plan_index].seconds_since_midnight
        while (
            self._plan_index < len(self._plan)
            and self._plan[self._plan_index].seconds_since_midnight == current_offset
        ):
            scheduled = self._plan[self._plan_index]
            self._plan_index += 1
            await self._async_apply_level(scheduled.entity_id, scheduled.level)
        self._schedule_next()

    @callback
    def _schedule_midnight_rollover(self) -> None:
        now = dt_util.now()
        next_midnight = dt_util.start_of_local_day(now.date() + timedelta(days=1))
        self._unsub_midnight = async_track_point_in_time(
            self.hass, self._async_handle_rollover, next_midnight
        )

    async def _async_handle_rollover(self, now: datetime) -> None:
        self._cancel_next()
        self._schedule_midnight_rollover()
        await self._rebuild_and_apply(dt_util.now())

    async def _async_apply_level(self, entity_id: str, level: int) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return
        if state.state == STATE_UNAVAILABLE:
            _LOGGER.debug("Skipping unavailable light %s during replay", entity_id)
            return

        transition = self._entry.options.get(CONF_TRANSITION, DEFAULT_TRANSITION)
        if level <= 0:
            data: dict[str, object] = {ATTR_ENTITY_ID: entity_id}
            if transition:
                data[ATTR_TRANSITION] = transition
            await self.hass.services.async_call(
                LIGHT_DOMAIN, SERVICE_TURN_OFF, data, blocking=False
            )
        else:
            data = {ATTR_ENTITY_ID: entity_id, ATTR_BRIGHTNESS: level}
            if transition:
                data[ATTR_TRANSITION] = transition
            await self.hass.services.async_call(
                LIGHT_DOMAIN, SERVICE_TURN_ON, data, blocking=False
            )

    @callback
    def _cancel_next(self) -> None:
        if self._unsub_next is not None:
            self._unsub_next()
            self._unsub_next = None

    @callback
    def _cancel_midnight(self) -> None:
        if self._unsub_midnight is not None:
            self._unsub_midnight()
            self._unsub_midnight = None
