"""Minimal async client for the Audiobookshelf server API.

Only the endpoints the integration actually needs are implemented. Everything
returns plain decoded JSON; normalising it into something friendly is the
coordinator's job.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=20)
COVER_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Audiobookshelf IDs are prefixed slugs (li_8gch9ve09orgn4fdz8) or UUIDs.
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


class AudiobookshelfError(Exception):
    """Base class for every error raised by the client."""


class AudiobookshelfConnectionError(AudiobookshelfError):
    """The server could not be reached."""


class AudiobookshelfAuthError(AudiobookshelfError):
    """The server rejected our API token."""


class AudiobookshelfNotFoundError(AudiobookshelfError):
    """The requested resource does not exist."""


def _path_id(value: str) -> str:
    """Return an ID that is safe to put in a URL path, or raise.

    IDs reach the client from service calls and the card's websocket, which
    any Home Assistant user can send. Unchecked, an ID such as ``../../x``
    would aim a request carrying our API token at another endpoint.
    """
    if not _ID_PATTERN.fullmatch(str(value)):
        raise AudiobookshelfNotFoundError(f"Not a valid Audiobookshelf ID: {value!r}")
    return value


class AudiobookshelfClient:
    """Thin wrapper around the Audiobookshelf HTTP API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token: str | None = None,
    ) -> None:
        """Initialise the client."""
        self._session = session
        self._url = url.rstrip("/")
        self._token = token

    @property
    def base_url(self) -> str:
        """Return the configured server URL, without a trailing slash."""
        return self._url

    @property
    def token(self) -> str | None:
        """Return the API token in use."""
        return self._token

    def set_token(self, token: str) -> None:
        """Replace the API token, e.g. after a reauth."""
        self._token = token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Perform a request and return the decoded JSON body."""
        url = f"{self._url}{path}"
        headers = {"Accept": "application/json"}
        if authenticated and self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise AudiobookshelfAuthError(
                        f"Audiobookshelf rejected the API token ({response.status})"
                    )
                if response.status == 404:
                    raise AudiobookshelfNotFoundError(f"Not found: {path}")
                if response.status >= 400:
                    body = (await response.text())[:200]
                    raise AudiobookshelfError(
                        f"Audiobookshelf returned HTTP {response.status} for {path}: {body}"
                    )
                if response.status == 204 or response.content_length == 0:
                    return {}
                # Audiobookshelf is not always careful about its content-type
                # header, so decode regardless of what it claims to be.
                return await response.json(content_type=None)
        except TimeoutError as err:
            raise AudiobookshelfConnectionError(f"Timeout connecting to {url}") from err
        except aiohttp.ClientError as err:
            raise AudiobookshelfConnectionError(f"Error connecting to {url}: {err}") from err

    async def async_get_status(self) -> dict[str, Any]:
        """Return server status. This endpoint needs no authentication."""
        return await self._request("GET", "/status", authenticated=False)

    async def async_get_me(self) -> dict[str, Any]:
        """Return the authenticated user, including their full media progress."""
        return await self._request("GET", "/api/me")

    async def async_get_items_in_progress(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return the user's continue-listening shelf."""
        data = await self._request("GET", "/api/me/items-in-progress", params={"limit": limit})
        return data.get("libraryItems") or []

    async def async_get_listening_stats(self) -> dict[str, Any]:
        """Return aggregated listening statistics for the user."""
        return await self._request("GET", "/api/me/listening-stats")

    async def async_get_libraries(self) -> list[dict[str, Any]]:
        """Return every library visible to the user."""
        data = await self._request("GET", "/api/libraries")
        return data.get("libraries") or []

    async def async_get_library_items(
        self,
        library_id: str,
        *,
        limit: int = 10,
        sort: str = "addedAt",
        desc: bool = True,
        library_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return items from a library, newest first by default."""
        params: dict[str, Any] = {
            "limit": limit,
            "page": 0,
            "sort": sort,
            "desc": 1 if desc else 0,
            "minified": 1,
        }
        if library_filter:
            params["filter"] = library_filter
        data = await self._request(
            "GET", f"/api/libraries/{_path_id(library_id)}/items", params=params
        )
        return data.get("results") or []

    async def async_get_library_stats(self, library_id: str) -> dict[str, Any]:
        """Return the item/size totals for a library."""
        return await self._request("GET", f"/api/libraries/{_path_id(library_id)}/stats")

    async def async_get_item(self, item_id: str) -> dict[str, Any]:
        """Return a single library item."""
        return await self._request("GET", f"/api/items/{_path_id(item_id)}")

    async def async_get_series(self, library_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return series in a library, most recently added first."""
        data = await self._request(
            "GET",
            f"/api/libraries/{_path_id(library_id)}/series",
            params={"limit": limit, "page": 0, "sort": "addedAt", "desc": 1},
        )
        return data.get("results") or []

    async def async_update_progress(
        self,
        item_id: str,
        payload: dict[str, Any],
        episode_id: str | None = None,
    ) -> None:
        """Patch the user's progress for an item (or a podcast episode)."""
        path = f"/api/me/progress/{_path_id(item_id)}"
        if episode_id:
            path = f"{path}/{_path_id(episode_id)}"
        await self._request("PATCH", path, json=payload)

    async def async_get_cover(
        self, item_id: str, width: int = 400, raw: bool = False
    ) -> tuple[bytes, str]:
        """Return the cover image bytes and content type for an item."""
        url = f"{self._url}/api/items/{_path_id(item_id)}/cover"
        params: dict[str, Any] = {"raw": 1} if raw else {"width": width}
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            async with self._session.get(
                url, params=params, headers=headers, timeout=COVER_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise AudiobookshelfAuthError("Audiobookshelf rejected the API token")
                if response.status == 404:
                    raise AudiobookshelfNotFoundError(f"No cover for item {item_id}")
                if response.status >= 400:
                    raise AudiobookshelfError(
                        f"Cover request failed with HTTP {response.status}"
                    )
                content_type = response.headers.get("Content-Type", "image/jpeg")
                return await response.read(), content_type.split(";")[0].strip()
        except TimeoutError as err:
            raise AudiobookshelfConnectionError("Timeout fetching cover art") from err
        except aiohttp.ClientError as err:
            raise AudiobookshelfConnectionError(f"Error fetching cover art: {err}") from err

    async def async_validate(self) -> dict[str, Any]:
        """Check that the URL and token work, returning the user object."""
        me = await self.async_get_me()
        if not me.get("id"):
            raise AudiobookshelfError("Unexpected response from /api/me")
        return me
