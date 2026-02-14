"""Base entity classes for Speidel Braumeister integration."""

from typing import Any

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, NAME
from .coordinator import SpeidelBraumeisterDataCoordinator


class SpeidelBraumeisterEntity(CoordinatorEntity[SpeidelBraumeisterDataCoordinator]):
    """Base entity for Speidel Braumeister devices."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SpeidelBraumeisterDataCoordinator,
        entity_key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._entity_key = entity_key

        # Use machine UUID for device identification
        device_id = coordinator.machine_uuid
        
        self._attr_unique_id = f"{device_id}_{entity_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model="Braumeister",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def machine_data(self) -> dict[str, Any]:
        """Return the machine data from coordinator."""
        return self.coordinator.data or {}
