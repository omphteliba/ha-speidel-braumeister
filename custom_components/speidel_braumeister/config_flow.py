"""Config flow for Speidel Braumeister integration."""

import logging
from typing import Any, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .api import SpeidelBraumeisterAPI, SpeidelAuthError, SpeidelApiError
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_MACHINE_UUID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Schema for authentication
STEP_AUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

# Schema for machine UUID
STEP_MACHINE_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("name", default="Braumeister"): str,
        vol.Required(CONF_MACHINE_UUID): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=3600)
        ),
    }
)


async def validate_auth(hass: HomeAssistant, username: str, password: str) -> dict[str, Any]:
    """Validate credentials."""
    api = SpeidelBraumeisterAPI(username, password)
    try:
        await api.authenticate()
        return {
            "success": True,
            "user_id": api.user_id,
        }
    finally:
        await api.close()


class SpeidelBraumeisterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Speidel Braumeister."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._auth_info: Optional[dict] = None

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step (authentication)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            try:
                auth_info = await validate_auth(self.hass, username, password)
            except SpeidelAuthError as err:
                _LOGGER.error("Auth error: %s", err)
                errors["base"] = "invalid_auth"
            except SpeidelApiError as err:
                _LOGGER.error("API error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during authentication")
                errors["base"] = "unknown"
            else:
                self._username = username
                self._password = password
                self._auth_info = auth_info
                
                # Ask for machine UUID
                return await self.async_step_machine()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_AUTH_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_machine(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the machine UUID entry step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            machine_uuid = user_input[CONF_MACHINE_UUID]
            name = user_input.get("name", "Braumeister")
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            return self.async_create_entry(
                title=name,
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_MACHINE_UUID: machine_uuid,
                    CONF_SCAN_INTERVAL: scan_interval,
                },
            )

        return self.async_show_form(
            step_id="machine",
            data_schema=STEP_MACHINE_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "help_text": "Enter your Braumeister's Machine UUID. You can find this in the My Speidel app or web interface."
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
) -> "SpeidelBraumeisterOptionsFlow":
        """Get the options flow for this handler."""
        return SpeidelBraumeisterOptionsFlow(config_entry)


class SpeidelBraumeisterOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Speidel Braumeister."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle options flow initialization."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
