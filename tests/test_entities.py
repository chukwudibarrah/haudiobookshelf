"""Tests for the entities and the websocket API."""

from __future__ import annotations

from custom_components.audiobookshelf.const import DOMAIN

from .test_init import setup_integration


async def test_sensor_states(hass, mock_config_entry, mock_client) -> None:
    """The headline sensors report what we expect."""
    await setup_integration(hass, mock_config_entry)

    now = hass.states.get("sensor.audiobookshelf_badrat_now_listening")
    assert now is not None
    assert now.state == "Dune"
    assert now.attributes["author"] == "Frank Herbert"
    assert now.attributes["item_id"] == "li_current"
    assert now.attributes["percent"] == 42.1

    assert (
        hass.states.get("sensor.audiobookshelf_badrat_last_finished").state
        == "Project Hail Mary"
    )
    assert hass.states.get("sensor.audiobookshelf_badrat_books_in_progress").state == "2"
    assert hass.states.get("sensor.audiobookshelf_badrat_books_finished").state == "3"
    assert hass.states.get("sensor.audiobookshelf_badrat_listening_streak").state == "4"
    assert (
        hass.states.get("sensor.audiobookshelf_badrat_now_listening_progress").state == "42.1"
    )

    listening = hass.states.get("binary_sensor.audiobookshelf_badrat_listening")
    assert listening is not None
    assert listening.state == "off"


async def test_sensor_state_is_truncated(hass, mock_config_entry, mock_client) -> None:
    """A very long title still produces a valid state."""
    from .const import ITEMS_IN_PROGRESS

    items = [dict(item) for item in ITEMS_IN_PROGRESS["libraryItems"]]
    items[0] = {**items[0], "media": {**items[0]["media"]}}
    items[0]["media"]["metadata"] = {
        **items[0]["media"]["metadata"],
        "title": "T" * 400,
    }
    mock_client.async_get_items_in_progress.return_value = items

    await setup_integration(hass, mock_config_entry)
    state = hass.states.get("sensor.audiobookshelf_badrat_now_listening")
    assert len(state.state) <= 255
    # The untruncated title stays available as an attribute.
    assert len(state.attributes["title"]) == 400


async def test_image_entities(
    hass, mock_config_entry, mock_client, hass_client_no_auth
) -> None:
    """Cover images are created and serve bytes through their signed URL."""
    await setup_integration(hass, mock_config_entry)

    state = hass.states.get("image.audiobookshelf_badrat_now_listening_cover")
    assert state is not None
    assert state.state != "unavailable"

    # entity_picture carries its own access token, so no auth header is needed.
    client = await hass_client_no_auth()
    response = await client.get(state.attributes["entity_picture"])
    assert response.status == 200
    assert await response.read() == b"\x89PNG fake"

    finished = hass.states.get("image.audiobookshelf_badrat_last_finished_cover")
    assert finished is not None


async def test_cover_proxy_requires_auth(
    hass, mock_config_entry, mock_client, hass_client_no_auth
) -> None:
    """The cover view is not open to unauthenticated callers."""
    await setup_integration(hass, mock_config_entry)
    client = await hass_client_no_auth()
    response = await client.get(f"/api/{DOMAIN}/cover/{mock_config_entry.entry_id}/li_current")
    assert response.status == 401


async def test_cover_proxy_serves_image(
    hass, mock_config_entry, mock_client, hass_client
) -> None:
    """An authenticated request gets the proxied cover back."""
    await setup_integration(hass, mock_config_entry)
    client = await hass_client()
    response = await client.get(
        f"/api/{DOMAIN}/cover/{mock_config_entry.entry_id}/li_current?width=250"
    )
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("image/png")
    assert await response.read() == b"\x89PNG fake"
    mock_client.async_get_cover.assert_awaited_with("li_current", width=250)


async def test_cover_proxy_clamps_width(
    hass, mock_config_entry, mock_client, hass_client
) -> None:
    """A silly width is clamped rather than passed to the server."""
    await setup_integration(hass, mock_config_entry)
    client = await hass_client()
    await client.get(
        f"/api/{DOMAIN}/cover/{mock_config_entry.entry_id}/li_current?width=99999"
    )
    assert mock_client.async_get_cover.await_args.kwargs["width"] == 1200


async def test_cover_proxy_unknown_entry(
    hass, mock_config_entry, mock_client, hass_client
) -> None:
    """An unknown config entry is a 404, not a traceback."""
    await setup_integration(hass, mock_config_entry)
    client = await hass_client()
    response = await client.get(f"/api/{DOMAIN}/cover/does_not_exist/li_current")
    assert response.status == 404


async def test_websocket_data_and_subscription(
    hass, mock_config_entry, mock_client, hass_ws_client
) -> None:
    """The card's websocket commands return data and push updates."""
    await setup_integration(hass, mock_config_entry)
    ws = await hass_ws_client(hass)

    await ws.send_json({"id": 1, "type": f"{DOMAIN}/entries"})
    response = await ws.receive_json()
    assert response["success"]
    assert response["result"]["entries"][0]["entry_id"] == mock_config_entry.entry_id

    await ws.send_json({"id": 2, "type": f"{DOMAIN}/data"})
    response = await ws.receive_json()
    assert response["success"]
    assert response["result"]["now"]["title"] == "Dune"

    await ws.send_json({"id": 3, "type": f"{DOMAIN}/subscribe"})
    response = await ws.receive_json()
    assert response["success"]

    # The current snapshot arrives immediately...
    event = await ws.receive_json()
    assert event["event"]["now"]["title"] == "Dune"

    # ...and again on the next refresh.
    await hass.data[DOMAIN][mock_config_entry.entry_id].async_refresh()
    event = await ws.receive_json()
    assert event["event"]["now"]["id"] == "li_current"


async def test_websocket_set_finished(
    hass, mock_config_entry, mock_client, hass_ws_client
) -> None:
    """The card can mark a book finished."""
    await setup_integration(hass, mock_config_entry)
    ws = await hass_ws_client(hass)

    await ws.send_json(
        {
            "id": 1,
            "type": f"{DOMAIN}/set_finished",
            "item_id": "li_current",
            "finished": True,
        }
    )
    response = await ws.receive_json()
    assert response["success"]
    mock_client.async_update_progress.assert_awaited_once_with(
        "li_current", {"isFinished": True}, episode_id=None
    )


async def test_websocket_unknown_entry(
    hass, mock_config_entry, mock_client, hass_ws_client
) -> None:
    """Asking for a server that is not configured is an error, not a crash."""
    await setup_integration(hass, mock_config_entry)
    ws = await hass_ws_client(hass)

    await ws.send_json({"id": 1, "type": f"{DOMAIN}/data", "entry_id": "nope"})
    response = await ws.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "not_found"


async def test_diagnostics_redacts_secrets(
    hass, mock_config_entry, mock_client, hass_client
) -> None:
    """Diagnostics do not leak the URL or the token."""
    from pytest_homeassistant_custom_component.components.diagnostics import (
        get_diagnostics_for_config_entry,
    )

    await setup_integration(hass, mock_config_entry)
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, mock_config_entry)
    dumped = str(diagnostics)
    assert "exp_abcdef1234567890" not in dumped
    assert "192.168.1.10" not in dumped
    assert diagnostics["coordinator"]["counts"]["finished"] == 2
