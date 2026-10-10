"""Config flow for Sapir Parking."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from . import create_client
from .api import (
    CloudflareChallengeError,
    SapirParkingAuthError,
    SapirParkingConnectionError,
    SapirParkingError,
)
from .const import (
    AUTH_METHOD_COOKIE,
    AUTH_METHOD_LOGIN,
    CONF_AUTH_METHOD,
    CONF_FLARESOLVERR_URL,
    CONF_LICENSE,
    CONF_PHONE,
    CONF_SESSION_COOKIE,
    DOMAIN,
    NAME,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

COOKIE_FIELDS = {vol.Required(CONF_SESSION_COOKIE): str}
LOGIN_FIELDS = {vol.Required(CONF_PHONE): str, vol.Required(CONF_LICENSE): str}
FLARESOLVERR_FIELD = {vol.Optional(CONF_FLARESOLVERR_URL): str}


async def _async_validate(
    hass: HomeAssistant, data: dict[str, Any], flaresolverr_url: str | None
) -> dict[str, str]:
    """Validate the settings, returning a dict of errors (empty if valid)."""
    if flaresolverr_url:
        try:
            cv.url(flaresolverr_url)
        except vol.Invalid:
            return {CONF_FLARESOLVERR_URL: "invalid_url"}

    client = create_client(hass, data, flaresolverr_url)
    try:
        await client.async_check_flaresolverr()
    except SapirParkingConnectionError as err:
        _LOGGER.warning("%s", err)
        return {CONF_FLARESOLVERR_URL: "flaresolverr_unreachable"}

    try:
        await client.async_get_parking_status(dt_util.now().date())
    except SapirParkingAuthError:
        return {"base": "invalid_auth"}
    except CloudflareChallengeError:
        return {"base": "cloudflare_challenge"}
    except SapirParkingConnectionError:
        return {"base": "cannot_connect"}
    except SapirParkingError:
        _LOGGER.exception("Unexpected response while validating credentials")
        return {"base": "unknown"}
    return {}


class SapirParkingFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for Sapir Parking."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return SapirParkingOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick how to authenticate."""
        return self.async_show_menu(
            step_id="user", menu_options=[AUTH_METHOD_LOGIN, AUTH_METHOD_COOKIE]
        )

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Authenticate with phone and license number."""
        return await self._async_step_auth(
            AUTH_METHOD_LOGIN, {**LOGIN_FIELDS, **FLARESOLVERR_FIELD}, user_input
        )

    async def async_step_cookie(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Authenticate with a session cookie."""
        return await self._async_step_auth(
            AUTH_METHOD_COOKIE, {**COOKIE_FIELDS, **FLARESOLVERR_FIELD}, user_input
        )

    async def _async_step_auth(
        self,
        auth_method: str,
        fields: dict,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**user_input, CONF_AUTH_METHOD: auth_method}
            errors = await _async_validate(
                self.hass, data, user_input.get(CONF_FLARESOLVERR_URL)
            )
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=NAME, data=data)

        return self.async_show_form(
            step_id=auth_method,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the session expired or login failed."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials."""
        entry = self._get_reauth_entry()
        auth_method = entry.data.get(CONF_AUTH_METHOD, AUTH_METHOD_COOKIE)
        fields = LOGIN_FIELDS if auth_method == AUTH_METHOD_LOGIN else COOKIE_FIELDS
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input, CONF_AUTH_METHOD: auth_method}
            flaresolverr_url = entry.options.get(
                CONF_FLARESOLVERR_URL, entry.data.get(CONF_FLARESOLVERR_URL)
            )
            errors = await _async_validate(self.hass, data, flaresolverr_url)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(fields),
            errors=errors,
        )


class SapirParkingOptionsFlow(OptionsFlow):
    """Options flow for changing the FlareSolverr URL."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            url = (user_input.get(CONF_FLARESOLVERR_URL) or "").strip()
            if url:
                errors = await _async_validate(self.hass, dict(entry.data), url)
            if not errors:
                return self.async_create_entry(data={CONF_FLARESOLVERR_URL: url})

        current = entry.options.get(
            CONF_FLARESOLVERR_URL, entry.data.get(CONF_FLARESOLVERR_URL, "")
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(FLARESOLVERR_FIELD),
                user_input or {CONF_FLARESOLVERR_URL: current},
            ),
            errors=errors,
        )
