"""Switch platform for Speidel Braumeister integration."""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.switch import SwitchEntity

from .const import (
    DOMAIN,
    SWITCH_PUMP,
    SWITCH_HEATING,
    SWITCH_TYPES,
)
from .coordinator import SpeidelBraumeisterDataCoordinator
from .entity import SpeidelBraumeisterEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Speidel Braumeister switches from a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: SpeidelBraumeisterDataCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SpeidelBraumeisterPumpSwitch(coordinator, SWITCH_PUMP, SWITCH_TYPES[SWITCH_PUMP]),
        SpeidelBraumeisterHeatingSwitch(coordinator, SWITCH_HEATING, SWITCH_TYPES[SWITCH_HEATING]),
    ]

    async_add_entities(entities)


class SpeidelBraumeisterPumpSwitch(SpeidelBraumeisterEntity, SwitchEntity):
    """Switch for controlling the pump."""

    _attr_translation_key = "pump"

    def __init__(
        self,
        coordinator: SpeidelBraumeisterDataCoordinator,
        switch_type: str,
        switch_info: dict[str, Any],
    ) -> None:
        """Initialize the pump switch."""
        super().__init__(coordinator, switch_type)
        self._switch_type = switch_type
        self._attr_icon = switch_info.get("icon")

    @property
    def is_on(self) -> bool:
        """Return True if pump is on."""
        return self.machine_data.get("pump") == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the pump on."""
        try:
            await self.coordinator.async_set_pump(True)
            await self.coordinator.async_request_refresh()
        except NotImplementedError as err:
            _LOGGER.warning("Pump control not available: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Failed to turn on pump: %s", err)
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the pump off."""
        try:
            await self.coordinator.async_set_pump(False)
            await self.coordinator.async_request_refresh()
        except NotImplementedError as err:
            _LOGGER.warning("Pump control not available: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Failed to turn off pump: %s", err)
            raise

    @property
    def available(self) -> bool:
        """Return if entity is available.

        The switch is only available if control is supported.
        """
        # For now, switches are unavailable as the API doesn't support control
        return False


class SpeidelBraumeisterHeatingSwitch(SpeidelBraumeisterEntity, SwitchEntity):
    """Switch for controlling the heating."""

    _attr_translation_key = "heating"

    def __init__(
        self,
        coordinator: SpeidelBraumeisterDataCoordinator,
        switch_type: str,
        switch_info: dict[str, Any],
    ) -> None:
        """Initialize the heating switch."""
        super().__init__(coordinator, switch_type)
        self._switch_type = switch_type
        self._attr_icon = switch_info.get("icon")

    @property
    def is_on(self) -> bool:
        """Return True if heating is on."""
        return self.machine_data.get("heating") == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the heating on."""
        try:
            await self.coordinator.async_set_heating(True)
            await self.coordinator.async_request_refresh()
        except NotImplementedError as err:
            _LOGGER.warning("Heating control not available: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Failed to turn on heating: %s", err)
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the heating off."""
        try:
            await self.coordinator.async_set_heating(False)
            await self.coordinator.async_request_refresh()
        except NotImplementedError as err:
            _LOGGER.warning("Heating control not available: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Failed to turn off heating: %s", err)
            raise

    @property
    def available(self) -> bool:
        """Return if entity is available.

        The switch is only available if control is supported.
        """
        # For now, switches are unavailable as the API doesn't support control
        return False
