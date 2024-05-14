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

from .config_flow import SpeidelConfigFlow  # Import your config_flow module

from .const import (
    DOMAIN,
    MANUFACTURER,
    NAME,
    SCAN_INTERVAL,
    SENSOR_TYPES,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> bool:
    """Set up the Speidel Braumeister integration."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = SpeidelDataCoordinator(hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.data:
        raise ConfigEntryNotReady("Failed to fetch data from Speidel API.")

    async_add_entities(
        SpeidelSensor(coordinator, description) for description in SENSOR_TYPES
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the Speidel Braumeister integration."""
    if hass.data.get(DOMAIN):
        del hass.data[DOMAIN][entry.entry_id]

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


class SpeidelSensor(SensorEntity):
    """Representation of a Speidel Braumeister sensor."""

    def __init__(self, coordinator: SpeidelDataCoordinator, description: SensorEntityDescription) -> None:
        """Initialize the sensor."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.username)},
            "name": NAME,
            "manufacturer": MANUFACTURER,
        }

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        data = self.coordinator.data
        if data:
            if self.entity_description.key == "current_temperature":
                return f"{data['currentTemperature']:.1f}"
            elif self.entity_description.key == "target_temperature":
                return f"{data['targetTemperature']:.1f}"
            elif self.entity_description.key == "current_phase":
                return data['currentPhase'].upper()
            elif self.entity_description.key == "current_time":
                return data['currentTime']
            elif self.entity_description.key == "remaining_time":
                return data['remainingTime']
            else:
                return data[self.entity_description.key]
        else:
            return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    async def async_update(self) -> None:
        """Update the sensor state."""
        await self.coordinator.async_request_refresh()