"""Button platform for Presence Replay -- manual snapshot trigger."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PresenceReplayConfigEntry, async_take_snapshot
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PresenceReplayConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([TakeSnapshotButton(entry)])


class TakeSnapshotButton(ButtonEntity):
    """Freezes the configured `delta_days` into the snapshot slot on press.

    Equivalent to calling the `presence_replay.snapshot` service for this
    entry.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "take_snapshot"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:camera"

    def __init__(self, entry: PresenceReplayConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_take_snapshot"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )

    async def async_press(self) -> None:
        await async_take_snapshot(self.hass, self._entry)
