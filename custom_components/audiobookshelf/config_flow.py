"""Config flow for Audiobookshelf."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AudiobookshelfAuthError,
    AudiobookshelfClient,
    AudiobookshelfConnectionError,
    AudiobookshelfError,
)
from .const import (
    CONF_ACTIVE_WINDOW,
    CONF_LIBRARIES,
    CONF_MAX_ITEMS,
    CONF_PUBLIC_URL,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    CONF_VERIFY_SSL,
    DEFAULT_ACTIVE_WINDOW,
    DEFAULT_MAX_ITEMS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(CONF_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_VERIFY_SSL, default=True): BooleanSelector(),
    }
)


def _normalise_url(url: str) -> str:
    """Add a scheme if the user left it out and strip any trailing slash."""
    url = url.strip().rstrip("/")
    if not url:
        return url
    if "://" not in url:
        url = f"http://{url}"
    return url


class AudiobookshelfConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Audiobookshelf config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._reauth_entry: ConfigEntry | None = None

    async def _async_validate(
        self, url: str, token: str, verify_ssl: bool
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Try to talk to the server, returning (user, error_key)."""
        session = async_get_clientsession(self.hass, verify_ssl=verify_ssl)
        client = AudiobookshelfClient(session, url, token)
        try:
            user = await client.async_validate()
        except AudiobookshelfAuthError:
            return None, "invalid_auth"
        except AudiobookshelfConnectionError:
            return None, "cannot_connect"
        except AudiobookshelfError:
            return None, "unknown"
        except Exception:
            _LOGGER.exception("Unexpected error validating Audiobookshelf")
            return None, "unknown"
        return user, None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = _normalise_url(user_input[CONF_URL])
            token = user_input[CONF_TOKEN].strip()
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

            if not urlparse(url).netloc:
                errors["base"] = "invalid_url"
            else:
                user, error = await self._async_validate(url, token, verify_ssl)
                if error:
                    errors["base"] = error
                else:
                    assert user is not None
                    await self.async_set_unique_id(f"{url}::{user.get('id')}")
                    self._abort_if_unique_id_configured(
                        updates={CONF_URL: url, CONF_TOKEN: token}
                    )
                    return self.async_create_entry(
                        title=f"Audiobookshelf ({user.get('username') or urlparse(url).netloc})",
                        data={
                            CONF_URL: url,
                            CONF_TOKEN: token,
                            CONF_VERIFY_SSL: verify_ssl,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a token that stopped working."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh API token."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        assert entry is not None

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            _, error = await self._async_validate(
                entry.data[CONF_URL], token, entry.data.get(CONF_VERIFY_SSL, True)
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, CONF_TOKEN: token}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the server address, token or SSL setting of an entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            url = _normalise_url(user_input[CONF_URL])
            # A blank token keeps the current one, so moving the server to a
            # new address does not mean digging the token out again.
            token = (user_input.get(CONF_TOKEN) or "").strip() or entry.data[CONF_TOKEN]
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

            if not urlparse(url).netloc:
                errors["base"] = "invalid_url"
            else:
                user, error = await self._async_validate(url, token, verify_ssl)
                if error:
                    errors["base"] = error
                else:
                    assert user is not None
                    # The entry tracks one user's progress; pointing it at a
                    # different account would silently swap whose books it shows.
                    if str(entry.unique_id).rsplit("::", 1)[-1] != str(user.get("id")):
                        errors["base"] = "wrong_account"
                    else:
                        unique_id = f"{url}::{user.get('id')}"
                        if any(
                            other.unique_id == unique_id
                            for other in self._async_current_entries()
                            if other.entry_id != entry.entry_id
                        ):
                            return self.async_abort(reason="already_configured")
                        return self.async_update_reload_and_abort(
                            entry,
                            unique_id=unique_id,
                            data={
                                **entry.data,
                                CONF_URL: url,
                                CONF_TOKEN: token,
                                CONF_VERIFY_SSL: verify_ssl,
                            },
                        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.URL)
                        ),
                        vol.Optional(CONF_TOKEN): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.PASSWORD)
                        ),
                        vol.Optional(CONF_VERIFY_SSL, default=True): BooleanSelector(),
                    }
                ),
                {
                    CONF_URL: entry.data[CONF_URL],
                    CONF_VERIFY_SSL: entry.data.get(CONF_VERIFY_SSL, True),
                    **{
                        key: value
                        for key, value in (user_input or {}).items()
                        if key != CONF_TOKEN
                    },
                },
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AudiobookshelfOptionsFlow:
        """Return the options flow."""
        return AudiobookshelfOptionsFlow()


class AudiobookshelfOptionsFlow(OptionsFlow):
    """Handle Audiobookshelf options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            options = dict(user_input)
            options[CONF_SCAN_INTERVAL] = int(options[CONF_SCAN_INTERVAL])
            options[CONF_MAX_ITEMS] = int(options[CONF_MAX_ITEMS])
            options[CONF_ACTIVE_WINDOW] = int(options[CONF_ACTIVE_WINDOW])
            public_url = (options.get(CONF_PUBLIC_URL) or "").strip()
            options[CONF_PUBLIC_URL] = _normalise_url(public_url) if public_url else ""
            return self.async_create_entry(data=options)

        library_options = await self._async_library_options()
        current = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MAX_ITEMS, default=current.get(CONF_MAX_ITEMS, DEFAULT_MAX_ITEMS)
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=50, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_ACTIVE_WINDOW,
                    default=current.get(CONF_ACTIVE_WINDOW, DEFAULT_ACTIVE_WINDOW),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=60,
                        max=3600,
                        step=30,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    CONF_LIBRARIES, default=list(current.get(CONF_LIBRARIES) or [])
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=library_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_PUBLIC_URL, default=current.get(CONF_PUBLIC_URL, "")
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def _async_library_options(self) -> list[SelectOptionDict]:
        """Offer the libraries the server knows about, if it is reachable."""
        entry = self.config_entry
        session = async_get_clientsession(
            self.hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True)
        )
        client = AudiobookshelfClient(session, entry.data[CONF_URL], entry.data[CONF_TOKEN])
        try:
            libraries = await client.async_get_libraries()
        except AudiobookshelfError as err:
            _LOGGER.debug("Could not list libraries for the options flow: %s", err)
            return []
        return [
            SelectOptionDict(
                value=str(library["id"]),
                label=f"{library.get('name')} ({library.get('mediaType', 'book')})",
            )
            for library in libraries
            if library.get("id")
        ]
