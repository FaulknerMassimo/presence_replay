"""presence_replay.{snapshot,clear_log,export_log} services."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.presence_replay.const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONFIRM,
    CONF_LIGHTS,
    DEFAULT_OPTIONS,
    DOMAIN,
    SERVICE_CLEAR_LOG,
    SERVICE_EXPORT_LOG,
    SERVICE_SNAPSHOT,
)
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
    recent_ts = dt_util.utcnow().timestamp() - 3600
    entry.runtime_data.store.events.append(
        LightEvent(ts=recent_ts, entity_id="light.kitchen", level=123)
    )
    return entry


async def test_snapshot_service(hass: HomeAssistant, hass_owner_user) -> None:
    entry = await _make_entry(hass)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SNAPSHOT,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
        blocking=True,
    )
    assert entry.runtime_data.store.snapshot is not None
    assert len(entry.runtime_data.store.snapshot.events) == 1


async def test_clear_log_requires_confirm_text(hass: HomeAssistant, hass_owner_user) -> None:
    entry = await _make_entry(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CLEAR_LOG,
            {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_CONFIRM: "nope"},
            blocking=True,
        )
    assert len(entry.runtime_data.store.events) == 1

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEAR_LOG,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_CONFIRM: "CLEAR"},
        blocking=True,
    )
    assert entry.runtime_data.store.events == []


async def test_export_log_returns_response_data(hass: HomeAssistant, hass_owner_user) -> None:
    entry = await _make_entry(hass)
    expected_ts = entry.runtime_data.store.events[0].ts
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_EXPORT_LOG,
        {ATTR_CONFIG_ENTRY_ID: entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert response["events"] == [[expected_ts, "light.kitchen", 123]]
