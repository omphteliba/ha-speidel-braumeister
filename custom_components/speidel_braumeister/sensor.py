"""
Representation of a Speidel Braumeister sensor.
"""

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, MANUFACTURER, NAME, SENSOR_TYPES


class SpeidelSensor(SensorEntity):
    """Representation of a Speidel Braumeister sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator, description: SensorEntityDescription) -> None:
        """Initialize the sensor."""
        super().__init__()
        self.coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"

    @property
    def device_info(self) -> dict:
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