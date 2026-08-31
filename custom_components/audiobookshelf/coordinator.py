"""Data coordinator for Audiobookshelf."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AudiobookshelfAuthError,
    AudiobookshelfClient,
    AudiobookshelfError,
    AudiobookshelfNotFoundError,
)
from .const import (
    CONF_ACTIVE_WINDOW,
    CONF_LIBRARIES,
    CONF_MAX_ITEMS,
    CONF_PUBLIC_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_ACTIVE_WINDOW,
    DEFAULT_MAX_ITEMS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LIBRARY_INTERVAL,
    SERVER_INTERVAL,
    STATS_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Item detail lookups are cached; a finished book's metadata does not change.
ITEM_CACHE_LIMIT = 200


def _ms_to_iso(value: Any) -> str | None:
    """Convert an Audiobookshelf millisecond timestamp to an ISO string."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _join_names(value: Any, key: str | None = None) -> str | None:
    """Flatten Audiobookshelf's several shapes for name lists into a string."""
    if not value:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        names = []
        for entry in value:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict) and key:
                name = entry.get(key)
                if name:
                    names.append(str(name))
        return ", ".join(names) or None
    return None


class AudiobookshelfCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll Audiobookshelf and expose a normalised view of the data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AudiobookshelfClient,
    ) -> None:
        """Initialise the coordinator."""
        self.entry = entry
        self.client = client
        self._item_cache: dict[str, dict[str, Any]] = {}
        self._libraries: list[dict[str, Any]] = []
        self._stats: dict[str, Any] = {}
        self._recently_added: list[dict[str, Any]] = []
        self._server: dict[str, Any] = {}
        self._library_totals: dict[str, int] = {}
        self._last_stats = 0.0
        self._last_library = 0.0
        self._last_server = 0.0

        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    @property
    def max_items(self) -> int:
        """Return how many items to keep in each list."""
        return int(self.entry.options.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS))

    @property
    def active_window(self) -> int:
        """Return how recent a progress update must be to count as 'listening'."""
        return int(self.entry.options.get(CONF_ACTIVE_WINDOW, DEFAULT_ACTIVE_WINDOW))

    @property
    def selected_libraries(self) -> list[str]:
        """Return the library IDs the user wants included, empty meaning all."""
        return list(self.entry.options.get(CONF_LIBRARIES) or [])

    @property
    def public_url(self) -> str:
        """Return the URL to build clickable deep links from."""
        configured = self.entry.options.get(CONF_PUBLIC_URL) or self.entry.data.get(
            CONF_PUBLIC_URL
        )
        return str(configured or self.client.base_url).rstrip("/")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the current state of the server."""
        try:
            return await self._async_fetch()
        except AudiobookshelfAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AudiobookshelfError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_fetch(self) -> dict[str, Any]:
        """Do the actual fetching and normalising."""
        now = self.hass.loop.time()

        me = await self.client.async_get_me()
        raw_in_progress = await self.client.async_get_items_in_progress(
            limit=max(self.max_items, 10)
        )

        # The slower endpoints run on their own, longer schedules.
        if now - self._last_server > SERVER_INTERVAL or not self._server:
            self._server = await self._async_fetch_server()
            self._last_server = now
        if now - self._last_stats > STATS_INTERVAL or not self._stats:
            try:
                self._stats = await self.client.async_get_listening_stats()
            except AudiobookshelfError as err:
                _LOGGER.debug("Could not fetch listening stats: %s", err)
            self._last_stats = now
        if now - self._last_library > LIBRARY_INTERVAL or not self._libraries:
            await self._async_fetch_libraries()
            self._last_library = now

        progress_map = self._build_progress_map(me)
        in_progress = [
            book
            for book in (self._book_from_item(item, progress_map) for item in raw_in_progress)
            if book is not None
        ][: self.max_items]

        finished = await self._async_build_finished(progress_map)
        stats = self._build_stats(progress_map)

        current = in_progress[0] if in_progress else None
        last_update = current.get("last_update_ts") if current else None
        is_listening = bool(
            last_update and (dt_util.utcnow().timestamp() - last_update) <= self.active_window
        )

        return {
            "server": self._server,
            "user": {
                "id": me.get("id"),
                "username": me.get("username"),
                "type": me.get("type"),
            },
            "now": current,
            "is_listening": is_listening,
            "in_progress": in_progress,
            "finished": finished,
            "recently_added": self._recently_added,
            "libraries": [
                {
                    "id": lib.get("id"),
                    "name": lib.get("name"),
                    "media_type": lib.get("mediaType"),
                }
                for lib in self._libraries
            ],
            "stats": stats,
            "public_url": self.public_url,
            "entry_id": self.entry.entry_id,
        }

    async def _async_fetch_server(self) -> dict[str, Any]:
        """Fetch server identity, tolerating older builds without /status."""
        try:
            status = await self.client.async_get_status()
        except AudiobookshelfError as err:
            _LOGGER.debug("Could not fetch server status: %s", err)
            return {"url": self.client.base_url, "version": None}
        return {
            "url": self.client.base_url,
            "version": status.get("serverVersion"),
            "language": status.get("language"),
        }

    async def _async_fetch_libraries(self) -> None:
        """Refresh library metadata and the recently-added shelf."""
        try:
            self._libraries = await self.client.async_get_libraries()
        except AudiobookshelfError as err:
            _LOGGER.debug("Could not fetch libraries: %s", err)
            return

        selected = self.selected_libraries
        libraries = [
            lib for lib in self._libraries if not selected or lib.get("id") in selected
        ]

        added: list[dict[str, Any]] = []
        totals: dict[str, int] = {}
        for library in libraries:
            library_id = library.get("id")
            if not library_id:
                continue
            try:
                items = await self.client.async_get_library_items(
                    library_id, limit=self.max_items
                )
            except AudiobookshelfError as err:
                _LOGGER.debug("Could not fetch items for library %s: %s", library_id, err)
                continue
            for item in items:
                book = self._book_from_item(item, {})
                if book:
                    book["library_name"] = library.get("name")
                    added.append(book)
            try:
                stats = await self.client.async_get_library_stats(library_id)
                totals[library_id] = int(stats.get("totalItems") or 0)
            except AudiobookshelfError as err:
                _LOGGER.debug("Could not fetch stats for library %s: %s", library_id, err)

        added.sort(key=lambda book: book.get("added_at_ts") or 0, reverse=True)
        self._recently_added = added[: self.max_items]
        self._library_totals = totals

    def _build_progress_map(self, me: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Index the user's media progress by item (and episode) ID."""
        progress_map: dict[str, dict[str, Any]] = {}
        for progress in me.get("mediaProgress") or []:
            item_id = progress.get("libraryItemId")
            if not item_id:
                continue
            key = f"{item_id}:{progress.get('episodeId') or ''}"
            progress_map[key] = progress
        return progress_map

    async def _async_build_finished(
        self, progress_map: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Build the recently-finished list from the user's progress records."""
        entries = [
            progress for progress in progress_map.values() if progress.get("isFinished")
        ]
        entries.sort(
            key=lambda progress: progress.get("finishedAt") or progress.get("lastUpdate") or 0,
            reverse=True,
        )

        finished: list[dict[str, Any]] = []
        for progress in entries[: self.max_items]:
            item_id = progress.get("libraryItemId")
            item = await self._async_get_item_cached(item_id)
            if item is None:
                continue
            book = self._book_from_item(item, progress_map, progress_override=progress)
            if book:
                finished.append(book)
        return finished

    async def _async_get_item_cached(self, item_id: str | None) -> dict[str, Any] | None:
        """Return an item, fetching it only the first time we need it."""
        if not item_id:
            return None
        if item_id in self._item_cache:
            return self._item_cache[item_id]
        try:
            item = await self.client.async_get_item(item_id)
        except AudiobookshelfNotFoundError:
            # The book was removed from the library but the progress record
            # survives. Cache the miss so we do not re-request it every cycle.
            self._item_cache[item_id] = {}
            return None
        except AudiobookshelfError as err:
            _LOGGER.debug("Could not fetch item %s: %s", item_id, err)
            return None

        if len(self._item_cache) >= ITEM_CACHE_LIMIT:
            self._item_cache.pop(next(iter(self._item_cache)))
        self._item_cache[item_id] = item
        return item or None

    def _build_stats(self, progress_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Assemble the listening statistics block."""
        days: dict[str, Any] = self._stats.get("days") or {}
        today_key = dt_util.now().date().isoformat()
        today = float(self._stats.get("today") or days.get(today_key) or 0)

        week = 0.0
        for offset in range(7):
            key = (dt_util.now().date() - timedelta(days=offset)).isoformat()
            week += float(days.get(key) or 0)

        finished_count = sum(
            1 for progress in progress_map.values() if progress.get("isFinished")
        )
        in_progress_count = sum(
            1
            for progress in progress_map.values()
            if not progress.get("isFinished") and float(progress.get("progress") or 0) > 0
        )

        return {
            "today_seconds": round(today),
            "week_seconds": round(week),
            "total_seconds": round(float(self._stats.get("totalTime") or 0)),
            "streak_days": self._calculate_streak(days),
            "books_finished": finished_count,
            "books_in_progress": in_progress_count,
            "library_items": sum(self._library_totals.values()) or None,
            "recent_days": self._recent_days(days),
        }

    def _recent_days(self, days: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the last 30 days of listening time, oldest first.

        The raw ``days`` map grows for the lifetime of the account, and it is
        pushed to every subscribed browser, so only the useful tail is kept.
        """
        today = dt_util.now().date()
        return [
            {
                "date": (today - timedelta(days=offset)).isoformat(),
                "seconds": round(
                    float(days.get((today - timedelta(days=offset)).isoformat()) or 0)
                ),
            }
            for offset in range(29, -1, -1)
        ]

    def _calculate_streak(self, days: dict[str, Any]) -> int:
        """Count consecutive days with listening time, ending today or yesterday."""
        if not days:
            return 0
        today = dt_util.now().date()
        # A streak is still alive on a day you have not listened yet, so start
        # counting from yesterday when today is empty.
        start = (
            today if float(days.get(today.isoformat()) or 0) > 0 else today - timedelta(days=1)
        )
        streak = 0
        cursor = start
        while float(days.get(cursor.isoformat()) or 0) > 0:
            streak += 1
            cursor -= timedelta(days=1)
        return streak

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    def _book_from_item(
        self,
        item: dict[str, Any],
        progress_map: dict[str, dict[str, Any]],
        progress_override: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Turn a library item plus its progress record into a flat dict."""
        if not item or not item.get("id"):
            return None

        item_id = str(item["id"])
        media = item.get("media") or {}
        metadata = media.get("metadata") or {}
        media_type = item.get("mediaType") or "book"

        episode = item.get("recentEpisode") or {}
        episode_id = episode.get("id")

        progress = progress_override
        if progress is None:
            progress = progress_map.get(f"{item_id}:{episode_id or ''}") or {}

        duration = progress.get("duration") or media.get("duration") or episode.get("duration")
        duration = float(duration) if duration else None
        current_time = float(progress.get("currentTime") or 0)
        fraction = float(progress.get("progress") or 0)
        if not fraction and duration and current_time:
            fraction = current_time / duration
        fraction = max(0.0, min(1.0, fraction))

        series_name = metadata.get("seriesName") or _join_names(metadata.get("series"), "name")
        sequence = None
        series_list = metadata.get("series")
        if isinstance(series_list, list) and series_list:
            first = series_list[0]
            if isinstance(first, dict):
                sequence = first.get("sequence")

        title = episode.get("title") if episode_id else None
        title = title or metadata.get("title") or "Unknown title"

        book: dict[str, Any] = {
            "id": item_id,
            "episode_id": episode_id,
            "media_type": media_type,
            "title": title,
            "book_title": metadata.get("title"),
            "subtitle": metadata.get("subtitle"),
            "author": metadata.get("authorName")
            or _join_names(metadata.get("authors"), "name"),
            "narrator": metadata.get("narratorName") or _join_names(metadata.get("narrators")),
            "series": series_name,
            "series_sequence": sequence,
            "genres": metadata.get("genres") or [],
            "published_year": metadata.get("publishedYear"),
            "description": (metadata.get("description") or None),
            "duration": round(duration) if duration else None,
            "current_time": round(current_time),
            "remaining": round(duration - current_time)
            if duration and duration > current_time
            else 0,
            "progress": round(fraction, 4),
            "percent": round(fraction * 100, 1),
            "is_finished": bool(progress.get("isFinished")),
            "started_at": _ms_to_iso(progress.get("startedAt")),
            "finished_at": _ms_to_iso(progress.get("finishedAt")),
            "last_update": _ms_to_iso(progress.get("lastUpdate")),
            "last_update_ts": (float(progress["lastUpdate"]) / 1000)
            if progress.get("lastUpdate")
            else None,
            "added_at": _ms_to_iso(item.get("addedAt")),
            "added_at_ts": (float(item["addedAt"]) / 1000) if item.get("addedAt") else None,
            "num_chapters": media.get("numChapters"),
            # Always offered: the proxy view returns a 404 when the item has
            # no artwork, and the card falls back to a placeholder on error.
            # Minified items do not reliably carry coverPath, so we cannot
            # decide here whether artwork exists.
            "cover_url": f"/api/{DOMAIN}/cover/{self.entry.entry_id}/{item_id}",
            "url": f"{self.public_url}/item/{item_id}",
        }
        return book

    def async_get_book(self, item_id: str) -> dict[str, Any] | None:
        """Look a book up in the most recent data, across every list."""
        if not self.data:
            return None
        for key in ("in_progress", "finished", "recently_added"):
            for book in self.data.get(key) or []:
                if book.get("id") == item_id:
                    return book
        return None
