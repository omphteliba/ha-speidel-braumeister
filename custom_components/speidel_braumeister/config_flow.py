from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

class SpeidelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Speidel Braumeister."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_USERNAME], data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=config_entries.Schema(
                {
                    CONF_USERNAME: config_entries.const.STRING,
                    CONF_PASSWORD: config_entries.const.STRING,
                }
            ),
            errors=errors,
        )