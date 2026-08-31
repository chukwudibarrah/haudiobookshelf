"""The Audiobookshelf integration."""

from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AudiobookshelfClient, AudiobookshelfError
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CURRENT_TIME,
    ATTR_EPISODE_ID,
    ATTR_ITEM_ID,
    ATTR_PERCENT,
    CARD_FILENAME,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_SSL,
    DATA_FRONTEND_REGISTERED,
    DATA_SERVICES_REGISTERED,
    DATA_VIEWS_REGISTERED,
    DOMAIN,
    SERVICE_MARK_FINISHED,
    SERVICE_MARK_UNFINISHED,
    SERVICE_REFRESH,
    SERVICE_SET_PROGRESS,
    URL_BASE,
)
from .coordinator import AudiobookshelfCoordinator
from .http import AudiobookshelfCoverView
from .websocket import async_register as async_register_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.IMAGE,
    Platform.SENSOR,
]

BASE_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ITEM_ID): cv.string,
        vol.Optional(ATTR_EPISODE_ID): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

SET_PROGRESS_SCHEMA = BASE_SERVICE_SCHEMA.extend(
    {
        vol.Exclusive(ATTR_CURRENT_TIME, "position"): vol.Coerce(float),
        vol.Exclusive(ATTR_PERCENT, "position"): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
    }
)

REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Audiobookshelf from a config entry."""
    session = async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True))
    client = AudiobookshelfClient(session, entry.data[CONF_URL], entry.data[CONF_TOKEN])

    coordinator = AudiobookshelfCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await _async_register_frontend(hass)
    _async_register_views(hass)
    async_register_websocket(hass)
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            for service in (
                SERVICE_MARK_FINISHED,
                SERVICE_MARK_UNFINISHED,
                SERVICE_SET_PROGRESS,
                SERVICE_REFRESH,
            ):
                hass.services.async_remove(DOMAIN, service)
            hass.data.pop(f"{DOMAIN}_{DATA_SERVICES_REGISTERED}", None)
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


# ----------------------------------------------------------------------
# Frontend
# ----------------------------------------------------------------------


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card and register it with the frontend.

    Shipping the card inside the integration means HACS installs both in one
    step and users never have to add a Lovelace resource by hand.
    """
    if hass.data.get(f"{DOMAIN}_{DATA_FRONTEND_REGISTERED}"):
        return
    hass.data[f"{DOMAIN}_{DATA_FRONTEND_REGISTERED}"] = True

    root = os.path.join(os.path.dirname(__file__), "frontend")
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, root, cache_headers=False)]
        )
    except ImportError:  # pragma: no cover - cores older than 2024.7
        hass.http.register_static_path(URL_BASE, root, cache_headers=False)

    version = await hass.async_add_executor_job(_card_version)
    add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}?v={version}")


def _card_version() -> str:
    """Return a cache-busting token for the card, based on its mtime."""
    path = os.path.join(os.path.dirname(__file__), "frontend", CARD_FILENAME)
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"


@callback
def _async_register_views(hass: HomeAssistant) -> None:
    """Register the cover proxy view once."""
    if hass.data.get(f"{DOMAIN}_{DATA_VIEWS_REGISTERED}"):
        return
    hass.data[f"{DOMAIN}_{DATA_VIEWS_REGISTERED}"] = True
    hass.http.register_view(AudiobookshelfCoverView())


# ----------------------------------------------------------------------
# Services
# ----------------------------------------------------------------------


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's services once."""
    if hass.data.get(f"{DOMAIN}_{DATA_SERVICES_REGISTERED}"):
        return
    hass.data[f"{DOMAIN}_{DATA_SERVICES_REGISTERED}"] = True

    def _coordinator_for(call: ServiceCall) -> AudiobookshelfCoordinator:
        """Pick the coordinator a service call is aimed at."""
        coordinators: dict[str, AudiobookshelfCoordinator] = hass.data.get(DOMAIN, {})
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        if entry_id:
            coordinator = coordinators.get(entry_id)
            if coordinator is None:
                raise ServiceValidationError(
                    f"No loaded Audiobookshelf config entry with ID {entry_id}"
                )
            return coordinator
        if len(coordinators) != 1:
            raise ServiceValidationError(
                "Several Audiobookshelf servers are configured; "
                f"pass {ATTR_CONFIG_ENTRY_ID} to choose one"
            )
        return next(iter(coordinators.values()))

    async def _async_patch(call: ServiceCall, payload: dict[str, Any]) -> None:
        """Send a progress patch and refresh."""
        coordinator = _coordinator_for(call)
        try:
            await coordinator.client.async_update_progress(
                call.data[ATTR_ITEM_ID],
                payload,
                episode_id=call.data.get(ATTR_EPISODE_ID),
            )
        except AudiobookshelfError as err:
            raise HomeAssistantError(f"Audiobookshelf rejected the update: {err}") from err
        await coordinator.async_request_refresh()

    async def async_mark_finished(call: ServiceCall) -> None:
        """Mark an item as finished."""
        await _async_patch(call, {"isFinished": True})

    async def async_mark_unfinished(call: ServiceCall) -> None:
        """Mark an item as unfinished and rewind it to the start."""
        await _async_patch(call, {"isFinished": False, "progress": 0, "currentTime": 0})

    async def async_set_progress(call: ServiceCall) -> None:
        """Move the playback position of an item."""
        coordinator = _coordinator_for(call)
        item_id = call.data[ATTR_ITEM_ID]

        if ATTR_CURRENT_TIME in call.data:
            current_time = float(call.data[ATTR_CURRENT_TIME])
            payload: dict[str, Any] = {"currentTime": current_time}
            book = coordinator.async_get_book(item_id)
            duration = (book or {}).get("duration")
            if duration:
                payload["progress"] = max(0.0, min(1.0, current_time / float(duration)))
        elif ATTR_PERCENT in call.data:
            fraction = float(call.data[ATTR_PERCENT]) / 100
            payload = {"progress": fraction}
            book = coordinator.async_get_book(item_id)
            duration = (book or {}).get("duration")
            if duration:
                payload["currentTime"] = fraction * float(duration)
        else:
            raise ServiceValidationError(f"Pass either {ATTR_CURRENT_TIME} or {ATTR_PERCENT}")

        try:
            await coordinator.client.async_update_progress(
                item_id, payload, episode_id=call.data.get(ATTR_EPISODE_ID)
            )
        except AudiobookshelfError as err:
            raise HomeAssistantError(f"Audiobookshelf rejected the update: {err}") from err
        await coordinator.async_request_refresh()

    async def async_refresh(call: ServiceCall) -> None:
        """Force a poll of one or every configured server."""
        entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
        coordinators: dict[str, AudiobookshelfCoordinator] = hass.data.get(DOMAIN, {})
        targets = [_coordinator_for(call)] if entry_id else list(coordinators.values())
        for coordinator in targets:
            await coordinator.async_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_MARK_FINISHED, async_mark_finished, schema=BASE_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_MARK_UNFINISHED, async_mark_unfinished, schema=BASE_SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_PROGRESS, async_set_progress, schema=SET_PROGRESS_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, async_refresh, schema=REFRESH_SCHEMA)
