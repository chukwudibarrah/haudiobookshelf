"""Cover art image entities for Audiobookshelf.

``cover_url`` on the sensors points at an authenticated Home Assistant view,
which a plain ``<img>`` cannot load. These entities exist so cover art works in
ordinary picture cards and in notifications, where Home Assistant handles the
access token for us.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import AudiobookshelfError
from .const import DOMAIN
from .coordinator import AudiobookshelfCoordinator
from .entity import AudiobookshelfEntity

_LOGGER = logging.getLogger(__name__)

COVER_WIDTH = 600

IMAGES: tuple[tuple[str, str], ...] = (
    ("now_cover", "now"),
    ("last_finished_cover", "finished"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Audiobookshelf cover images."""
    coordinator: AudiobookshelfCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AudiobookshelfCoverImage(coordinator, key, source) for key, source in IMAGES
    )


class AudiobookshelfCoverImage(AudiobookshelfEntity, ImageEntity):
    """Cover art for the current or most recently finished book."""

    def __init__(
        self,
        coordinator: AudiobookshelfCoordinator,
        key: str,
        source: str,
    ) -> None:
        """Initialise the image entity."""
        AudiobookshelfEntity.__init__(self, coordinator, key)
        ImageEntity.__init__(self, coordinator.hass)
        self.entity_description = ImageEntityDescription(key=key, translation_key=key)
        self._source = source
        self._item_id: str | None = None
        self._cached: bytes | None = None
        self._sync_item()

    def _current_book(self) -> dict[str, Any] | None:
        """Return the book this entity is showing."""
        data = self.coordinator.data or {}
        if self._source == "now":
            return data.get("now")
        return next(iter(data.get("finished") or []), None)

    @callback
    def _sync_item(self) -> None:
        """Track which item we are showing and invalidate the cache on change."""
        book = self._current_book()
        item_id = book.get("id") if book else None
        if item_id == self._item_id:
            return
        self._item_id = item_id
        self._cached = None
        self._attr_image_last_updated = dt_util.utcnow() if item_id else None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle new data from the coordinator."""
        self._sync_item()
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Return whether there is a book to show."""
        return super().available and self._item_id is not None

    async def async_image(self) -> bytes | None:
        """Return the cover art bytes."""
        if self._item_id is None:
            return None
        if self._cached is None:
            try:
                image, content_type = await self.coordinator.client.async_get_cover(
                    self._item_id, width=COVER_WIDTH
                )
            except AudiobookshelfError as err:
                _LOGGER.debug("Could not fetch cover for %s: %s", self._item_id, err)
                return None
            self._attr_content_type = content_type
            self._cached = image
        return self._cached
