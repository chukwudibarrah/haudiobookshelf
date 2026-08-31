"""Tests for the bundled Lovelace card being served automatically."""

from __future__ import annotations

from custom_components.audiobookshelf.const import CARD_FILENAME, URL_BASE

from .test_init import setup_integration


async def test_card_is_registered_with_the_frontend(
    hass, mock_config_entry, mock_client
) -> None:
    """The card is added as an extra module, so no Lovelace resource is needed."""
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL

    await setup_integration(hass, mock_config_entry)

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any(f"{URL_BASE}/{CARD_FILENAME}" in url for url in urls)
    # Cache busting keeps browsers from pinning an old build after an upgrade.
    assert any("?v=" in url for url in urls)


async def test_card_is_served(
    hass, mock_config_entry, mock_client, hass_client_no_auth
) -> None:
    """The card file is reachable, and is the card we shipped."""
    await setup_integration(hass, mock_config_entry)

    client = await hass_client_no_auth()
    response = await client.get(f"{URL_BASE}/{CARD_FILENAME}")
    assert response.status == 200
    body = await response.text()
    assert 'customElements.define("audiobookshelf-card"' in body
    assert "audiobookshelf/subscribe" in body


async def test_frontend_registered_once_for_two_entries(
    hass, mock_config_entry, mock_client
) -> None:
    """A second server does not register the card twice."""
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.audiobookshelf.const import (
        CONF_TOKEN,
        CONF_URL,
        DOMAIN,
    )

    await setup_integration(hass, mock_config_entry)
    before = len(hass.data[DATA_EXTRA_MODULE_URL].urls)

    second = MockConfigEntry(
        domain=DOMAIN,
        title="Audiobookshelf (other)",
        unique_id="http://other::usr_other",
        data={CONF_URL: "http://other:13378", CONF_TOKEN: "exp_other"},
    )
    await setup_integration(hass, second)

    assert len(hass.data[DATA_EXTRA_MODULE_URL].urls) == before
    assert len(hass.data[DOMAIN]) == 2
