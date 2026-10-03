"""Sensors for Audiobookshelf."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import AudiobookshelfCoordinator
from .entity import AudiobookshelfEntity

# Home Assistant truncates states at 255 characters, and a state that long is
# useless in the UI anyway. Full values stay available as attributes.
MAX_STATE_LENGTH = 250


@dataclass(frozen=True, kw_only=True)
class AudiobookshelfSensorDescription(SensorEntityDescription):
    """Describes an Audiobookshelf sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _book_attributes(book: dict[str, Any] | None) -> dict[str, Any]:
    """Return the attribute set shared by the book-shaped sensors."""
    if not book:
        return {}
    return {
        "item_id": book.get("id"),
        "episode_id": book.get("episode_id"),
        "media_type": book.get("media_type"),
        "title": book.get("title"),
        "subtitle": book.get("subtitle"),
        "author": book.get("author"),
        "narrator": book.get("narrator"),
        "series": book.get("series"),
        "series_sequence": book.get("series_sequence"),
        "published_year": book.get("published_year"),
        "genres": book.get("genres"),
        "duration": book.get("duration"),
        "current_time": book.get("current_time"),
        "remaining": book.get("remaining"),
        "percent": book.get("percent"),
        "num_chapters": book.get("num_chapters"),
        "started_at": book.get("started_at"),
        "finished_at": book.get("finished_at"),
        "last_update": book.get("last_update"),
        "cover_url": book.get("cover_url"),
        "url": book.get("url"),
    }


def _titles(books: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return a compact list of books for a list-shaped sensor's attributes."""
    return [
        {
            "item_id": book.get("id"),
            "title": book.get("title"),
            "author": book.get("author"),
            "percent": book.get("percent"),
            "url": book.get("url"),
            "cover_url": book.get("cover_url"),
        }
        for book in (books or [])
    ]


def _minutes(seconds: Any) -> float | None:
    """Convert seconds to minutes, rounded for display."""
    if seconds in (None, ""):
        return None
    return round(float(seconds) / 60, 1)


def _hours(seconds: Any) -> float | None:
    """Convert seconds to hours, rounded for display."""
    if seconds in (None, ""):
        return None
    return round(float(seconds) / 3600, 2)


SENSORS: tuple[AudiobookshelfSensorDescription, ...] = (
    AudiobookshelfSensorDescription(
        key="now_listening",
        translation_key="now_listening",
        icon="mdi:book-open-page-variant",
        value_fn=lambda data: (data.get("now") or {}).get("title"),
        attributes_fn=lambda data: {
            **_book_attributes(data.get("now")),
            "is_listening": data.get("is_listening"),
        },
    ),
    AudiobookshelfSensorDescription(
        key="now_author",
        translation_key="now_author",
        icon="mdi:account-edit",
        value_fn=lambda data: (data.get("now") or {}).get("author"),
    ),
    AudiobookshelfSensorDescription(
        key="now_progress",
        translation_key="now_progress",
        icon="mdi:progress-clock",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: (data.get("now") or {}).get("percent"),
    ),
    AudiobookshelfSensorDescription(
        key="now_remaining",
        translation_key="now_remaining",
        icon="mdi:timer-sand",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: _minutes((data.get("now") or {}).get("remaining")),
    ),
    AudiobookshelfSensorDescription(
        key="last_finished",
        translation_key="last_finished",
        icon="mdi:book-check",
        value_fn=lambda data: next(
            (book.get("title") for book in data.get("finished") or []), None
        ),
        attributes_fn=lambda data: _book_attributes(
            next(iter(data.get("finished") or []), None)
        ),
    ),
    AudiobookshelfSensorDescription(
        key="books_in_progress",
        translation_key="books_in_progress",
        icon="mdi:bookmark-multiple",
        native_unit_of_measurement="books",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (data.get("stats") or {}).get("books_in_progress"),
        attributes_fn=lambda data: {"items": _titles(data.get("in_progress"))},
    ),
    AudiobookshelfSensorDescription(
        key="books_finished",
        translation_key="books_finished",
        icon="mdi:book-check-outline",
        native_unit_of_measurement="books",
        # Not total_increasing: marking a book unfinished lowers the count, and
        # Home Assistant would record that as a meter reset.
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data: (data.get("stats") or {}).get("books_finished"),
        attributes_fn=lambda data: {"items": _titles(data.get("finished"))},
    ),
    AudiobookshelfSensorDescription(
        key="recently_added",
        translation_key="recently_added",
        icon="mdi:new-box",
        value_fn=lambda data: next(
            (book.get("title") for book in data.get("recently_added") or []), None
        ),
        attributes_fn=lambda data: {"items": _titles(data.get("recently_added"))},
    ),
    AudiobookshelfSensorDescription(
        key="listening_today",
        translation_key="listening_today",
        icon="mdi:headphones",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: _minutes((data.get("stats") or {}).get("today_seconds")),
    ),
    AudiobookshelfSensorDescription(
        key="listening_week",
        translation_key="listening_week",
        icon="mdi:calendar-week",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda data: _minutes((data.get("stats") or {}).get("week_seconds")),
    ),
    AudiobookshelfSensorDescription(
        key="listening_total",
        translation_key="listening_total",
        icon="mdi:chart-timeline-variant",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda data: _hours((data.get("stats") or {}).get("total_seconds")),
        attributes_fn=lambda data: {
            "recent_days": (data.get("stats") or {}).get("recent_days")
        },
    ),
    AudiobookshelfSensorDescription(
        key="listening_streak",
        translation_key="listening_streak",
        icon="mdi:fire",
        native_unit_of_measurement="days",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: (data.get("stats") or {}).get("streak_days"),
    ),
    AudiobookshelfSensorDescription(
        key="library_items",
        translation_key="library_items",
        icon="mdi:bookshelf",
        native_unit_of_measurement="items",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (data.get("stats") or {}).get("library_items"),
        attributes_fn=lambda data: {"libraries": data.get("libraries")},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Audiobookshelf sensors."""
    coordinator: AudiobookshelfCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AudiobookshelfSensor(coordinator, description) for description in SENSORS
    )


class AudiobookshelfSensor(AudiobookshelfEntity, SensorEntity):
    """A sensor backed by the coordinator's normalised data."""

    entity_description: AudiobookshelfSensorDescription

    def __init__(
        self,
        coordinator: AudiobookshelfCoordinator,
        description: AudiobookshelfSensorDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        value = self.entity_description.value_fn(self.coordinator.data or {})
        if isinstance(value, str) and len(value) > MAX_STATE_LENGTH:
            return f"{value[: MAX_STATE_LENGTH - 1]}…"
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the sensor attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data or {})
