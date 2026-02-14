"""Sensor platform for Speidel Braumeister integration."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

from .const import (
    DOMAIN,
    SENSOR_TYPES,
)
from .coordinator import SpeidelBraumeisterDataCoordinator
from .entity import SpeidelBraumeisterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Speidel Braumeister sensors from a config entry."""
    coordinator: SpeidelBraumeisterDataCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for description in SENSOR_TYPES:
        entities.append(SpeidelBraumeisterSensor(coordinator, description))

    async_add_entities(entities)


class SpeidelBraumeisterSensor(SpeidelBraumeisterEntity, SensorEntity):
    """Sensor for Speidel Braumeister."""

    def __init__(
        self,
        coordinator: SpeidelBraumeisterDataCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        data = self.coordinator.data
        if not data:
            return None

        key = self.entity_description.key
        
        if key == "connection_status":
            return data.get("connection_status", "unknown")
        elif key == "payment_required":
            # Return Yes if payment required, No otherwise
            return "Yes" if data.get("payment_required", False) else "No"
        elif key == "temperature":
            temp = data.get("temperature")
            return round(temp, 1) if temp is not None else None
        elif key == "target_temperature":
            temp = data.get("target_temperature")
            return round(temp, 1) if temp is not None else None
        elif key == "pump_status":
            pump = data.get("pump", "unknown")
            # Translate to German for consistency with web interface
            if pump == "on":
                return "Ein"
            elif pump == "off":
                return "Aus"
            return pump
        elif key == "heating_status":
            heating = data.get("heating", "unknown")
            # Translate to German for consistency with web interface
            if heating == "on":
                return "Ein"
            elif heating == "off":
                return "Aus"
            return heating
        elif key == "process_status":
            return data.get("process_status", "unknown")
        elif key == "current_phase":
            # Use current_step if available, otherwise fall back to current_phase
            step = data.get("current_step")
            if step:
                # Extract just the step name (e.g., "Einmaischen" from "Stone IPA – Einmaischen")
                if "–" in step:
                    return step.split("–")[-1].strip()
                elif "-" in step:
                    return step.split("-")[-1].strip()
                return step
            phase = data.get("current_phase")
            return str(phase).upper() if phase else "UNKNOWN"
        elif key == "remaining_time":
            return data.get("remaining_time")
        elif key == "brew_name":
            return data.get("brew_name")
        elif key == "device_type":
            return data.get("device_type")
        elif key == "device_mode":
            mode = data.get("device_mode")
            # Translate German mode to English if needed
            if mode == "wartet":
                return "waiting"
            return mode
        elif key == "current_step":
            return data.get("current_step")
        elif key == "progress":
            return data.get("progress")
        elif key == "last_online":
            return data.get("last_online")

        return data.get(key)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes for the sensor."""
        data = self.coordinator.data
        if not data:
            return None
        
        key = self.entity_description.key
        
        if key == "brew_name":
            # Add recipe matching attributes
            attrs = {
                "recipe_slot": data.get("recipe_slot"),
                "recipe_matched": data.get("recipe_matched", False),
            }
            
            if data.get("recipe_matched"):
                attrs["account_recipe_id"] = data.get("recipe_account_id")
                attrs["recipe_date"] = data.get("recipe_date")
                attrs["recipe_style"] = data.get("recipe_style")
            
            return attrs
        
        elif key == "process_status":
            return {
                "remaining_seconds": data.get("remaining_seconds"),
                "heating": data.get("heating"),
                "pump": data.get("pump"),
            }
        
        return None
