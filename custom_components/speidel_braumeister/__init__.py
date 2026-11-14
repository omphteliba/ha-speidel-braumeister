"""The Speidel Braumeister integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import SpeidelAuthError, SpeidelBraumeisterAPI
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_MACHINE_UUID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    CONF_LOCAL_ONLY,
    LOCAL_SCAN_INTERVAL,
)
from .coordinator import SpeidelBraumeisterDataCoordinator
from .web_auth import SpeidelWebAuth
from .request_policy import PollingError, RequestPolicy
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Speidel Braumeister integration."""
    hass.data.setdefault(DOMAIN, {})
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Speidel Braumeister from a config entry."""
    _LOGGER.info("Setting up Speidel Braumeister integration")

    local_only = entry.options.get(CONF_LOCAL_ONLY, entry.data.get(CONF_LOCAL_ONLY, False))
    machine_uuid = entry.data[CONF_MACHINE_UUID]
    # The options flow stores a changed interval in entry.options
    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    _LOGGER.info("Machine UUID: %s, Scan interval: %s", machine_uuid, scan_interval)

    api = web_auth = None
    if local_only:
        scan_interval = LOCAL_SCAN_INTERVAL
    else:
        username = entry.data[CONF_USERNAME]
        password = entry.data[CONF_PASSWORD]
        # Create API client for cloud API
        session = async_get_clientsession(hass)
        api = SpeidelBraumeisterAPI(username, password, session)
        # Keep a cooldown across HA setup retries, and share it across cloud clients.
        policy_key = f"{entry.entry_id}_request_policy"
        api.request_policy = hass.data[DOMAIN].setdefault(policy_key, RequestPolicy())

        # Authenticate with cloud API
        try:
            await api.authenticate()
            _LOGGER.info("Cloud API authentication successful, user_id: %s", api.user_id)

            # Log subscription info
            if api.subscription_id:
                _LOGGER.info("Subscription found - ID: %s, End: %s", api.subscription_id, api.subscription_end)
            else:
                _LOGGER.info("No subscription found - using XHR polling for real-time data")
        except PollingError as err:
            raise ConfigEntryNotReady(str(err)) from err
        except SpeidelAuthError as err:
            # Home Assistant asks the user for the new password (reauthentication flow)
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:
            _LOGGER.error("Failed to authenticate with cloud API: %s", err)
            return False

        # Web authentication for XHR polling (PRIMARY data source)
        web_auth = SpeidelWebAuth(username, password, session)
        web_auth.request_policy = api.request_policy
        try:
            web_login_success = await web_auth.login()
        except PollingError as err:
            raise ConfigEntryNotReady(str(err)) from err

        if web_login_success:
            _LOGGER.info("Web interface login successful - XHR polling available")
            _LOGGER.info("Discovered machines: %s", web_auth.machines)

            # If user didn't specify a valid UUID, use the first discovered machine
            if not machine_uuid or machine_uuid == "":
                if web_auth.machines:
                    machine_uuid = web_auth.machines[0]['full_id']
                    _LOGGER.info("Using discovered machine: %s", machine_uuid)
        else:
            _LOGGER.warning("Web interface login failed - XHR polling not available")

    # Create coordinator
    coordinator = SpeidelBraumeisterDataCoordinator(
        hass,
        api,
        machine_uuid,
        scan_interval,
        local_only=local_only,
    )

    # IMPORTANT: Set web_auth BEFORE first data refresh
    # This is needed for XHR polling to work
    coordinator.web_auth = web_auth

    # Fetch initial data - NOW web_auth is available
    await coordinator.async_config_entry_first_refresh()

    # Diagnostic: log what the documented cloud timeseries API returns
    if not local_only and _LOGGER.isEnabledFor(logging.DEBUG):
        entry.async_create_background_task(
            hass, api.probe_timeseries(machine_uuid), "speidel_timeseries_probe"
        )

    entry.runtime_data = coordinator

    async def refresh_after_action(event):
        if local_only and str(event.data.get("device_id", "")).lower() == machine_uuid.split(".")[0].lower():
            await coordinator.async_request_refresh()

    entry.async_on_unload(hass.bus.async_listen("braumeister_menu_updated", refresh_after_action))

    # No real-time push client: the former MQTT client was based on a guessed
    # protocol and never received data. See docs/NEW_DEVICES.md for how owners of
    # newer models can record the real WebSocket traffic.

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info("Speidel Braumeister integration setup complete for machine %s", machine_uuid)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: SpeidelBraumeisterDataCoordinator = entry.runtime_data

    # Close web auth
    if hasattr(coordinator, 'web_auth') and coordinator.web_auth:
        await coordinator.web_auth.close()

    if coordinator.api is not None:
        await coordinator.api.close()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options for a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
