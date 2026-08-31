"""HTTP views for Audiobookshelf.

Cover art lives behind the Audiobookshelf API token, which must never reach the
browser. This view proxies covers through Home Assistant so the frontend can
request them with normal HA authentication (the card uses a signed path).
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .api import (
    AudiobookshelfAuthError,
    AudiobookshelfError,
    AudiobookshelfNotFoundError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

MIN_WIDTH = 40
MAX_WIDTH = 1200
DEFAULT_WIDTH = 400


def _get_hass(request: web.Request) -> HomeAssistant:
    """Return the HomeAssistant instance for a request."""
    try:
        from homeassistant.components.http import KEY_HASS

        return request.app[KEY_HASS]
    except ImportError:  # pragma: no cover - older cores
        return request.app["hass"]


class AudiobookshelfCoverView(HomeAssistantView):
    """Serve Audiobookshelf cover art to authenticated Home Assistant users."""

    url = f"/api/{DOMAIN}/cover/{{entry_id}}/{{item_id}}"
    name = f"api:{DOMAIN}:cover"
    requires_auth = True

    async def get(
        self, request: web.Request, entry_id: str, item_id: str
    ) -> web.StreamResponse:
        """Return the cover image for a library item."""
        hass = _get_hass(request)
        coordinator: Any = (hass.data.get(DOMAIN) or {}).get(entry_id)
        if coordinator is None:
            return web.Response(status=404, text="Unknown config entry")

        try:
            width = int(request.query.get("width", DEFAULT_WIDTH))
        except ValueError:
            width = DEFAULT_WIDTH
        width = max(MIN_WIDTH, min(MAX_WIDTH, width))

        try:
            image, content_type = await coordinator.client.async_get_cover(
                item_id, width=width
            )
        except AudiobookshelfNotFoundError:
            return web.Response(status=404, text="No cover for this item")
        except AudiobookshelfAuthError:
            return web.Response(status=502, text="Audiobookshelf rejected the API token")
        except AudiobookshelfError as err:
            _LOGGER.debug("Cover proxy failed for %s: %s", item_id, err)
            return web.Response(status=502, text="Could not fetch cover art")

        if not image:
            return web.Response(status=404, text="Empty cover")

        return web.Response(
            body=image,
            content_type=content_type,
            headers={
                # Covers are immutable for a given item and width; let the
                # browser keep them rather than re-proxying on every render.
                "Cache-Control": "private, max-age=86400",
            },
        )
