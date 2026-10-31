"""Sensor platform for Speidel Braumeister integration."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

from .const import (
    ACTUATOR_STATES,
    CONNECTION_STATES,
    PROCESS_STATES,
    DOMAIN,
    SENSOR_TYPES,
)
from .coordinator import SpeidelBraumeisterDataCoordinator
from .entity import SpeidelBraumeisterEntity


def _enum(value: Any, options: list[str]) -> str | None:
    """State of an enum sensor; values outside the options show as unknown."""
    value = getattr(value, "value", value)  # str enums from models.py
    return value if value in options else None


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
    def icon(self) -> str:
        """Return custom icon from brand directory for specific sensors."""
        # Use custom icons for specific sensors, fall back to MDI for others
        key = self.entity_description.key
        if key == "temperature":
            return f"/local/custom_components/{DOMAIN}/brand/icon.png"
        if key == "brew_name":
            return f"/local/custom_components/{DOMAIN}/brand/logo.png"
        # Use MDI icon from entity_description for other sensors
        return self.entity_description.icon

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        data = self.coordinator.data
        if not data:
            return None

        key = self.entity_description.key
        
        if key == "connection_status":
            return _enum(data.get("connection_status"), CONNECTION_STATES)
        elif key == "payment_required":
            return "yes" if data.get("payment_required", False) else "no"
        elif key == "temperature":
            temp = data.get("temperature")
            return round(temp, 1) if temp is not None else None
        elif key == "target_temperature":
            temp = data.get("target_temperature")
            return round(temp, 1) if temp is not None else None
        elif key == "pump_status":
            # Enum sensor: "on"/"off" are translated by Home Assistant, anything else is unknown
            pump = data.get("pump")
            return pump if pump in ACTUATOR_STATES else None
        elif key == "heating_status":
            heating = data.get("heating")
            return heating if heating in ACTUATOR_STATES else None
        elif key == "process_status":
            return _enum(data.get("process_status"), PROCESS_STATES)
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
            return data.get("current_phase") or None
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
        elif key == "device_recipes":
            # Number of recipe slots on the device; the recipes are attributes
            recipes = data.get("device_recipe_details")
            return len(recipes) if recipes else None
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
        
        elif key == "device_recipes":
            return {"recipes": data.get("device_recipe_details") or []}

        elif key == "process_status":
            return {
                "remaining_seconds": data.get("remaining_seconds"),
                "heating": data.get("heating"),
                "pump": data.get("pump"),
            }
        
        return None
