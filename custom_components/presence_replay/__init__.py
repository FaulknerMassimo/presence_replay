"""The Presence Replay integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONFIRM,
    CLEAR_LOG_CONFIRM_TEXT,
    CONF_DELTA_DAYS,
    CONF_RETENTION_DAYS,
    DEFAULT_DELTA_DAYS,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    PLATFORMS,
    PRUNE_HOUR,
    PRUNE_MINUTE,
    PRUNE_SECOND,
    SERVICE_CLEAR_LOG,
    SERVICE_EXPORT_LOG,
    SERVICE_SNAPSHOT,
)
from .frontend import async_register_frontend
from .models import PresenceReplayRuntime
from .recorder import LightCapture
from .scheduler import ReplayScheduler
from .store import PresenceReplayStore
from .websocket_api import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)

type PresenceReplayConfigEntry = ConfigEntry[PresenceReplayRuntime]

_SERVICES_REGISTERED_KEY = f"{DOMAIN}_services_registered"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Global, once-per-run setup: history websocket command + bundled card."""
    async_register_websocket_api(hass)
    await async_register_frontend(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PresenceReplayConfigEntry) -> bool:
    """Set up Presence Replay from a config entry."""
    store = PresenceReplayStore(hass, entry.entry_id)
    await store.async_load()

    capture = LightCapture(hass, entry, store)
    capture.async_start()

    scheduler = ReplayScheduler(hass, entry, store)

    entry.runtime_data = PresenceReplayRuntime(
        store=store, capture=capture, scheduler=scheduler
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(_async_register_nightly_prune(hass, entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: PresenceReplayConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = entry.runtime_data
        runtime.capture.async_stop()
        await runtime.scheduler.async_stop(restore=False)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: PresenceReplayConfigEntry) -> bool:
    """Migrate an old config entry. Nothing to migrate yet, but the hook
    is cheap to have from day one and expensive to retrofit later."""
    return True


async def _async_update_listener(hass: HomeAssistant, entry: PresenceReplayConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_nightly_prune(hass: HomeAssistant, entry: PresenceReplayConfigEntry):
    """Prune events older than retention_days once per night."""

    async def _prune(_now: Any) -> None:
        retention_days = entry.options.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS)
        entry.runtime_data.store.prune(retention_days, dt_util.utcnow().timestamp())

    return async_track_time_change(
        hass, _prune, hour=PRUNE_HOUR, minute=PRUNE_MINUTE, second=PRUNE_SECOND
    )


async def async_take_snapshot(hass: HomeAssistant, entry: PresenceReplayConfigEntry) -> None:
    """Freeze the last delta_days of recorded events into the snapshot slot."""
    days = entry.options.get(CONF_DELTA_DAYS, DEFAULT_DELTA_DAYS)
    entry.runtime_data.store.make_snapshot(days, dt_util.utcnow().timestamp())


def _get_entry_from_call(hass: HomeAssistant, call: ServiceCall) -> PresenceReplayConfigEntry:
    entry_id = call.data[ATTR_CONFIG_ENTRY_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(f"Unknown Presence Replay config entry: {entry_id}")
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"Presence Replay entry {entry_id} is not loaded")
    return entry


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.data.get(_SERVICES_REGISTERED_KEY):
        return
    hass.data[_SERVICES_REGISTERED_KEY] = True

    async def _handle_snapshot(call: ServiceCall) -> None:
        entry = _get_entry_from_call(hass, call)
        await async_take_snapshot(hass, entry)

    async def _handle_clear_log(call: ServiceCall) -> None:
        entry = _get_entry_from_call(hass, call)
        if call.data.get(ATTR_CONFIRM) != CLEAR_LOG_CONFIRM_TEXT:
            raise ServiceValidationError(
                f"Type {CLEAR_LOG_CONFIRM_TEXT!r} in the confirm field to clear the log"
            )
        entry.runtime_data.store.clear()

    async def _handle_export_log(call: ServiceCall) -> ServiceResponse:
        entry = _get_entry_from_call(hass, call)
        return {
            "events": [
                [event.ts, event.entity_id, event.level]
                for event in entry.runtime_data.store.events
            ]
        }

    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_SNAPSHOT,
        _handle_snapshot,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}),
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_CLEAR_LOG,
        _handle_clear_log,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
                vol.Required(ATTR_CONFIRM): cv.string,
            }
        ),
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_EXPORT_LOG,
        _handle_export_log,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
