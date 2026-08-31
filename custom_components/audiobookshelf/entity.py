"""Shared entity base for Audiobookshelf."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import AudiobookshelfCoordinator


class AudiobookshelfEntity(CoordinatorEntity[AudiobookshelfCoordinator]):
    """Base entity tying everything to one Audiobookshelf server device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AudiobookshelfCoordinator, key: str) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        entry = coordinator.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        server = (coordinator.data or {}).get("server") or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model="Audiobookshelf server",
            sw_version=server.get("version"),
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.public_url,
        )
