"""Tests for setting up and tearing down the Audiobookshelf integration."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.audiobookshelf.api import (
    AudiobookshelfAuthError,
    AudiobookshelfConnectionError,
)
from custom_components.audiobookshelf.const import (
    ATTR_ITEM_ID,
    ATTR_PERCENT,
    DOMAIN,
    SERVICE_MARK_FINISHED,
    SERVICE_MARK_UNFINISHED,
    SERVICE_REFRESH,
    SERVICE_SET_PROGRESS,
)


async def setup_integration(hass: HomeAssistant, entry) -> None:
    """Add the config entry and let it set up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(hass, mock_config_entry, mock_client) -> None:
    """The entry loads, creates entities, and unloads cleanly."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert DOMAIN in hass.data

    for service in (
        SERVICE_MARK_FINISHED,
        SERVICE_MARK_UNFINISHED,
        SERVICE_SET_PROGRESS,
        SERVICE_REFRESH,
    ):
        assert hass.services.has_service(DOMAIN, service)

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert mock_config_entry.entry_id not in hass.data[DOMAIN]
    # Services are torn down with the last entry.
    assert not hass.services.has_service(DOMAIN, SERVICE_MARK_FINISHED)


async def test_setup_retries_when_server_is_down(hass, mock_config_entry, mock_client) -> None:
    """A connection failure leaves the entry in a retrying state."""
    mock_client.async_get_me.side_effect = AudiobookshelfConnectionError("nope")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_starts_reauth_on_bad_token(hass, mock_config_entry, mock_client) -> None:
    """A rejected token asks the user to reauthenticate."""
    mock_client.async_get_me.side_effect = AudiobookshelfAuthError("bad token")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_mark_finished_service(hass, mock_config_entry, mock_client) -> None:
    """The mark_finished service patches progress and refreshes."""
    await setup_integration(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_MARK_FINISHED,
        {ATTR_ITEM_ID: "li_current"},
        blocking=True,
    )
    mock_client.async_update_progress.assert_awaited_once_with(
        "li_current", {"isFinished": True}, episode_id=None
    )


async def test_mark_unfinished_rewinds(hass, mock_config_entry, mock_client) -> None:
    """Un-finishing also resets the position, or the server re-finishes it."""
    await setup_integration(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_MARK_UNFINISHED,
        {ATTR_ITEM_ID: "li_current"},
        blocking=True,
    )
    mock_client.async_update_progress.assert_awaited_once_with(
        "li_current",
        {"isFinished": False, "progress": 0, "currentTime": 0},
        episode_id=None,
    )


async def test_set_progress_by_percent_derives_time(
    hass, mock_config_entry, mock_client
) -> None:
    """A percentage is converted to a position using the known duration."""
    await setup_integration(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_PROGRESS,
        {ATTR_ITEM_ID: "li_current", ATTR_PERCENT: 50},
        blocking=True,
    )
    args = mock_client.async_update_progress.await_args
    assert args.args[0] == "li_current"
    assert args.args[1]["progress"] == pytest.approx(0.5)
    # li_current runs for 36000 seconds.
    assert args.args[1]["currentTime"] == pytest.approx(18000)


async def test_set_progress_requires_a_position(hass, mock_config_entry, mock_client) -> None:
    """Calling set_progress with neither argument is rejected."""
    await setup_integration(hass, mock_config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_PROGRESS, {ATTR_ITEM_ID: "li_current"}, blocking=True
        )


async def test_options_update_reloads_entry(hass, mock_config_entry, mock_client) -> None:
    """Changing options reloads the entry so they take effect."""
    from custom_components.audiobookshelf.const import CONF_SCAN_INTERVAL

    await setup_integration(hass, mock_config_entry)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_SCAN_INTERVAL: 120}
    )
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id]
    assert coordinator.update_interval.total_seconds() == 120
