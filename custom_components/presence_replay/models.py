"""Data models for the Presence Replay integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .recorder import LightCapture
    from .scheduler import ReplayScheduler
    from .store import PresenceReplayStore


@dataclass(slots=True, frozen=True)
class LightEvent:
    """A single recorded (or replayed-baseline) light level change.

    ``replay`` is True when the event was written to the log while the
    switch was on, i.e. it is simulation output rather than an organic
    observation. It exists to detect the feedback-loop edge case, not to
    change how the event is otherwise treated.
    """

    ts: float
    entity_id: str
    level: int
    replay: bool = False


@dataclass(slots=True)
class SnapshotData:
    """A frozen reference period, replayed instead of the rolling log."""

    created: float | None
    days: int
    events: list[LightEvent]


@dataclass(slots=True)
class ScheduledEvent:
    """A LightEvent projected onto a single day's replay timeline."""

    seconds_since_midnight: float
    entity_id: str
    level: int


@dataclass
class PresenceReplayRuntime:
    """Runtime state attached to the config entry via ``runtime_data``."""

    store: PresenceReplayStore
    capture: LightCapture
    scheduler: ReplayScheduler


@dataclass(slots=True)
class ReplayStatus:
    """Snapshot of scheduler state consumed by diagnostic sensors."""

    is_running: bool = False
    next_action_at: datetime | None = None
    replaying_date: date | None = None
    dead_entity_count: int = 0
