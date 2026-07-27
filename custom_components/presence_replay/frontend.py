"""Serves the bundled Lovelace history card and auto-registers it.

`add_extra_js_url` loads the module for every dashboard without the user
having to add a Lovelace resource by hand.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

CARD_FILENAME = "presence-replay-history-card.js"
STATIC_URL_PATH = "/presence_replay_static"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve custom_components/presence_replay/www/ and load the card. Call once from async_setup."""
    root = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL_PATH, str(root), True)]
    )
    add_extra_js_url(hass, f"{STATIC_URL_PATH}/{CARD_FILENAME}")
