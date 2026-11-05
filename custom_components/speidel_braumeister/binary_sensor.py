"""Binary sensor platform for Speidel Braumeister integration."""

import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
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
from .connection_monitor import ConnectionMonitor


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
        sensor_type = (ConnectionWarningSensor if description.key == "connection_warning"
                       else SpeidelBraumeisterBinarySensor)
        entities.append(sensor_type(coordinator, description))

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
        if self.entity_description.key == "rtc_warning":
            return data.get("rtc_warning") if data else None
        if not data:
            return False

        key = self.entity_description.key

        if key == "alarm":
            # A decoded alarm (including explicit None after acknowledgement)
            # is authoritative even when the state code is unavailable.
            if "alarm" in data:
                return data.get("alarm") is not None
            # Fallback: check if current phase is an alarm state
            current_phase = data.get("current_phase", "")
            return current_phase in ALARM_PHASES

        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return which alarm is active and the raw device state."""
        data = self.coordinator.data
        if not data or self.entity_description.key != "alarm":
            return None
        return {
            "alarm_type": data.get("alarm"),
            "state_code": data.get("state_code"),
        }


class ConnectionWarningSensor(SpeidelBraumeisterBinarySensor):
    """Remain available during update failures and evaluate without network I/O."""

    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator, description)
        self._monitor = ConnectionMonitor()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._observe()
        self.async_on_remove(async_track_time_interval(
            self.hass, self._tick, timedelta(seconds=5)
        ))

    def _observe(self) -> None:
        data = self.coordinator.data if self.coordinator.last_update_success else None
        self._monitor.observe(data or {}, time.monotonic())

    @callback
    def _handle_coordinator_update(self) -> None:
        self._observe()
        super()._handle_coordinator_update()

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool | None:
        return self._monitor.snapshot(time.monotonic())["warning"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self._monitor.snapshot(time.monotonic())
        result.pop("warning")
        return result
