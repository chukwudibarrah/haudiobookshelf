"""Tests for the Audiobookshelf API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.audiobookshelf.api import (
    AudiobookshelfClient,
    AudiobookshelfNotFoundError,
)

from .const import MOCK_TOKEN, MOCK_URL

BAD_IDS = ["..", "../../api/me", "li_1/../../me", "li 1", "li_1?x=1", "", "li_1%2F.."]


@pytest.fixture
def session() -> MagicMock:
    """A session that fails the test if the client ever uses it."""
    return MagicMock(side_effect=AssertionError("no request expected"))


@pytest.mark.parametrize("bad_id", BAD_IDS)
async def test_progress_rejects_unsafe_item_ids(session, bad_id) -> None:
    """An ID that could change the request path is refused before any request."""
    client = AudiobookshelfClient(session, MOCK_URL, MOCK_TOKEN)
    with pytest.raises(AudiobookshelfNotFoundError):
        await client.async_update_progress(bad_id, {"isFinished": True})
    session.request.assert_not_called()


# An empty episode ID means "not an episode", so it is not in this list.
@pytest.mark.parametrize("bad_id", [bad for bad in BAD_IDS if bad])
async def test_progress_rejects_unsafe_episode_ids(session, bad_id) -> None:
    """Episode IDs are checked too; they are appended to the same path."""
    client = AudiobookshelfClient(session, MOCK_URL, MOCK_TOKEN)
    with pytest.raises(AudiobookshelfNotFoundError):
        await client.async_update_progress("li_ok", {"isFinished": True}, episode_id=bad_id)
    session.request.assert_not_called()


@pytest.mark.parametrize("bad_id", BAD_IDS)
async def test_item_and_cover_reject_unsafe_ids(session, bad_id) -> None:
    """Item and cover lookups refuse the same IDs."""
    client = AudiobookshelfClient(session, MOCK_URL, MOCK_TOKEN)
    with pytest.raises(AudiobookshelfNotFoundError):
        await client.async_get_item(bad_id)
    with pytest.raises(AudiobookshelfNotFoundError):
        await client.async_get_cover(bad_id)
    session.request.assert_not_called()
    session.get.assert_not_called()


class RecordingSession:
    """Just enough of aiohttp.ClientSession to see which URLs were requested."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url))
        response = MagicMock(status=200, content_length=None)
        response.json = AsyncMock(return_value={"id": "ok"})
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        return context


@pytest.mark.parametrize(
    "item_id",
    ["li_8gch9ve09orgn4fdz8", "0c2a1d7e-6b52-4f0a-9d3c-1f2e3a4b5c6d"],
)
async def test_real_ids_are_accepted(item_id) -> None:
    """Both of Audiobookshelf's ID styles reach the server unchanged."""
    session = RecordingSession()
    client = AudiobookshelfClient(session, MOCK_URL, MOCK_TOKEN)

    await client.async_update_progress(item_id, {"isFinished": True}, episode_id="ep_1")
    await client.async_get_item(item_id)

    assert session.requests == [
        ("PATCH", f"{MOCK_URL}/api/me/progress/{item_id}/ep_1"),
        ("GET", f"{MOCK_URL}/api/items/{item_id}"),
    ]
