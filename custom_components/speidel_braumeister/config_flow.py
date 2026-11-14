"""Config flow for Speidel Braumeister integration."""

import logging
from collections.abc import Mapping
from typing import Any, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .api import SpeidelApiError, SpeidelAuthError, SpeidelBraumeisterAPI, SpeidelConnectionError
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_MACHINE_UUID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    CONF_LOCAL_ONLY,
)

_LOGGER = logging.getLogger(__name__)

# Schema for authentication
STEP_AUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_LOCAL_ONLY, default=False): bool,
        vol.Optional(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
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
            if user_input.get(CONF_LOCAL_ONLY):
                return await self.async_step_local()
            username = user_input.get(CONF_USERNAME, "")
            password = user_input.get(CONF_PASSWORD, "")

            try:
                auth_info = await validate_auth(self.hass, username, password)
            except SpeidelAuthError as err:
                _LOGGER.error("Auth error: %s", err)
                errors["base"] = "invalid_auth"
            except (SpeidelApiError, SpeidelConnectionError) as err:
                _LOGGER.error("API error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
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

    async def async_step_local(self, user_input=None) -> FlowResult:
        """Configure a local device without creating or authenticating a cloud client."""
        errors = {}
        if user_input is not None:
            machine = user_input[CONF_MACHINE_UUID].strip()
            if not machine:
                errors["base"] = "invalid_machine"
            else:
                self._async_abort_entries_match({CONF_MACHINE_UUID: machine})
                await self.async_set_unique_id(machine.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input.get("name", "Braumeister"), data={
                    CONF_MACHINE_UUID: machine, CONF_LOCAL_ONLY: True,
                })
        return self.async_show_form(step_id="local", errors=errors, data_schema=vol.Schema({
            vol.Required("name", default="Braumeister"): str,
            vol.Required(CONF_MACHINE_UUID): str,
        }))

    async def async_step_machine(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the machine UUID entry step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            machine_uuid = user_input[CONF_MACHINE_UUID].strip()
            name = user_input.get("name", "Braumeister")
            # Entries created before unique IDs existed are matched by their data
            self._async_abort_entries_match({CONF_MACHINE_UUID: machine_uuid})
            await self.async_set_unique_id(machine_uuid.lower())
            self._abort_if_unique_id_configured()
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

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """The stored password was rejected: ask for a new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Check the new password and reload the entry with it."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_auth(self.hass, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            except SpeidelAuthError:
                errors["base"] = "invalid_auth"
            except (SpeidelApiError, SpeidelConnectionError):
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during reauthentication")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
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
        errors = {}
        if user_input is not None:
            if not user_input.get(CONF_LOCAL_ONLY, self._config_entry.data.get(CONF_LOCAL_ONLY, False)) and not (
                self._config_entry.data.get(CONF_USERNAME) and self._config_entry.data.get(CONF_PASSWORD)
            ):
                errors["base"] = "cloud_credentials_required"
            else:
                return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_LOCAL_ONLY, default=self._config_entry.options.get(
                    CONF_LOCAL_ONLY, self._config_entry.data.get(CONF_LOCAL_ONLY, False))): bool,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self._config_entry.options.get(
                        CONF_SCAN_INTERVAL,
                        self._config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )
