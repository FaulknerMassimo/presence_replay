"""presence_replay/history websocket command, used by the history card."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.presence_replay.const import CONF_LIGHTS, DEFAULT_OPTIONS, DOMAIN
from custom_components.presence_replay.models import LightEvent


async def _make_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        options={**DEFAULT_OPTIONS, CONF_LIGHTS: ["light.kitchen"]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_history_returns_events_and_snapshot(hass, hass_owner_user, hass_ws_client) -> None:
    entry = await _make_entry(hass)
    now = dt_util.utcnow().timestamp()
    entry.runtime_data.store.events.append(
        LightEvent(ts=now - 3600, entity_id="light.kitchen", level=123)
    )
    entry.runtime_data.store.events.append(
        LightEvent(ts=now - 60, entity_id="light.kitchen", level=200, replay=True)
    )
    entry.runtime_data.store.make_snapshot(days=7, now_ts=now)

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "presence_replay/history", "config_entry_id": entry.entry_id}
    )
    response = await client.receive_json()

    assert response["success"]
    assert response["result"]["events"] == [
        [now - 3600, "light.kitchen", 123, False],
        [now - 60, "light.kitchen", 200, True],
    ]
    snapshot = response["result"]["snapshot"]
    assert snapshot["days"] == 7
    assert snapshot["created"] == now
    assert snapshot["events"] == response["result"]["events"]


async def test_history_no_snapshot_is_none(hass, hass_owner_user, hass_ws_client) -> None:
    entry = await _make_entry(hass)

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "presence_replay/history", "config_entry_id": entry.entry_id}
    )
    response = await client.receive_json()

    assert response["success"]
    assert response["result"]["events"] == []
    assert response["result"]["snapshot"] is None


async def test_history_unknown_entry_is_not_found(hass, hass_owner_user, hass_ws_client) -> None:
    await _make_entry(hass)
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "presence_replay/history", "config_entry_id": "does-not-exist"}
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "not_found"


async def test_history_unloaded_entry_is_not_found(hass, hass_owner_user, hass_ws_client) -> None:
    # Registers the websocket command without loading any entry.
    assert await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Not loaded",
        options={**DEFAULT_OPTIONS, CONF_LIGHTS: ["light.kitchen"]},
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "presence_replay/history", "config_entry_id": entry.entry_id}
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "not_found"


async def test_history_requires_admin(hass, hass_read_only_access_token, hass_ws_client) -> None:
    entry = await _make_entry(hass)
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    await client.send_json(
        {"id": 1, "type": "presence_replay/history", "config_entry_id": entry.entry_id}
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "unauthorized"
