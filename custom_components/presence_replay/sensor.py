"""Diagnostic sensors for Presence Replay.

Confirms capture is working (`events_recorded`, `history_span`) independent
of any replay code, and exposes scheduler state (`next_action`,
`replaying_date`) once replay is running.
"""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PresenceReplayConfigEntry
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PresenceReplayConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            EventsRecordedSensor(entry),
            HistorySpanSensor(entry),
            NextActionSensor(entry),
            ReplayingDateSensor(entry),
        ]
    )


class _PresenceReplaySensorBase(SensorEntity):
    """Shared device info + naming for the diagnostic sensor set."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: PresenceReplayConfigEntry, key: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )


class EventsRecordedSensor(_PresenceReplaySensorBase):
    """Count of events currently held in the log."""

    _attr_icon = "mdi:database"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: PresenceReplayConfigEntry) -> None:
        super().__init__(entry, "events_recorded")

    @property
    def native_value(self) -> int:
        return len(self._entry.runtime_data.store.events)


class HistorySpanSensor(_PresenceReplaySensorBase):
    """Days between the oldest and newest recorded event."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:calendar-range"

    def __init__(self, entry: PresenceReplayConfigEntry) -> None:
        super().__init__(entry, "history_span")

    @property
    def native_value(self) -> float:
        events = self._entry.runtime_data.store.events
        if len(events) < 2:
            return 0.0
        oldest = min(event.ts for event in events)
        newest = max(event.ts for event in events)
        return round((newest - oldest) / 86400, 2)


class NextActionSensor(_PresenceReplaySensorBase):
    """Next scheduled point-in-time replay action, if any."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, entry: PresenceReplayConfigEntry) -> None:
        super().__init__(entry, "next_action")

    @property
    def native_value(self) -> datetime | None:
        return self._entry.runtime_data.scheduler.status.next_action_at


class ReplayingDateSensor(_PresenceReplaySensorBase):
    """Which historical date is currently being played back."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: PresenceReplayConfigEntry) -> None:
        super().__init__(entry, "replaying_date")

    @property
    def native_value(self) -> date | None:
        return self._entry.runtime_data.scheduler.status.replaying_date

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {
            "dead_entities": self._entry.runtime_data.scheduler.status.dead_entity_count,
        }
