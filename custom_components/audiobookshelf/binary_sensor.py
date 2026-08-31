"""Binary sensor for Audiobookshelf."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AudiobookshelfCoordinator
from .entity import AudiobookshelfEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Audiobookshelf binary sensor."""
    coordinator: AudiobookshelfCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AudiobookshelfListeningSensor(coordinator)])


class AudiobookshelfListeningSensor(AudiobookshelfEntity, BinarySensorEntity):
    """Whether the user appears to be listening right now.

    Audiobookshelf has no "is playing" endpoint for an arbitrary client, but
    players sync their position every few seconds while audio is running. A
    progress timestamp inside the configured window is therefore a reliable
    proxy for active playback.
    """

    _attr_translation_key = "listening"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: AudiobookshelfCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, "listening")

    @property
    def is_on(self) -> bool:
        """Return true when a book was being played recently."""
        return bool((self.coordinator.data or {}).get("is_listening"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details about what is playing."""
        book = (self.coordinator.data or {}).get("now") or {}
        return {
            "title": book.get("title"),
            "author": book.get("author"),
            "last_update": book.get("last_update"),
            "active_window": self.coordinator.active_window,
        }
