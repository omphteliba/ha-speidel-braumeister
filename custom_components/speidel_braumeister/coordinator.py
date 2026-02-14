"""Data coordinator for the Speidel Braumeister integration."""

import logging
from datetime import timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SpeidelBraumeisterAPI, SpeidelAuthError, SpeidelApiError, SpeidelPaymentRequiredError
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class SpeidelBraumeisterDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage data updates for Speidel Braumeister."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: SpeidelBraumeisterAPI,
        machine_uuid: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Speidel Braumeister",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._api = api
        self._machine_uuid = machine_uuid
        self._mqtt_data: dict[str, Any] = {}
        self.mqtt_client: Optional[Any] = None
        self._mqtt_task: Optional[Any] = None
        self.web_auth: Optional[Any] = None  # Set by __init__.py

    @callback
    def update_from_mqtt(self, data: dict[str, Any]) -> None:
        """Update data from MQTT message."""
        _LOGGER.debug("Updating from MQTT: %s", data)
        
        # Merge MQTT data with existing data
        self._mqtt_data.update(data)
        
        # Update the coordinator data
        if self.data:
            updated_data = {**self.data, **self._mqtt_data}
        else:
            updated_data = self._mqtt_data.copy()
        
        # Ensure connection status is online if we're getting MQTT data
        updated_data["connection_status"] = "online"
        
        # Set the new data and notify listeners
        self.async_set_updated_data(updated_data)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the API.
        
        Priority:
        1. XHR polling via web_auth (PRIMARY - most reliable)
        2. Cloud API (SECONDARY - may require subscription)
        """
        _LOGGER.info("Starting data update for machine %s", self._machine_uuid)
        
        # Start with any MQTT data we have
        result = self._mqtt_data.copy()
        result["payment_required"] = False
        
        # =============================================
        # PRIORITY 1: XHR Polling via web_auth
        # This is the same method the web interface uses
        # =============================================
        if self.web_auth:
            try:
                xhr_data = await self.web_auth.get_device_status(self._machine_uuid)
                
                if xhr_data and xhr_data.get('temperature') is not None:
                    _LOGGER.info("Got data via XHR polling: %s", xhr_data)
                    
                    # Copy ALL XHR data to result
                    result['temperature'] = xhr_data.get('temperature')
                    result['target_temperature'] = xhr_data.get('target_temperature')
                    result['remaining_time'] = xhr_data.get('remaining_time')
                    result['remaining_seconds'] = xhr_data.get('remaining_seconds')
                    result['heating'] = xhr_data.get('heating', 'unknown')
                    result['pump'] = xhr_data.get('pump', 'unknown')
                    result['process_status'] = xhr_data.get('process_status', 'unknown')
                    result['connection_status'] = 'online'
                    
                    # Recipe information
                    result['brew_name'] = xhr_data.get('brew_name')
                    result['recipe_slot'] = xhr_data.get('recipe_slot')
                    result['recipe_matched'] = xhr_data.get('recipe_matched', False)
                    result['recipe_account_id'] = xhr_data.get('recipe_account_id')
                    result['recipe_date'] = xhr_data.get('recipe_date')
                    result['recipe_style'] = xhr_data.get('recipe_style')
                    
                    # Device info
                    result['device_type'] = xhr_data.get('device_type')
                    result['device_name'] = xhr_data.get('device_name')
                    result['last_online'] = xhr_data.get('last_online')
                    
                    # Brewing step info
                    result['device_mode'] = xhr_data.get('device_mode')
                    result['current_step'] = xhr_data.get('current_step')
                    result['progress'] = xhr_data.get('progress')
                    result['current_stage'] = xhr_data.get('current_stage')
                    
                    # Merge with any MQTT data
                    result = {**result, **self._mqtt_data}
                    result['connection_status'] = 'online'
                    
                    _LOGGER.info("XHR polling successful - temp: %s°C, brew: %s, heating: %s, pump: %s",
                               result.get('temperature'), result.get('brew_name'), 
                               result.get('heating'), result.get('pump'))
                    return result
                    
            except Exception as err:
                _LOGGER.warning("XHR polling error: %s", err)
        else:
            _LOGGER.warning("web_auth not available for XHR polling")
        
        # =============================================
        # PRIORITY 2: Cloud API
        # May return empty data or 402 errors
        # =============================================
        try:
            api_data = await self._api.get_latest_data(self._machine_uuid)
            _LOGGER.info("Coordinator received API data: %s", api_data)
            
            # Check if payment was required
            if self._api.payment_required:
                result["payment_required"] = True
                _LOGGER.warning("API requires subscription - XHR polling should be used instead")
            
            # Merge API data with MQTT data (MQTT takes precedence for real-time values)
            result = {**api_data, **self._mqtt_data, "payment_required": result["payment_required"]}
            
            # If we have MQTT data, mark as online
            if self._mqtt_data:
                result["connection_status"] = "online"
            
            return result

        except SpeidelPaymentRequiredError as err:
            _LOGGER.warning("Payment required for API access: %s", err)
            result["payment_required"] = True
            # If we have MQTT data, still return it
            if self._mqtt_data:
                _LOGGER.info("Using MQTT data (subscription required for API)")
                result["connection_status"] = "online"
                return result
            raise UpdateFailed(f"Payment required for API access. MQTT data not yet available.") from err
        except SpeidelAuthError as err:
            _LOGGER.error("Authentication error: %s", err)
            raise UpdateFailed(f"Authentication error: {err}") from err
        except SpeidelApiError as err:
            _LOGGER.error("API error: %s", err)
            # If we have MQTT data, still return it even if API fails
            if self._mqtt_data:
                _LOGGER.warning("API error but have MQTT data, continuing")
                result["connection_status"] = "online"
                return result
            raise UpdateFailed(f"API error: {err}") from err
        except Exception as err:
            _LOGGER.error("Unexpected error updating data: %s", err)
            # If we have MQTT data, still return it even if API fails
            if self._mqtt_data:
                _LOGGER.warning("Unexpected error but have MQTT data, continuing")
                result["connection_status"] = "online"
                return result
            raise UpdateFailed(f"Unexpected error: {err}") from err

    @property
    def machine_uuid(self) -> str:
        """Return the machine UUID."""
        return self._machine_uuid

    @property
    def api(self) -> SpeidelBraumeisterAPI:
        """Return the API client."""
        return self._api
