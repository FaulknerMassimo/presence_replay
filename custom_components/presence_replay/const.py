"""Constants for the Presence Replay integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "presence_replay"

PLATFORMS: Final = [Platform.SWITCH, Platform.SENSOR, Platform.BUTTON]

# Config / options keys
CONF_NAME: Final = "name"
CONF_LIGHTS: Final = "lights"
CONF_DELTA_DAYS: Final = "delta_days"
CONF_JITTER_SECONDS: Final = "jitter_seconds"
CONF_TRANSITION: Final = "transition"
CONF_RETENTION_DAYS: Final = "retention_days"
CONF_DEBOUNCE_SECONDS: Final = "debounce_seconds"
CONF_MIN_DELTA: Final = "min_delta"
CONF_USE_SNAPSHOT: Final = "use_snapshot"
CONF_RESTORE_ON_STOP: Final = "restore_on_stop"

# Defaults
DEFAULT_DELTA_DAYS: Final = 7
DEFAULT_JITTER_SECONDS: Final = 300
DEFAULT_TRANSITION: Final = 2
DEFAULT_RETENTION_DAYS: Final = 21
DEFAULT_DEBOUNCE_SECONDS: Final = 5
DEFAULT_MIN_DELTA: Final = 3
DEFAULT_USE_SNAPSHOT: Final = False
DEFAULT_RESTORE_ON_STOP: Final = True

DEFAULT_OPTIONS: Final = {
    CONF_DELTA_DAYS: DEFAULT_DELTA_DAYS,
    CONF_JITTER_SECONDS: DEFAULT_JITTER_SECONDS,
    CONF_TRANSITION: DEFAULT_TRANSITION,
    CONF_RETENTION_DAYS: DEFAULT_RETENTION_DAYS,
    CONF_DEBOUNCE_SECONDS: DEFAULT_DEBOUNCE_SECONDS,
    CONF_MIN_DELTA: DEFAULT_MIN_DELTA,
    CONF_USE_SNAPSHOT: DEFAULT_USE_SNAPSHOT,
    CONF_RESTORE_ON_STOP: DEFAULT_RESTORE_ON_STOP,
}

# Storage
STORAGE_VERSION: Final = 1
STORAGE_VERSION_MINOR: Final = 1
STORAGE_KEY_TEMPLATE: Final = f"{DOMAIN}.{{entry_id}}"
SAVE_DELAY: Final = 300

# Light level encoding: 0-255, 0 = off, non-dimmable "on" = 255
LEVEL_OFF: Final = 0
LEVEL_ON_NO_BRIGHTNESS: Final = 255

# Nightly prune time (local time)
PRUNE_HOUR: Final = 3
PRUNE_MINUTE: Final = 0
PRUNE_SECOND: Final = 0

# Services
SERVICE_SNAPSHOT: Final = "snapshot"
SERVICE_CLEAR_LOG: Final = "clear_log"
SERVICE_EXPORT_LOG: Final = "export_log"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_CONFIRM: Final = "confirm"
CLEAR_LOG_CONFIRM_TEXT: Final = "CLEAR"

SIGNAL_RUNTIME_UPDATE: Final = f"{DOMAIN}_runtime_update"
