"""Fixtures shaped like real Audiobookshelf API responses."""

from __future__ import annotations

# Timestamps are milliseconds, as Audiobookshelf returns them.
NOW_MS = 1_767_225_600_000  # 2026-01-01T00:00:00Z

MOCK_URL = "http://192.168.1.10:13378"
MOCK_TOKEN = "exp_abcdef1234567890"

STATUS = {
    "isInit": True,
    "language": "en-us",
    "serverVersion": "2.26.3",
    "authMethods": ["local"],
}

ME = {
    "id": "usr_abc123",
    "username": "badrat",
    "type": "root",
    "mediaProgress": [
        {
            "id": "prog_1",
            "libraryItemId": "li_current",
            "episodeId": None,
            "duration": 36000.0,
            "progress": 0.4211,
            "currentTime": 15159.6,
            "isFinished": False,
            "hideFromContinueListening": False,
            "lastUpdate": NOW_MS - 30_000,
            "startedAt": NOW_MS - 500_000_000,
            "finishedAt": None,
        },
        {
            "id": "prog_2",
            "libraryItemId": "li_second",
            "episodeId": None,
            "duration": 18000.0,
            "progress": 0.1,
            "currentTime": 1800.0,
            "isFinished": False,
            "hideFromContinueListening": False,
            "lastUpdate": NOW_MS - 800_000_000,
            "startedAt": NOW_MS - 900_000_000,
            "finishedAt": None,
        },
        {
            "id": "prog_3",
            "libraryItemId": "li_done_recent",
            "episodeId": None,
            "duration": 25000.0,
            "progress": 1,
            "currentTime": 25000.0,
            "isFinished": True,
            "hideFromContinueListening": False,
            "lastUpdate": NOW_MS - 86_400_000,
            "startedAt": NOW_MS - 900_000_000,
            "finishedAt": NOW_MS - 86_400_000,
        },
        {
            "id": "prog_4",
            "libraryItemId": "li_done_older",
            "episodeId": None,
            "duration": 12000.0,
            "progress": 1,
            "currentTime": 12000.0,
            "isFinished": True,
            "hideFromContinueListening": False,
            "lastUpdate": NOW_MS - 500_000_000,
            "startedAt": NOW_MS - 900_000_000,
            "finishedAt": NOW_MS - 500_000_000,
        },
        {
            # Progress for an item that has since been deleted from the library.
            "id": "prog_5",
            "libraryItemId": "li_deleted",
            "episodeId": None,
            "duration": 100.0,
            "progress": 1,
            "currentTime": 100.0,
            "isFinished": True,
            "finishedAt": NOW_MS - 600_000_000,
            "lastUpdate": NOW_MS - 600_000_000,
        },
    ],
}


def _item(item_id, title, author, duration, added_at=NOW_MS, **extra):
    """Build a minified library item the way Audiobookshelf does."""
    metadata = {
        "title": title,
        "titleIgnorePrefix": title,
        "subtitle": extra.pop("subtitle", None),
        "authorName": author,
        "narratorName": extra.pop("narrator", "A Narrator"),
        "seriesName": extra.pop("series_name", None),
        "genres": ["Science Fiction"],
        "publishedYear": "1965",
        "explicit": False,
    }
    metadata.update(extra.pop("metadata", {}))
    return {
        "id": item_id,
        "libraryId": "lib_books",
        "mediaType": "book",
        "addedAt": added_at,
        "updatedAt": added_at,
        "coverPath": f"/metadata/items/{item_id}/cover.jpg",
        "media": {
            "metadata": metadata,
            "coverPath": f"/metadata/items/{item_id}/cover.jpg",
            "numTracks": 12,
            "numChapters": 24,
            "duration": duration,
            "size": 512_000_000,
        },
        **extra,
    }


ITEMS_IN_PROGRESS = {
    "libraryItems": [
        _item("li_current", "Dune", "Frank Herbert", 36000.0, series_name="Dune"),
        _item("li_second", "Piranesi", "Susanna Clarke", 18000.0),
    ]
}

ITEM_DETAILS = {
    "li_done_recent": _item("li_done_recent", "Project Hail Mary", "Andy Weir", 25000.0),
    "li_done_older": _item("li_done_older", "Recursion", "Blake Crouch", 12000.0),
}

LIBRARIES = {
    "libraries": [
        {"id": "lib_books", "name": "Audiobooks", "mediaType": "book"},
        {"id": "lib_pods", "name": "Podcasts", "mediaType": "podcast"},
    ]
}

LIBRARY_ITEMS = {
    "results": [
        _item("li_new_1", "The Spare Man", "Mary Robinette Kowal", 30000.0, added_at=NOW_MS),
        _item(
            "li_new_2",
            "Sea of Tranquility",
            "Emily St. John Mandel",
            21000.0,
            added_at=NOW_MS - 86_400_000,
        ),
    ]
}

LIBRARY_STATS = {"totalItems": 412, "totalAuthors": 190, "totalSize": 900_000_000_000}

LISTENING_STATS = {
    "totalTime": 900_000,
    "items": {},
    "days": {},
    "dayOfWeek": {},
    "today": 3600,
    "recentSessions": [],
}
