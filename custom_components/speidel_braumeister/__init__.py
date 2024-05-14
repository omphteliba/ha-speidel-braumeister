"""
Custom integration for Home Assistant to integrate with the Speidel Braumeister.

This integration retrieves data from the Speidel API and exposes it as entities in Home Assistant.
"""

import logging
from datetime import timedelta

import requests
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

from .const import (
    DOMAIN,
    MANUFACTURER,
    NAME,
    SCAN_INTERVAL,
    SENSOR_TYPES,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Speidel Braumeister integration."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    coordinator = SpeidelDataCoordinator(hass, username, password)
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data:
        raise ConfigEntryNotReady("Failed to fetch data from Speidel API.")

    async_add_entities(
        SpeidelSensor(coordinator, description) for description in SENSOR_TYPES
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the Speidel Braumeister integration."""
    return True


class SpeidelDataCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Speidel API."""

    def __init__(self, hass: HomeAssistant, username: str, password: str) -> None:
        """Initialize the data coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.username = username
        self.password = password

    async def _async_update_data(self) -> dict:
        """Fetch data from the Speidel API."""
        try:
            response = requests.get(
                "https://api.cloud.myspeidel.com/v1.0/braumeister/status",
                auth=(self.username, self.password),
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as error:
            raise UpdateFailed(f"Error fetching data from Speidel API: {error}") from error