"""Binary sensor platform for Speidel Braumeister integration."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .const import (
    DOMAIN,
    BINARY_SENSOR_TYPES,
)
from .coordinator import SpeidelBraumeisterDataCoordinator
from .entity import SpeidelBraumeisterEntity


# Alarm states that trigger the alarm binary sensor
ALARM_PHASES = [
    "Einmaischen Temp. erreicht",  # Mash-in temperature reached
    "Rastende erreicht",  # Rest end reached
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Speidel Braumeister binary sensors from a config entry."""
    coordinator: SpeidelBraumeisterDataCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for description in BINARY_SENSOR_TYPES:
        entities.append(SpeidelBraumeisterBinarySensor(coordinator, description))

    async_add_entities(entities)


class SpeidelBraumeisterBinarySensor(SpeidelBraumeisterEntity, BinarySensorEntity):
    """Binary sensor for Speidel Braumeister."""

    def __init__(
        self,
        coordinator: SpeidelBraumeisterDataCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        data = self.coordinator.data
        if not data:
            return False

        key = self.entity_description.key

        if key == "alarm":
            if data.get("connection_status") != "online":
                return None
            if isinstance(data.get("alarm"), bool):
                return data["alarm"]
            # Legacy/cloud fallback; unknown fast alarm flags remain unknown.
            if "alarm" in data and data["alarm"] is None:
                return None
            # Check if current phase is an alarm state
            current_phase = data.get("current_phase", "")
            return current_phase in ALARM_PHASES

        return False
