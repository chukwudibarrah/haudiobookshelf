"""Websocket API used by the Audiobookshelf Lovelace card.

Sensor attributes are the wrong place for shelves of books: they are size
limited, they end up in the recorder, and they churn the state machine. The
card talks to these commands instead and subscribes for live updates.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .api import AudiobookshelfError
from .const import DATA_WEBSOCKET_REGISTERED, DOMAIN

_LOGGER = logging.getLogger(__name__)


def _coordinators(hass: HomeAssistant) -> dict[str, Any]:
    """Return every loaded coordinator, keyed by config entry ID."""
    return hass.data.get(DOMAIN) or {}


def _resolve(hass: HomeAssistant, entry_id: str | None) -> Any | None:
    """Return the requested coordinator, or the only one if none was named."""
    coordinators = _coordinators(hass)
    if entry_id:
        return coordinators.get(entry_id)
    if len(coordinators) == 1:
        return next(iter(coordinators.values()))
    return None


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the websocket commands once per Home Assistant run."""
    if hass.data.get(f"{DOMAIN}_{DATA_WEBSOCKET_REGISTERED}"):
        return
    hass.data[f"{DOMAIN}_{DATA_WEBSOCKET_REGISTERED}"] = True

    websocket_api.async_register_command(hass, ws_entries)
    websocket_api.async_register_command(hass, ws_data)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_set_finished)


@callback
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/entries"})
def ws_entries(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List the configured Audiobookshelf servers."""
    entries = []
    for entry_id, coordinator in _coordinators(hass).items():
        entry = coordinator.entry
        entries.append(
            {
                "entry_id": entry_id,
                "title": entry.title,
                "url": coordinator.public_url,
                "username": (coordinator.data or {}).get("user", {}).get("username"),
            }
        )
    connection.send_result(msg["id"], {"entries": entries})


@callback
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/data",
        vol.Optional("entry_id"): str,
    }
)
def ws_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the current snapshot for one server."""
    coordinator = _resolve(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "No matching Audiobookshelf config entry"
        )
        return
    connection.send_result(msg["id"], coordinator.data or {})


@callback
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/subscribe",
        vol.Optional("entry_id"): str,
    }
)
def ws_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Push a snapshot now, and again on every coordinator refresh."""
    coordinator = _resolve(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "No matching Audiobookshelf config entry"
        )
        return

    @callback
    def _forward() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], coordinator.data or {}))

    connection.subscriptions[msg["id"]] = coordinator.async_add_listener(_forward)
    connection.send_result(msg["id"])
    if coordinator.data:
        _forward()


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_finished",
        vol.Required("item_id"): str,
        vol.Optional("episode_id"): vol.Any(str, None),
        vol.Optional("finished", default=True): bool,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_set_finished(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Mark an item finished or unfinished on behalf of the card."""
    coordinator = _resolve(hass, msg.get("entry_id"))
    if coordinator is None:
        connection.send_error(
            msg["id"], "not_found", "No matching Audiobookshelf config entry"
        )
        return

    finished = msg["finished"]
    payload: dict[str, Any] = {"isFinished": finished}
    if not finished:
        # Clearing the flag alone leaves the book sitting at 100%, where
        # Audiobookshelf will immediately re-finish it on the next sync.
        payload["progress"] = 0
        payload["currentTime"] = 0

    try:
        await coordinator.client.async_update_progress(
            msg["item_id"], payload, episode_id=msg.get("episode_id")
        )
    except AudiobookshelfError as err:
        connection.send_error(msg["id"], "update_failed", str(err))
        return

    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"success": True})
