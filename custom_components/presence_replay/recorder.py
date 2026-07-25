"""Event-driven light-level capture with per-entity debounce.

Named recorder.py per PLAN.md to avoid confusion with the HA core
`recorder` component -- this module has nothing to do with it and exists
specifically because the core recorder no longer keeps light attributes.

Each state change (re)starts a per-entity `async_call_later` timer. Only
when the timer fires -- i.e. the burst has gone quiet for
`debounce_seconds` -- is an event recorded, using the timestamp of the
*first* change in the burst and the *last* observed level. This collapses
a multi-step fade into a single event instead of polling.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_LIGHTS,
    CONF_MIN_DELTA,
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_MIN_DELTA,
    LEVEL_OFF,
    LEVEL_ON_NO_BRIGHTNESS,
)
from .models import LightEvent
from .store import PresenceReplayStore

_LOGGER = logging.getLogger(__name__)


def light_level_from_state(state: State | None) -> int | None:
    """Translate a light state to the 0-255 encoding, or None if unusable."""
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    if state.state == STATE_OFF:
        return LEVEL_OFF
    if state.state == STATE_ON:
        return state.attributes.get(ATTR_BRIGHTNESS) or LEVEL_ON_NO_BRIGHTNESS
    return None


class LightCapture:
    """Owns the state-change listener and per-entity debounce timers."""

    def __init__(self, hass: HomeAssistant, entry: Any, store: PresenceReplayStore) -> None:
        self.hass = hass
        self._entry = entry
        self._store = store
        self.is_replaying = False
        self._unsub_state: CALLBACK_TYPE | None = None
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._burst_start: dict[str, float] = {}

    @callback
    def async_start(self) -> None:
        entities = self._entry.options.get(CONF_LIGHTS, [])
        if not entities:
            return
        self._unsub_state = async_track_state_change_event(
            self.hass, entities, self._handle_state_change
        )

    @callback
    def async_stop(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        self._burst_start.clear()

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        level = light_level_from_state(new_state)
        if level is None or new_state is None:
            return

        entity_id = event.data["entity_id"]
        self._burst_start.setdefault(entity_id, dt_util.utcnow().timestamp())

        cancel = self._timers.pop(entity_id, None)
        if cancel is not None:
            cancel()

        debounce_seconds = self._entry.options.get(
            CONF_DEBOUNCE_SECONDS, DEFAULT_DEBOUNCE_SECONDS
        )
        self._timers[entity_id] = async_call_later(
            self.hass, debounce_seconds, partial(self._async_fire, entity_id, level)
        )

    @callback
    def _async_fire(self, entity_id: str, level: int, _now: Any) -> None:
        self._timers.pop(entity_id, None)
        start_ts = self._burst_start.pop(entity_id, dt_util.utcnow().timestamp())

        min_delta = self._entry.options.get(CONF_MIN_DELTA, DEFAULT_MIN_DELTA)
        last = self._store.last_level(entity_id)
        if last is not None and abs(level - last) < min_delta:
            return

        self._store.append(
            LightEvent(ts=start_ts, entity_id=entity_id, level=level, replay=self.is_replaying)
        )
