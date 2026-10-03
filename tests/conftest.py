"""Shared fixtures for the Audiobookshelf tests."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiobookshelf.const import (
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_SSL,
    DOMAIN,
)

from .const import (
    ITEM_DETAILS,
    ITEMS_IN_PROGRESS,
    LIBRARIES,
    LIBRARY_ITEMS,
    LIBRARY_STATS,
    LISTENING_STATS,
    ME,
    MOCK_TOKEN,
    MOCK_URL,
    STATUS,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry for the integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Audiobookshelf (badrat)",
        unique_id=f"{MOCK_URL}::usr_abc123",
        data={
            CONF_URL: MOCK_URL,
            CONF_TOKEN: MOCK_TOKEN,
            CONF_VERIFY_SSL: True,
        },
    )


def build_client_mock() -> AsyncMock:
    """Return an AudiobookshelfClient mock wired to the fixtures."""
    client = AsyncMock()
    client.base_url = MOCK_URL
    client.token = MOCK_TOKEN
    client.async_get_status.return_value = STATUS
    client.async_get_me.return_value = ME
    client.async_get_items_in_progress.return_value = ITEMS_IN_PROGRESS["libraryItems"]
    client.async_get_listening_stats.return_value = _stats_with_today()
    client.async_get_libraries.return_value = LIBRARIES["libraries"]
    client.async_get_library_items.return_value = LIBRARY_ITEMS["results"]
    client.async_get_library_stats.return_value = LIBRARY_STATS
    client.async_validate.return_value = ME
    client.async_get_cover.return_value = (b"\x89PNG fake", "image/png")

    async def _get_item(item_id: str):
        from custom_components.audiobookshelf.api import AudiobookshelfNotFoundError

        if item_id not in ITEM_DETAILS:
            raise AudiobookshelfNotFoundError(item_id)
        return ITEM_DETAILS[item_id]

    client.async_get_item.side_effect = _get_item
    return client


def _stats_with_today() -> dict:
    """Listening stats whose day keys line up with the real 'today'.

    The streak and week calculations key off Home Assistant's local date, so the
    fixture has to move with that clock rather than sit on a fixed date. It must
    not use the machine's date: the test harness runs Home Assistant in
    US/Pacific, which is a day behind UTC for eight hours of every day.
    """
    today = dt_util.now().date()
    days = {
        (today - dt.timedelta(days=offset)).isoformat(): 3600 - offset * 100
        for offset in range(4)
    }
    # A gap, so the streak stops at four days rather than running on.
    days[(today - dt.timedelta(days=5)).isoformat()] = 1800
    return {**LISTENING_STATS, "days": days, "today": days[today.isoformat()]}


@pytest.fixture
def mock_client(hass):
    """Patch the API client everywhere the integration constructs one.

    Depends on ``hass`` so Home Assistant's time zone is set before the
    listening-stats fixture works out what "today" is.
    """
    client = build_client_mock()
    with (
        patch(
            "custom_components.audiobookshelf.AudiobookshelfClient",
            return_value=client,
        ),
        patch(
            "custom_components.audiobookshelf.config_flow.AudiobookshelfClient",
            return_value=client,
        ),
    ):
        yield client
