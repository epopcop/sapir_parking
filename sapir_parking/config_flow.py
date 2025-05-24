"""Config flow for Sapir Parking."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import SapirParkingApiClient
from .const import CONF_LICENSE, CONF_PHONE, DOMAIN, NAME

CONFIG_SCHMA = vol.Schema(
    {
        vol.Required(CONF_PHONE): str,
        vol.Required(CONF_LICENSE): str,
    }
)


class SapirParkingFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Sapir Parking."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize."""
        self._errors = {}

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Uncomment the next 2 lines if only a single instance of the integration is allowed:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            valid = await self._test_credentials(
                user_input[CONF_PHONE], user_input[CONF_LICENSE]
            )
            if valid:
                return self.async_create_entry(title=NAME, data=user_input)

            self._errors["base"] = "Couldn't login with the provided credentials"

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit data."""
        return self.async_show_form(
            step_id="user",
            data_schema=CONFIG_SCHMA,
            errors=self._errors,
        )

    async def _test_credentials(self, phone, license):
        """Return true if credentials is valid."""
        try:
            session = async_create_clientsession(self.hass)
            client = SapirParkingApiClient(session)
            await client.async_login(phone, license)
        except Exception:  # pylint: disable=broad-except
            pass
        else:
            return True
        return False
