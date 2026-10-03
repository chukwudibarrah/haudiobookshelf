"""Tests for the Audiobookshelf config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.audiobookshelf.api import (
    AudiobookshelfAuthError,
    AudiobookshelfConnectionError,
)
from custom_components.audiobookshelf.const import (
    CONF_LIBRARIES,
    CONF_MAX_ITEMS,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_SSL,
    DOMAIN,
)

from .const import MOCK_TOKEN, MOCK_URL
from .test_init import setup_integration


async def test_user_flow(hass, mock_client) -> None:
    """A valid URL and token create an entry."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with patch("custom_components.audiobookshelf.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: MOCK_URL, CONF_TOKEN: MOCK_TOKEN, CONF_VERIFY_SSL: True},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == MOCK_URL
    assert result["data"][CONF_TOKEN] == MOCK_TOKEN
    assert result["result"].unique_id == f"{MOCK_URL}::usr_abc123"


async def test_user_flow_adds_missing_scheme(hass, mock_client) -> None:
    """A bare host:port is turned into a URL rather than rejected."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch("custom_components.audiobookshelf.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_URL: "192.168.1.10:13378/", CONF_TOKEN: MOCK_TOKEN},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == "http://192.168.1.10:13378"


async def test_user_flow_errors(hass, mock_client) -> None:
    """Connection and auth failures are reported, and the form is retryable."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    mock_client.async_validate.side_effect = AudiobookshelfConnectionError("down")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: MOCK_URL, CONF_TOKEN: MOCK_TOKEN}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client.async_validate.side_effect = AudiobookshelfAuthError("nope")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: MOCK_URL, CONF_TOKEN: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.async_validate.side_effect = None
    with patch("custom_components.audiobookshelf.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_URL: MOCK_URL, CONF_TOKEN: MOCK_TOKEN}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_is_aborted(hass, mock_config_entry, mock_client) -> None:
    """Adding the same server and user twice is refused."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: MOCK_URL, CONF_TOKEN: MOCK_TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(hass, mock_config_entry, mock_client) -> None:
    """A new token is accepted and stored on the existing entry."""
    await setup_integration(hass, mock_config_entry)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "exp_newtoken"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_TOKEN] == "exp_newtoken"


async def test_options_flow(hass, mock_config_entry, mock_client) -> None:
    """Options are saved, and the library picker is populated from the server."""
    await setup_integration(hass, mock_config_entry)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 90,
            CONF_MAX_ITEMS: 5,
            "active_window": 600,
            CONF_LIBRARIES: ["lib_books"],
            "public_url": "https://books.example.com/",
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_SCAN_INTERVAL] == 90
    assert mock_config_entry.options[CONF_LIBRARIES] == ["lib_books"]
    assert mock_config_entry.options["public_url"] == "https://books.example.com"


async def test_reconfigure_moves_server_and_keeps_token(
    hass, mock_config_entry, mock_client
) -> None:
    """A new address is saved, and a blank token keeps the existing one."""
    await setup_integration(hass, mock_config_entry)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "https://books.example.com/", CONF_VERIFY_SSL: False},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data == {
        CONF_URL: "https://books.example.com",
        CONF_TOKEN: MOCK_TOKEN,
        CONF_VERIFY_SSL: False,
    }
    # The unique ID includes the URL, so it follows the move.
    assert mock_config_entry.unique_id == "https://books.example.com::usr_abc123"


async def test_reconfigure_replaces_token(hass, mock_config_entry, mock_client) -> None:
    """A token typed into the form replaces the stored one."""
    await setup_integration(hass, mock_config_entry)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: MOCK_URL, CONF_TOKEN: " exp_newtoken "}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_TOKEN] == "exp_newtoken"
    assert mock_config_entry.unique_id == f"{MOCK_URL}::usr_abc123"


async def test_reconfigure_rejects_another_user(hass, mock_config_entry, mock_client) -> None:
    """A token for a different user is refused rather than swapping accounts."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_validate.return_value = {"id": "usr_someone_else"}

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: MOCK_URL, CONF_TOKEN: "exp_theirs"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_account"}
    assert mock_config_entry.data[CONF_TOKEN] == MOCK_TOKEN


async def test_reconfigure_reports_connection_errors(
    hass, mock_config_entry, mock_client
) -> None:
    """An unreachable new address leaves the entry untouched."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_validate.side_effect = AudiobookshelfConnectionError("down")

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://nowhere:13378"}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert mock_config_entry.data[CONF_URL] == MOCK_URL


async def test_reconfigure_onto_existing_entry_aborts(
    hass, mock_config_entry, mock_client
) -> None:
    """Moving onto an address another entry already uses for this user is refused."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    other = MockConfigEntry(
        domain=DOMAIN,
        title="Audiobookshelf (badrat, remote)",
        unique_id="https://books.example.com::usr_abc123",
        data={CONF_URL: "https://books.example.com", CONF_TOKEN: MOCK_TOKEN},
    )
    other.add_to_hass(hass)
    await setup_integration(hass, mock_config_entry)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "https://books.example.com"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert mock_config_entry.data[CONF_URL] == MOCK_URL


async def test_reauth_rejects_another_user(hass, mock_config_entry, mock_client) -> None:
    """Reauth with someone else's token is refused, keeping the old token."""
    await setup_integration(hass, mock_config_entry)
    mock_client.async_validate.return_value = {"id": "usr_someone_else"}

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "exp_theirs"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "wrong_account"}
    assert mock_config_entry.data[CONF_TOKEN] == MOCK_TOKEN
