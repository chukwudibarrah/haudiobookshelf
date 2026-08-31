"""Diagnostics support for Audiobookshelf."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, CONF_URL, DOMAIN
from .coordinator import AudiobookshelfCoordinator

TO_REDACT = {CONF_TOKEN, CONF_URL, "url", "public_url", "id", "username"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: AudiobookshelfCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "server": async_redact_data(data.get("server") or {}, TO_REDACT),
            "user": async_redact_data(data.get("user") or {}, TO_REDACT),
            "stats": data.get("stats"),
            "libraries": data.get("libraries"),
            "counts": {
                key: len(data.get(key) or [])
                for key in ("in_progress", "finished", "recently_added")
            },
            "is_listening": data.get("is_listening"),
        },
    }
