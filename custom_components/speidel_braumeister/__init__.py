"""The Speidel Braumeister integration."""

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import SpeidelBraumeisterAPI
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_MACHINE_UUID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import SpeidelBraumeisterDataCoordinator
from .mqtt_client import SpeidelMQTTClient
from .web_auth import SpeidelWebAuth

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Speidel Braumeister integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Speidel Braumeister from a config entry."""
    _LOGGER.info("Setting up Speidel Braumeister integration")
    
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    machine_uuid = entry.data[CONF_MACHINE_UUID]
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    
    _LOGGER.info("Machine UUID: %s, Scan interval: %s", machine_uuid, scan_interval)

    # Create API client for cloud API
    session = async_get_clientsession(hass)
    api = SpeidelBraumeisterAPI(username, password, session)

    # Authenticate with cloud API
    try:
        auth_result = await api.authenticate()
        _LOGGER.info("Cloud API authentication successful, user_id: %s", api.user_id)
        
        # Log subscription info
        if api.subscription_id:
            _LOGGER.info("Subscription found - ID: %s, End: %s", api.subscription_id, api.subscription_end)
        else:
            _LOGGER.info("No subscription found - using XHR polling for real-time data")
    except Exception as err:
        _LOGGER.error("Failed to authenticate with cloud API: %s", err)
        return False

    # Web authentication for XHR polling (PRIMARY data source)
    web_auth = SpeidelWebAuth(username, password, session)
    web_login_success = await web_auth.login()
    
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
    )
    
    # IMPORTANT: Set web_auth BEFORE first data refresh
    # This is needed for XHR polling to work
    coordinator.web_auth = web_auth

    # Fetch initial data - NOW web_auth is available
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in hass.data
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Start MQTT client for real-time data if we have authentication
    mqtt_client = None
    mqtt_task = None
    
    session_value = web_auth.session_value if web_login_success else None
    user_id = web_auth.user_id if web_login_success else api.user_id
    
    if user_id:
        # Extract machine ID from UUID (could be "323" or "0004A30B003D70F4.323")
        machine_id = machine_uuid
        if "." in machine_uuid:
            machine_id = machine_uuid.split(".")[-1]
        
        @callback
        def on_mqtt_data(data: dict):
            """Handle incoming MQTT data."""
            _LOGGER.debug("Received MQTT data: %s", data)
            # Update coordinator with new data
            coordinator.update_from_mqtt(data)
        
        mqtt_client = SpeidelMQTTClient(
            token=api.token,
            user_id=user_id,
            machine_id=machine_id,
            on_data_callback=on_mqtt_data,
            session_value=session_value,
        )
        
        # Store MQTT client reference
        coordinator.mqtt_client = mqtt_client
        
        # Start MQTT in background task
        async def start_mqtt():
            """Start MQTT client."""
            try:
                await mqtt_client.start()
            except asyncio.CancelledError:
                _LOGGER.debug("MQTT task cancelled")
            except Exception as err:
                _LOGGER.error("MQTT error: %s", err)
        
        mqtt_task = hass.loop.create_task(start_mqtt())
        _LOGGER.info("Started MQTT client for real-time data")
    
    # Store task for cleanup
    coordinator._mqtt_task = mqtt_task

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info("Speidel Braumeister integration setup complete for machine %s", machine_uuid)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: SpeidelBraumeisterDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Stop MQTT client if running
    if hasattr(coordinator, 'mqtt_client') and coordinator.mqtt_client:
        await coordinator.mqtt_client.stop()
    if hasattr(coordinator, '_mqtt_task') and coordinator._mqtt_task:
        coordinator._mqtt_task.cancel()
        try:
            await coordinator._mqtt_task
        except asyncio.CancelledError:
            pass
    
    # Close web auth
    if hasattr(coordinator, 'web_auth') and coordinator.web_auth:
        await coordinator.web_auth.close()
    
    await coordinator.api.close()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options for a config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
