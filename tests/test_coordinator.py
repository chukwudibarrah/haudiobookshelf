"""Tests for the normalisation the coordinator does."""

from __future__ import annotations

from homeassistant.util import dt as dt_util

from custom_components.audiobookshelf.const import DOMAIN

from .test_init import setup_integration


async def test_current_book_is_normalised(hass, mock_config_entry, mock_client) -> None:
    """The first in-progress item becomes a flat, usable dict."""
    await setup_integration(hass, mock_config_entry)
    data = hass.data[DOMAIN][mock_config_entry.entry_id].data

    now = data["now"]
    assert now["id"] == "li_current"
    assert now["title"] == "Dune"
    assert now["author"] == "Frank Herbert"
    assert now["narrator"] == "A Narrator"
    assert now["series"] == "Dune"
    assert now["duration"] == 36000
    assert now["current_time"] == 15160
    assert now["percent"] == 42.1  # 0.4211, rounded to one decimal
    assert now["remaining"] == 36000 - 15160
    assert now["is_finished"] is False
    assert now["cover_url"] == (f"/api/{DOMAIN}/cover/{mock_config_entry.entry_id}/li_current")
    assert now["url"].endswith("/item/li_current")


async def test_finished_list_is_ordered_and_survives_deletions(
    hass, mock_config_entry, mock_client
) -> None:
    """Finished books come back newest first, and deleted items are dropped."""
    await setup_integration(hass, mock_config_entry)
    data = hass.data[DOMAIN][mock_config_entry.entry_id].data

    titles = [book["title"] for book in data["finished"]]
    assert titles == ["Project Hail Mary", "Recursion"]
    assert all(book["is_finished"] for book in data["finished"])
    assert data["finished"][0]["finished_at"] is not None
    # li_deleted 404s and must not appear or raise.
    assert "li_deleted" not in [book["id"] for book in data["finished"]]


async def test_deleted_item_is_not_refetched(hass, mock_config_entry, mock_client) -> None:
    """A 404 on an item is cached, so it is requested exactly once."""
    await setup_integration(hass, mock_config_entry)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]

    first = mock_client.async_get_item.await_count
    await coordinator.async_refresh()
    # Every item, including the missing one, is served from cache the second time.
    assert mock_client.async_get_item.await_count == first


async def test_stats_and_streak(hass, mock_config_entry, mock_client) -> None:
    """Statistics are aggregated and the streak stops at the first gap."""
    await setup_integration(hass, mock_config_entry)
    stats = hass.data[DOMAIN][mock_config_entry.entry_id].data["stats"]

    assert stats["today_seconds"] == 3600
    # Four consecutive days (3600 + 3500 + 3400 + 3300) plus the stray day
    # five days back, which still falls inside the seven day window.
    assert stats["week_seconds"] == 13800 + 1800
    assert stats["streak_days"] == 4
    assert stats["books_finished"] == 3
    assert stats["books_in_progress"] == 2
    assert stats["library_items"] == 412 * 2
    assert len(stats["recent_days"]) == 30
    assert stats["recent_days"][-1]["seconds"] == 3600


async def test_stats_use_home_assistant_date(
    hass, mock_config_entry, mock_client, freezer
) -> None:
    """Days are keyed on Home Assistant's local date, not the machine's.

    At 04:00 UTC it is still the previous evening in the test time zone
    (US/Pacific), so the two dates disagree.
    """
    from .conftest import _stats_with_today

    freezer.move_to("2026-03-10T04:00:00+00:00")
    assert dt_util.now().date().isoformat() == "2026-03-09"
    mock_client.async_get_listening_stats.return_value = _stats_with_today()

    await setup_integration(hass, mock_config_entry)
    stats = hass.data[DOMAIN][mock_config_entry.entry_id].data["stats"]

    assert stats["week_seconds"] == 13800 + 1800
    assert stats["streak_days"] == 4
    assert stats["recent_days"][-1] == {"date": "2026-03-09", "seconds": 3600}


async def test_recently_added_is_sorted_across_libraries(
    hass, mock_config_entry, mock_client
) -> None:
    """Recently added merges libraries and sorts by date added."""
    await setup_integration(hass, mock_config_entry)
    added = hass.data[DOMAIN][mock_config_entry.entry_id].data["recently_added"]

    assert added
    timestamps = [book["added_at_ts"] for book in added]
    assert timestamps == sorted(timestamps, reverse=True)
    assert added[0]["library_name"] in {"Audiobooks", "Podcasts"}


async def test_is_listening_window(hass, mock_config_entry, mock_client) -> None:
    """A progress sync inside the window counts as active listening."""
    from unittest.mock import patch

    import homeassistant.util.dt as dt_util

    from .const import NOW_MS

    with patch.object(
        dt_util, "utcnow", return_value=dt_util.utc_from_timestamp(NOW_MS / 1000)
    ):
        await setup_integration(hass, mock_config_entry)
        data = hass.data[DOMAIN][mock_config_entry.entry_id].data

    # li_current synced 30 seconds before NOW_MS, inside the 300 s default.
    assert data["is_listening"] is True


async def test_not_listening_when_progress_is_stale(
    hass, mock_config_entry, mock_client
) -> None:
    """Real wall-clock time is far past the fixture, so nothing is playing."""
    await setup_integration(hass, mock_config_entry)
    assert hass.data[DOMAIN][mock_config_entry.entry_id].data["is_listening"] is False


async def test_slow_endpoints_are_not_polled_every_cycle(
    hass, mock_config_entry, mock_client
) -> None:
    """Stats and libraries stay on their own, slower schedules."""
    await setup_integration(hass, mock_config_entry)
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]

    libraries_before = mock_client.async_get_libraries.await_count
    stats_before = mock_client.async_get_listening_stats.await_count
    me_before = mock_client.async_get_me.await_count

    await coordinator.async_refresh()

    assert mock_client.async_get_me.await_count == me_before + 1
    assert mock_client.async_get_libraries.await_count == libraries_before
    assert mock_client.async_get_listening_stats.await_count == stats_before


async def test_empty_server_does_not_crash(hass, mock_config_entry, mock_client) -> None:
    """A brand new account with no books produces empty lists, not errors."""
    mock_client.async_get_me.return_value = {
        "id": "usr_new",
        "username": "new",
        "mediaProgress": [],
    }
    mock_client.async_get_items_in_progress.return_value = []
    mock_client.async_get_library_items.return_value = []
    mock_client.async_get_listening_stats.return_value = {
        "totalTime": 0,
        "days": {},
        "today": 0,
    }

    await setup_integration(hass, mock_config_entry)
    data = hass.data[DOMAIN][mock_config_entry.entry_id].data

    assert data["now"] is None
    assert data["in_progress"] == []
    assert data["finished"] == []
    assert data["is_listening"] is False
    assert data["stats"]["streak_days"] == 0
