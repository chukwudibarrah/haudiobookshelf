"""Constants for the Audiobookshelf integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "audiobookshelf"
MANUFACTURER: Final = "Audiobookshelf"

# Config entry keys
CONF_URL: Final = "url"
CONF_TOKEN: Final = "token"
CONF_VERIFY_SSL: Final = "verify_ssl"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_LIBRARIES: Final = "libraries"
CONF_MAX_ITEMS: Final = "max_items"
CONF_ACTIVE_WINDOW: Final = "active_window"
CONF_PUBLIC_URL: Final = "public_url"

DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 3600
DEFAULT_MAX_ITEMS: Final = 10
DEFAULT_ACTIVE_WINDOW: Final = 300

# How often (in seconds) the slower endpoints are polled, independent of the
# main scan interval. Listening stats and library listings barely change from
# one minute to the next, and on large libraries they are the expensive calls.
STATS_INTERVAL: Final = 300
LIBRARY_INTERVAL: Final = 900
SERVER_INTERVAL: Final = 3600

# Frontend
URL_BASE: Final = "/audiobookshelf_frontend"
CARD_FILENAME: Final = "audiobookshelf-card.js"

# hass.data keys
DATA_COORDINATORS: Final = "coordinators"
DATA_FRONTEND_REGISTERED: Final = "frontend_registered"
DATA_VIEWS_REGISTERED: Final = "views_registered"
DATA_WEBSOCKET_REGISTERED: Final = "websocket_registered"
DATA_SERVICES_REGISTERED: Final = "services_registered"

# Services
SERVICE_MARK_FINISHED: Final = "mark_finished"
SERVICE_MARK_UNFINISHED: Final = "mark_unfinished"
SERVICE_SET_PROGRESS: Final = "set_progress"
SERVICE_REFRESH: Final = "refresh"

ATTR_ITEM_ID: Final = "item_id"
ATTR_EPISODE_ID: Final = "episode_id"
ATTR_CURRENT_TIME: Final = "current_time"
ATTR_PERCENT: Final = "percent"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
