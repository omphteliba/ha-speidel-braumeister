"""Button platform for Speidel Braumeister integration."""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.button import ButtonEntity

from .const import (
    DOMAIN,
    BUTTON_START_PROCESS,
    BUTTON_STOP_PROCESS,
    BUTTON_PAUSE_PROCESS,
    BUTTON_NEXT_PHASE,
    BUTTON_TYPES,
)
from .coordinator import SpeidelBraumeisterDataCoordinator
from .entity import SpeidelBraumeisterEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Speidel Braumeister buttons from a config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry
        async_add_entities: Callback to add entities
    """
    coordinator: SpeidelBraumeisterDataCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SpeidelBraumeisterButton(
            coordinator, BUTTON_START_PROCESS, BUTTON_TYPES[BUTTON_START_PROCESS]
        ),
        SpeidelBraumeisterButton(
            coordinator, BUTTON_STOP_PROCESS, BUTTON_TYPES[BUTTON_STOP_PROCESS]
        ),
        SpeidelBraumeisterButton(
            coordinator, BUTTON_PAUSE_PROCESS, BUTTON_TYPES[BUTTON_PAUSE_PROCESS]
        ),
        SpeidelBraumeisterButton(
            coordinator, BUTTON_NEXT_PHASE, BUTTON_TYPES[BUTTON_NEXT_PHASE]
        ),
    ]

    async_add_entities(entities)


class SpeidelBraumeisterButton(SpeidelBraumeisterEntity, ButtonEntity):
    """Button for Speidel Braumeister control."""

    def __init__(
        self,
        coordinator: SpeidelBraumeisterDataCoordinator,
        button_type: str,
        button_info: dict[str, Any],
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, button_type)
        self._button_type = button_type
        self._attr_translation_key = button_info.get("translation_key", button_type)
        self._attr_icon = button_info.get("icon")

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            if self._button_type == BUTTON_START_PROCESS:
                await self.coordinator.async_start_process()
            elif self._button_type == BUTTON_STOP_PROCESS:
                await self.coordinator.async_stop_process()
            elif self._button_type == BUTTON_PAUSE_PROCESS:
                await self.coordinator.async_pause_process()
            elif self._button_type == BUTTON_NEXT_PHASE:
                await self.coordinator.async_next_phase()
            
            await self.coordinator.async_request_refresh()
        except NotImplementedError as err:
            _LOGGER.warning("Button action not available: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Failed to execute button action: %s", err)
            raise

    @property
    def available(self) -> bool:
        """Return if entity is available.

        The button is only available if control is supported.
        """
        # For now, buttons are unavailable as the API doesn't support control
        return False
