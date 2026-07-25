"""Persistent event log for Presence Replay.

Independent of the recorder by design -- see PLAN.md. Events are kept in
memory and written to `.storage/presence_replay.<entry_id>` via
`Store.async_delay_save`, which batches bursts of changes into one disk
write every SAVE_DELAY seconds.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import SAVE_DELAY, STORAGE_VERSION, STORAGE_VERSION_MINOR
from .models import LightEvent, SnapshotData

_LOGGER = logging.getLogger(__name__)


def _event_to_row(event: LightEvent) -> list[Any]:
    row: list[Any] = [event.ts, event.entity_id, event.level]
    if event.replay:
        row.append(True)
    return row


def _row_to_event(row: list[Any]) -> LightEvent:
    ts, entity_id, level = row[0], row[1], row[2]
    replay = bool(row[3]) if len(row) > 3 else False
    return LightEvent(ts=ts, entity_id=entity_id, level=level, replay=replay)


class PresenceReplayStore:
    """Owns the in-memory event log and its on-disk persistence."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict[str, Any]](
            hass,
            STORAGE_VERSION,
            f"presence_replay.{entry_id}",
            minor_version=STORAGE_VERSION_MINOR,
        )
        self.events: list[LightEvent] = []
        self.snapshot: SnapshotData | None = None

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if raw is None:
            return
        self.events = [_row_to_event(row) for row in raw.get("events", [])]
        snap = raw.get("snapshot")
        if snap and snap.get("events") is not None and snap.get("created") is not None:
            self.snapshot = SnapshotData(
                created=snap["created"],
                days=snap["days"],
                events=[_row_to_event(row) for row in snap["events"]],
            )

    def _as_dict(self) -> dict[str, Any]:
        return {
            "events": [_event_to_row(event) for event in self.events],
            "snapshot": (
                {
                    "created": self.snapshot.created,
                    "days": self.snapshot.days,
                    "events": [_event_to_row(event) for event in self.snapshot.events],
                }
                if self.snapshot is not None
                else {"created": None, "days": 0, "events": []}
            ),
        }

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._as_dict, SAVE_DELAY)

    async def async_save_now(self) -> None:
        await self._store.async_save(self._as_dict())

    def append(self, event: LightEvent) -> None:
        self.events.append(event)
        self._schedule_save()

    def last_level(self, entity_id: str) -> int | None:
        """Most recently recorded level for entity_id, or None if never seen."""
        for event in reversed(self.events):
            if event.entity_id == entity_id:
                return event.level
        return None

    def prune(self, retention_days: int, now_ts: float) -> None:
        cutoff = now_ts - retention_days * 86400
        before = len(self.events)
        self.events = [event for event in self.events if event.ts >= cutoff]
        if len(self.events) != before:
            _LOGGER.debug(
                "Pruned %d events older than %d days", before - len(self.events), retention_days
            )
            self._schedule_save()

    def clear(self) -> None:
        self.events = []
        self._schedule_save()

    def make_snapshot(self, days: int, now_ts: float) -> None:
        cutoff = now_ts - days * 86400
        events = [event for event in self.events if event.ts >= cutoff]
        self.snapshot = SnapshotData(created=now_ts, days=days, events=events)
        _LOGGER.info("Took a %d-day snapshot with %d events", days, len(events))
        self._schedule_save()
