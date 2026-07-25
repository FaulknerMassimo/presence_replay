"""Switch platform for Presence Replay -- the entity automations target."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import PresenceReplayConfigEntry
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PresenceReplayConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([PresenceReplaySwitch(entry)])


class PresenceReplaySwitch(SwitchEntity, RestoreEntity):
    """Starts and stops the replay scheduler.

    `turn_on` starts the scheduler; `turn_off` stops it and, when
    `restore_on_stop` is set, reapplies the light states captured at start.
    On restart, a restored "on" state resumes the simulation automatically.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "replay"
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, entry: PresenceReplayConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_replay"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == STATE_ON:
            await self._async_start()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_start()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_stop()
        self.async_write_ha_state()

    async def _async_start(self) -> None:
        runtime = self._entry.runtime_data
        await runtime.scheduler.async_start()
        runtime.capture.is_replaying = True
        self._attr_is_on = True

    async def _async_stop(self) -> None:
        runtime = self._entry.runtime_data
        await runtime.scheduler.async_stop()
        runtime.capture.is_replaying = False
        self._attr_is_on = False
