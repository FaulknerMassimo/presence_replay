"""Websocket API for the bundled history card.

Read-only, admin-gated access to a config entry's event log -- the same
data `services.export_log` returns, but as a websocket command so the
frontend card can fetch it directly instead of invoking an admin service.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .models import LightEvent


def _events_to_payload(events: list[LightEvent]) -> list[list[float | str | int | bool]]:
    return [[event.ts, event.entity_id, event.level, event.replay] for event in events]


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/history",
        vol.Required("config_entry_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def _ws_get_history(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    entry = hass.config_entries.async_get_entry(msg["config_entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown Presence Replay config entry"
        )
        return
    if entry.state is not ConfigEntryState.LOADED:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Presence Replay entry is not loaded"
        )
        return

    store = entry.runtime_data.store
    snapshot = store.snapshot
    connection.send_result(
        msg["id"],
        {
            "events": _events_to_payload(store.events),
            "snapshot": (
                {
                    "created": snapshot.created,
                    "days": snapshot.days,
                    "events": _events_to_payload(snapshot.events),
                }
                if snapshot is not None
                else None
            ),
        },
    )


def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register the history websocket command. Call once from async_setup."""
    websocket_api.async_register_command(hass, _ws_get_history)
