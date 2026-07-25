"""store.py: pruning trims the rolling log but never touches the snapshot slot."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.presence_replay.models import LightEvent, SnapshotData
from custom_components.presence_replay.store import PresenceReplayStore


async def test_prune_drops_old_events_but_not_snapshot(hass: HomeAssistant) -> None:
    store = PresenceReplayStore(hass, "test_entry")
    now = 1_700_000_000.0
    store.events = [
        LightEvent(ts=now - 40 * 86400, entity_id="light.a", level=100),  # older than retention
        LightEvent(ts=now - 5 * 86400, entity_id="light.a", level=150),  # kept
    ]
    store.snapshot = SnapshotData(
        created=now,
        days=7,
        events=[LightEvent(ts=now - 40 * 86400, entity_id="light.a", level=10)],
    )

    store.prune(retention_days=21, now_ts=now)

    assert len(store.events) == 1
    assert store.events[0].level == 150
    assert len(store.snapshot.events) == 1


async def test_make_snapshot_only_includes_recent_events(hass: HomeAssistant) -> None:
    store = PresenceReplayStore(hass, "test_entry")
    now = 1_700_000_000.0
    store.events = [
        LightEvent(ts=now - 10 * 86400, entity_id="light.a", level=100),
        LightEvent(ts=now - 2 * 86400, entity_id="light.a", level=150),
    ]

    store.make_snapshot(days=7, now_ts=now)

    assert store.snapshot is not None
    assert store.snapshot.days == 7
    assert [event.level for event in store.snapshot.events] == [150]


async def test_last_level_returns_most_recent(hass: HomeAssistant) -> None:
    store = PresenceReplayStore(hass, "test_entry")
    store.events = [
        LightEvent(ts=1, entity_id="light.a", level=10),
        LightEvent(ts=2, entity_id="light.a", level=20),
        LightEvent(ts=3, entity_id="light.b", level=5),
    ]
    assert store.last_level("light.a") == 20
    assert store.last_level("light.b") == 5
    assert store.last_level("light.c") is None
