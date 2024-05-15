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
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            # Validate credentials - replace with your API validation
            # You can use requests.get to check if the credentials are valid
            try:
                response = await self.hass.async_add_executor_job(
                    requests.get,
                    "https://api.cloud.myspeidel.com/v1.0/braumeister/status", 
                    auth=(username, password),
                )
                response.raise_for_status()
                
                return self.async_create_entry(
                    title=username, data=user_input
                )

            except requests.exceptions.RequestException as error:
                _LOGGER.error("Invalid credentials: %s", error)
                errors["base"] = "invalid_auth" 

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