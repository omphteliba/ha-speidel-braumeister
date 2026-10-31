"""Data coordinator for the Speidel Braumeister integration."""

import logging
from time import monotonic
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SpeidelBraumeisterAPI, SpeidelAuthError, SpeidelApiError, SpeidelPaymentRequiredError
from .request_policy import PollingError, RetryLater, error_delay, jitter
from .const import DEFAULT_SCAN_INTERVAL
from .polling import polling_state, DEFAULT_ONLINE_INTERVAL, DEFAULT_ACTIVE_INTERVAL, MQTT_MAX_AGE

_LOGGER = logging.getLogger(__name__)

# Invalid values that indicate "no real data"
INVALID_TEMPS = {-1000, -999, -1, None}


class SpeidelBraumeisterDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to manage data updates for Speidel Braumeister."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: SpeidelBraumeisterAPI,
        machine_uuid: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        online_interval: int = DEFAULT_ONLINE_INTERVAL,
        active_interval: int = DEFAULT_ACTIVE_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Speidel Braumeister",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._poll_intervals = {
            "offline": scan_interval,
            "online": min(scan_interval, online_interval),
            "active": min(scan_interval, online_interval, active_interval),
        }
        self._failure_count = 0
        self._retry_not_before = 0.0
        self._mqtt_received_at = None
        self._api = api
        self._machine_uuid = machine_uuid
        self._mqtt_data: dict[str, Any] = {}
        self.mqtt_client: Optional[Any] = None
        self._mqtt_task: Optional[Any] = None
        self.web_auth: Optional[Any] = None
        
        # Track last online time
        self._last_online: Optional[datetime] = None
        # Store last known good data for device info
        self._last_device_info: dict[str, Any] = {}

    @callback
    def update_from_mqtt(self, data: dict[str, Any]) -> None:
        """Update data from MQTT message."""
        _LOGGER.debug("Updating from MQTT: %s", data)
        
        self._mqtt_received_at = monotonic()
        self._mqtt_data.update(data)
        self._last_online = datetime.now(timezone.utc).replace(microsecond=0)
        
        if self.data:
            updated_data = {**self.data, **self._mqtt_data}
        else:
            updated_data = self._mqtt_data.copy()
        
        updated_data["connection_status"] = "online"
        updated_data["last_online"] = self._last_online
        self._set_poll_interval(updated_data)
        self.async_set_updated_data(updated_data)

    def _is_valid_temp(self, temp: Any) -> bool:
        """Check if temperature value is valid."""
        if temp is None:
            return False
        try:
            temp_float = float(temp)
            return temp_float not in INVALID_TEMPS and -50 < temp_float < 200
        except (TypeError, ValueError):
            return False

    def _is_valid_pump_heating(self, value: Any) -> bool:
        """Check if pump/heating value is valid (clear on/off state)."""
        if value is None:
            return False
        value_str = str(value).lower().strip()
        return value_str in ("ein", "on", "true", "1", "aus", "off", "false", "0")

    def _get_offline_result(self) -> dict[str, Any]:
        """Return a default result for offline devices, preserving last online info."""
        return {
            "connection_status": "offline",
            "temperature": None,
            "target_temperature": None,
            "pump": "unknown",
            "heating": "unknown",
            "process_status": "idle",
            "brew_name": None,
            "remaining_time": None,
            "payment_required": False,
            "device_type": self._last_device_info.get("device_type"),
            "device_name": self._last_device_info.get("device_name"),
            "device_mode": self._last_device_info.get("device_mode"),
            "last_online": self._last_online,
        }

    def _update_last_online(self, data: dict[str, Any]) -> None:
        """Update last online timestamp and device info when device is online."""
        self._last_online = datetime.now(timezone.utc).replace(microsecond=0)
        
        if data.get("device_type"):
            self._last_device_info["device_type"] = data.get("device_type")
        if data.get("device_name"):
            self._last_device_info["device_name"] = data.get("device_name")
        if data.get("device_mode"):
            self._last_device_info["device_mode"] = data.get("device_mode")

    def _clean_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Clean and validate data, removing invalid/stale values."""
        cleaned = data.copy()
        
        # Clean temperature values
        temp_valid = self._is_valid_temp(data.get("temperature"))
        target_valid = self._is_valid_temp(data.get("target_temperature"))
        
        if not temp_valid:
            cleaned["temperature"] = None
        if not target_valid:
            cleaned["target_temperature"] = None
        
        # Clean pump/heating - only keep clear on/off states
        pump_val = data.get("pump")
        if not self._is_valid_pump_heating(pump_val):
            cleaned["pump"] = "unknown"
        else:
            pump_str = str(pump_val).lower().strip()
            cleaned["pump"] = "on" if pump_str in ("ein", "on", "true", "1") else "off"
        
        heating_val = data.get("heating")
        if not self._is_valid_pump_heating(heating_val):
            cleaned["heating"] = "unknown"
        else:
            heating_str = str(heating_val).lower().strip()
            cleaned["heating"] = "on" if heating_str in ("ein", "on", "true", "1") else "off"
        
        # Check for idle indicators
        current_phase = str(data.get("current_phase", "")).lower().strip()
        device_mode = str(data.get("device_mode", "")).lower().strip()
        process_status = str(data.get("process_status", "")).lower().strip()
        brew_name = data.get("brew_name")
        remaining_time = data.get("remaining_time")
        
        # Phases that indicate NOT brewing (German and English)
        idle_phases = [
            "hauptmenü", "hauptmenu", "main menu", "menu",
            "idle", "wartet", "waiting", "ready", "bereit"
        ]
        
        # Modes that indicate NOT brewing
        idle_modes = [
            "waiting", "wartet", "idle", "ready", "bereit"
        ]
        
        is_idle_phase = current_phase in idle_phases
        is_idle_mode = device_mode in idle_modes
        is_idle = is_idle_phase or is_idle_mode
        
        # If phase/mode indicates idle, clear ONLY brew-specific data
        # Keep pump/heating states as they can be controlled manually
        if is_idle:
            cleaned["process_status"] = "idle"
            cleaned["brew_name"] = None
            cleaned["remaining_time"] = None
            if not target_valid:
                cleaned["target_temperature"] = None
            _LOGGER.debug("Device in idle state (phase=%s, mode=%s), cleared brew data but kept pump/heating", current_phase, device_mode)
            return cleaned
        
        # Brewing indicators: valid target temp, brew name, or remaining time
        has_brewing_indicators = (
            target_valid or 
            (brew_name and str(brew_name).strip()) or
            (remaining_time is not None and remaining_time > 0)
        )
        
        # If process_status is "running" but no brewing indicators, set to idle
        if process_status == "running" and not has_brewing_indicators:
            cleaned["process_status"] = "idle"
            cleaned["brew_name"] = None
            cleaned["remaining_time"] = None
            _LOGGER.debug("Process was 'running' but no brewing indicators found, set to idle")
        elif process_status not in ("running", "paused", "finished", "aborted", "idle"):
            cleaned["process_status"] = "idle"
        
        return cleaned

    def _set_poll_interval(self, data: dict[str, Any]) -> None:
        state = polling_state(data)
        seconds = jitter(self._poll_intervals[state])
        self.update_interval = timedelta(seconds=seconds)
        _LOGGER.debug("Adaptive polling: state=%s, next interval=%ss", state, seconds)

    async def _async_update_data(self) -> dict[str, Any]:
        """Honor cooldown even for update_entity; never sleep in HA's loop."""
        remaining = self._retry_not_before - monotonic()
        if remaining > 0:
            self.update_interval = timedelta(seconds=min(remaining, 86400))
            raise UpdateFailed("MySpeidel polling pause is still active")
        try:
            result = await self._fetch_data()
        except Exception as err:
            self._failure_count += 1
            delay = error_delay(self._poll_intervals["offline"], self._failure_count)
            if isinstance(err, RetryLater):
                delay = max(delay, err.deadline - monotonic())
            delay = jitter(delay)
            self._retry_not_before = monotonic() + delay
            self.update_interval = timedelta(seconds=min(delay, 86400))
            raise UpdateFailed(f"MySpeidel refresh failed; retry in {delay:.0f}s") from err
        # A successful response (including device offline) ends error backoff.
        self._failure_count = 0
        self._retry_not_before = 0.0
        self._set_poll_interval(result)
        return result

    async def _fetch_data(self) -> dict[str, Any]:
        """Fetch data from the API."""
        _LOGGER.debug("Starting data update for machine %s", self._machine_uuid)
        
        # A historic MQTT message must not disable XHR polling indefinitely.
        if self._mqtt_received_at is None or monotonic() - self._mqtt_received_at >= MQTT_MAX_AGE:
            self._mqtt_data.clear()
        result: dict[str, Any] = self._mqtt_data.copy()
        result["payment_required"] = False
        result["last_online"] = self._last_online
        
        # If we have MQTT data, device is online
        if self._mqtt_data:
            result["connection_status"] = "online"
            self._update_last_online(result)
            return self._clean_data(result)
        
        # PRIORITY 1: XHR Polling
        if self.web_auth:
            try:
                xhr_data = await self.web_auth.get_device_status(self._machine_uuid)
                
                if xhr_data and xhr_data.get('temperature') is not None:
                    _LOGGER.debug("Got data via XHR polling")
                    
                    result['temperature'] = xhr_data.get('temperature')
                    result['target_temperature'] = xhr_data.get('target_temperature')
                    result['remaining_time'] = xhr_data.get('remaining_time')
                    result['remaining_seconds'] = xhr_data.get('remaining_seconds')
                    result['heating'] = xhr_data.get('heating', 'unknown')
                    result['pump'] = xhr_data.get('pump', 'unknown')
                    result['process_status'] = xhr_data.get('process_status', 'unknown')
                    result['connection_status'] = 'online'
                    result['brew_name'] = xhr_data.get('brew_name')
                    result['recipe_slot'] = xhr_data.get('recipe_slot')
                    result['recipe_matched'] = xhr_data.get('recipe_matched', False)
                    result['recipe_account_id'] = xhr_data.get('recipe_account_id')
                    result['recipe_date'] = xhr_data.get('recipe_date')
                    result['device_type'] = xhr_data.get('device_type')
                    result['device_name'] = xhr_data.get('device_name')
                    result['device_mode'] = xhr_data.get('device_mode')
                    result['current_step'] = xhr_data.get('current_step')
                    result['current_phase'] = xhr_data.get('current_phase')
                    result['progress'] = xhr_data.get('progress')
                    result['brew_status_code'] = xhr_data.get('brew_status_code')
                    result['alarm'] = xhr_data.get('alarm')
                    
                    self._update_last_online(result)
                    result["last_online"] = self._last_online
                    
                    return self._clean_data(result)
                    
                # XHR returned data but no temperature = device offline
                _LOGGER.debug("XHR returned data but device appears offline")
                result = self._get_offline_result()
                return result
                    
            except PollingError:
                raise
            except Exception as err:
                raise UpdateFailed("XHR polling failed") from err
        
        # PRIORITY 2: Cloud API
        try:
            api_data = await self._api.get_latest_data(self._machine_uuid)
            
            if self._api.payment_required:
                result["payment_required"] = True
            
            # Debug: log what we received
            _LOGGER.debug("API returned data of type: %s", type(api_data).__name__)
            
            # Convert Pydantic model to dict
            # Use model_dump() for Pydantic v2
            try:
                if hasattr(api_data, 'model_dump'):
                    _LOGGER.debug("Using model_dump() for conversion")
                    api_dict = api_data.model_dump()
                elif hasattr(api_data, 'dict'):
                    # Pydantic v1 fallback
                    _LOGGER.debug("Using dict() for Pydantic v1")
                    api_dict = api_data.dict()
                elif isinstance(api_data, dict):
                    _LOGGER.debug("API data is already a dict")
                    api_dict = api_data
                else:
                    # Last resort: try to convert to dict manually
                    _LOGGER.debug("Using vars() for manual conversion")
                    api_dict = {k: v for k, v in vars(api_data).items() if not k.startswith('_')}
            except Exception as conv_err:
                _LOGGER.error("Failed to convert api_data to dict: %s", conv_err)
                raise
            
            # Check if we got valid data
            if api_dict.get('temperature') is not None or api_dict.get('connection_status') == 'online':
                result = {**api_dict, **self._mqtt_data, "payment_required": result["payment_required"]}
                self._update_last_online(result)
                result["last_online"] = self._last_online
                return self._clean_data(result)
            
            # No valid data - device is offline
            result = self._get_offline_result()
            if api_dict.get("device_type"):
                result["device_type"] = api_dict.get("device_type")
            return result

        except PollingError:
            raise
        except SpeidelPaymentRequiredError:
            _LOGGER.debug("Payment required - device may be offline")
            return self._get_offline_result()
            
        except SpeidelAuthError as err:
            _LOGGER.error("Authentication error: %s", err)
            raise UpdateFailed(f"Authentication error: {err}") from err
            
        except SpeidelApiError as err:
            _LOGGER.debug("API error (device may be offline): %s", err)
            raise UpdateFailed("Cloud API request failed") from err
            
        except Exception as err:
            raise UpdateFailed("Cloud API request failed") from err

    @property
    def machine_uuid(self) -> str:
        """Return the machine UUID."""
        return self._machine_uuid

    @property
    def api(self) -> SpeidelBraumeisterAPI:
        """Return the API client."""
        return self._api