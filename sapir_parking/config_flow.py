"""Config flow for Sapir Parking."""

from datetime import datetime

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import SapirParkingApiClient
from .const import CONF_SESSION_COOKIE, DOMAIN, PLATFORMS


class SapirParkingFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Sapir Parking."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Uncomment the next 2 lines if only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            valid = await self._test_credentials(user_input[CONF_SESSION_COOKIE])
            if valid:
                return self.async_create_entry(title="sapir", data=user_input)

            self._errors["base"] = "Couldn't fetch available parking spots"

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SapirParkingOptionsFlowHandler(config_entry)

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_SESSION_COOKIE): str}),
            errors=self._errors,
        )

    async def _test_credentials(self, session_cookie):
        """Return true if credentials is valid."""
        try:
            session = async_create_clientsession(self.hass)
            client = SapirParkingApiClient(session, session_cookie)
            await client.async_get_available_spots(datetime.today())
        except Exception:  # pylint: disable=broad-except
            pass
        else:
            return True
        return False


class SapirParkingOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for Sapir Parking."""

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(x, default=self.options.get(x, True)): bool
                    for x in sorted(PLATFORMS)
                }
            ),
        )

    async def _update_options(self):
        """Update config entry options."""
        return self.async_create_entry(
            title=self.config_entry.data.get(CONF_SESSION_COOKIE), data=self.options
        )
