"""API client for the Speidel Braumeister Cloud API.

This module provides multiple data fetching strategies:
1. XHR Polling (primary) - Uses web interface's polling method for real-time data
2. Cloud API (secondary) - REST API for account/machine info
3. MQTT (optional) - Real-time updates when subscription is available
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp
from aiohttp import ClientError, ClientTimeout

from .const import API_BASE_URL, WEB_API_BASE_URL
from .xhr_client import SpeidelXHRClient

_LOGGER = logging.getLogger(__name__)


class SpeidelAuthError(Exception):
    """Exception for authentication errors."""
    pass


class SpeidelApiError(Exception):
    """Exception for API errors."""
    pass


class SpeidelInvalidUUIDError(Exception):
    """Exception for invalid machine UUID (404 error)."""
    pass


class SpeidelPaymentRequiredError(Exception):
    """Exception for HTTP 402 Payment Required - subscription needed for this endpoint."""
    pass


class SpeidelBraumeisterAPI:
    """API client for Speidel Braumeister Cloud API.
    
    Uses XHR polling as the primary data source for real-time device status.
    Falls back to cloud API endpoints when needed.
    """

    def __init__(
        self,
        username: str,
        password: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._session = session
        self._own_session = False
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._user_id: Optional[str] = None
        self._machine_uuid: Optional[str] = None
        self._session_value: Optional[str] = None
        self._subscription_id: Optional[str] = None
        self._subscription_end: Optional[str] = None
        self._payment_required = False  # Track if we've seen 402 errors
        
        # XHR client for web interface polling
        self._xhr_client: Optional[SpeidelXHRClient] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=ClientTimeout(total=30),
            )
            self._own_session = True
        return self._session
    
    def _get_xhr_client(self) -> SpeidelXHRClient:
        """Get or create XHR client."""
        if self._xhr_client is None:
            self._xhr_client = SpeidelXHRClient(
                self._username,
                self._password,
                self._session,
            )
        return self._xhr_client

    async def close(self) -> None:
        """Close the aiohttp session if we own it."""
        if self._xhr_client:
            await self._xhr_client.close()
            self._xhr_client = None
        if self._own_session and self._session:
            await self._session.close()
            self._session = None
            self._own_session = False

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        use_auth: bool = True,
    ) -> Any:
        """Make an API request."""
        session = await self._get_session()
        url = f"{API_BASE_URL}{endpoint}"

        headers = {"Accept": "application/json"}
        
        if use_auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        _LOGGER.debug("Making %s request to %s with params %s", method, url, params)

        try:
            if method == "GET":
                async with session.get(url, headers=headers, params=params) as response:
                    return await self._handle_response(response, endpoint)
            else:
                raise SpeidelApiError(f"Unsupported method: {method}")

        except ClientError as err:
            _LOGGER.error("Connection error: %s", err)
            raise SpeidelApiError(f"Connection error: {err}") from err

    async def _post_request(
        self,
        endpoint: str,
        data: dict,
    ) -> Any:
        """Make a POST API request with form data."""
        session = await self._get_session()
        url = f"{API_BASE_URL}{endpoint}"

        headers = {"Accept": "application/json"}
        
        # Use form-encoded data
        form_data = aiohttp.FormData()
        for key, value in data.items():
            form_data.add_field(key, str(value))

        _LOGGER.debug("Making POST request to %s with data %s", url, data)

        try:
            async with session.post(url, headers=headers, data=form_data) as response:
                return await self._handle_response(response, endpoint)
        except ClientError as err:
            _LOGGER.error("Connection error: %s", err)
            raise SpeidelApiError(f"Connection error: {err}") from err

    async def _handle_response(self, response: aiohttp.ClientResponse, endpoint: str) -> Any:
        """Handle API response."""
        _LOGGER.debug("API response status: %s for %s", response.status, endpoint)
        
        if response.status == 401:
            raise SpeidelAuthError("Authentication failed - invalid credentials or expired token")
        
        if response.status == 402:
            # Payment Required - this endpoint needs a subscription
            error_text = await response.text()
            _LOGGER.warning("Payment required for endpoint %s - subscription needed for timeseries data", endpoint)
            raise SpeidelPaymentRequiredError(f"Payment required for {endpoint}: {error_text}")
        
        if response.status == 404:
            error_text = await response.text()
            _LOGGER.error("Resource not found: %s - %s", endpoint, error_text)
            raise SpeidelApiError(f"Resource not found: {endpoint}")
        
        if response.status == 400:
            error_text = await response.text()
            _LOGGER.error("Bad request: %s - %s", endpoint, error_text)
            raise SpeidelApiError(f"Bad request: {error_text}")
        
        if response.status == 500:
            error_text = await response.text()
            _LOGGER.error("Server error: %s - %s", endpoint, error_text)
            raise SpeidelApiError(f"Server error: {error_text}")
        
        if response.status >= 400:
            error_text = await response.text()
            _LOGGER.error("API error %s: %s", response.status, error_text)
            raise SpeidelApiError(f"API error {response.status}: {error_text}")
        
        # Check content type
        content_type = response.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            return await response.json()
        else:
            text = await response.text()
            if not text:
                return {}
            # Try to parse as JSON anyway
            try:
                import json
                return json.loads(text)
            except:
                return {"raw_response": text}

    async def authenticate(self) -> dict[str, Any]:
        """Authenticate and get a token."""
        _LOGGER.info("Authenticating with Speidel Cloud API...")
        
        try:
            # API expects 'username' and 'pass' fields
            result = await self._post_request(
                "/auth/authentication",
                {"username": self._username, "pass": self._password},
            )
            
            self._token = result.get("token")
            self._user_id = result.get("userid")
            self._token_expires = datetime.now() + timedelta(hours=23)
            
            # Capture subscription info (available in auth response)
            self._subscription_id = result.get("subscription_id")
            self._subscription_end = result.get("subscription_end")
            
            if self._subscription_id:
                _LOGGER.info("Subscription ID: %s, End: %s", self._subscription_id, self._subscription_end)
            
            if not self._token:
                raise SpeidelAuthError("No token received from API")
            
            _LOGGER.info("Successfully authenticated, user_id: %s", self._user_id)
            return result
            
        except SpeidelApiError as err:
            raise SpeidelAuthError(f"Authentication failed: {err}") from err

    async def ensure_authenticated(self) -> None:
        """Ensure we have a valid token."""
        if self._token and self._token_expires:
            if datetime.now() < self._token_expires:
                return
        await self.authenticate()

    async def get_account_processes(self) -> list[dict[str, Any]]:
        """Get all processes for the account (helps discover machine UUID).
        
        This is a FREE endpoint that returns ALL processes for ALL machines
        on the account. Use this to verify data exists and discover machine UUIDs.
        """
        await self.ensure_authenticated()
        result = await self._request("GET", "/account/timeseries/process")
        _LOGGER.info("Account processes response: %s", result)
        
        # Log detailed info about discovered processes
        if result and isinstance(result, list):
            _LOGGER.info("Found %d total processes for account", len(result))
            for proc in result[:5]:  # Log first 5
                _LOGGER.debug("Process: id=%s, status=%s, machine=%s", 
                             proc.get('id'), proc.get('status'), proc.get('machine'))
        else:
            _LOGGER.warning("No processes found at account level - account may have no machines registered")
        
        return result

    async def get_machines(self) -> list[dict[str, Any]]:
        """Get all machines for the account."""
        await self.ensure_authenticated()
        try:
            result = await self._request("GET", "/account/machines")
            _LOGGER.info("Account machines response: %s", result)
            return result
        except SpeidelApiError as err:
            _LOGGER.warning("Could not get machines list: %s", err)
            return []

    async def get_machine_status(self, machine_uuid: str) -> dict[str, Any]:
        """Get current status for a machine (real-time data endpoint)."""
        await self.ensure_authenticated()
        
        # Try different UUID formats
        uuid_variants = self._get_uuid_variants(machine_uuid)
        
        for uuid_variant in uuid_variants:
            try:
                result = await self._request("GET", f"/machine/{uuid_variant}/status")
                _LOGGER.info("Machine status response for %s: %s", uuid_variant, result)
                return result
            except SpeidelApiError as err:
                if "404" in str(err) or "not found" in str(err).lower():
                    _LOGGER.debug("UUID variant %s not found for status, trying next", uuid_variant)
                    continue
                raise
        
        _LOGGER.warning("Could not get machine status for: %s", machine_uuid)
        return {}

    async def get_braumeister_status(self) -> dict[str, Any]:
        """Get status from the braumeister endpoint (alternative endpoint)."""
        await self.ensure_authenticated()
        try:
            result = await self._request("GET", "/braumeister/status")
            _LOGGER.info("Braumeister status response: %s", result)
            return result
        except SpeidelApiError as err:
            _LOGGER.warning("Could not get braumeister status: %s", err)
            return {}

    async def get_device_status_control(self, machine_uuid: str) -> dict[str, Any]:
        """Get real-time device status from the web API.
        
        This is the endpoint the web interface uses for live data.
        Endpoint: https://www.myspeidel.com/braumeister/getDeviceStatusControl/{uuid}
        """
        await self.ensure_authenticated()
        session = await self._get_session()
        
        # Try different UUID formats
        uuid_variants = self._get_uuid_variants(machine_uuid)
        
        for uuid_variant in uuid_variants:
            url = f"{WEB_API_BASE_URL}/getDeviceStatusControl/{uuid_variant}"
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
            }
            
            _LOGGER.debug("Making request to web API: %s", url)
            
            try:
                async with session.get(url, headers=headers) as response:
                    _LOGGER.debug("Web API response status: %s for %s", response.status, url)
                    
                    if response.status == 200:
                        data = await response.json()
                        _LOGGER.info("Device status control response for %s: %s", uuid_variant, data)
                        return data
                    elif response.status == 404:
                        _LOGGER.debug("UUID variant %s not found on web API, trying next", uuid_variant)
                        continue
                    else:
                        text = await response.text()
                        _LOGGER.warning("Web API error %s: %s", response.status, text)
                        
            except ClientError as err:
                _LOGGER.warning("Web API connection error: %s", err)
                continue
        
        _LOGGER.warning("Could not get device status from web API for: %s", machine_uuid)
        return {}

    async def get_device_recipes(self, machine_uuid: str) -> list[dict[str, Any]]:
        """Get recipes from the web API."""
        await self.ensure_authenticated()
        session = await self._get_session()
        
        uuid_variants = self._get_uuid_variants(machine_uuid)
        
        for uuid_variant in uuid_variants:
            url = f"{WEB_API_BASE_URL}/getDeviceRecipes/{uuid_variant}"
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
            }
            
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        _LOGGER.info("Device recipes response: %s", data)
                        return data
                    elif response.status == 404:
                        continue
            except ClientError as err:
                _LOGGER.warning("Error getting recipes: %s", err)
                
        return []

    async def get_machine_sensors(self, machine_uuid: str) -> tuple[list[dict[str, Any]], bool]:
        """Get sensor data for a machine.
        
        Returns:
            tuple: (data list, uuid_valid bool)
        """
        await self.ensure_authenticated()
        
        # Try different UUID formats
        uuid_variants = self._get_uuid_variants(machine_uuid)
        
        for uuid_variant in uuid_variants:
            try:
                result = await self._request("GET", f"/machine/{uuid_variant}/timeseries/sensor")
                _LOGGER.info("Sensor API response for machine %s: %s", uuid_variant, result)
                return result, True
            except SpeidelApiError as err:
                if "404" in str(err) or "not found" in str(err).lower():
                    _LOGGER.debug("UUID variant %s not found, trying next", uuid_variant)
                    continue
                raise
        
        _LOGGER.error("No valid UUID format found for: %s", machine_uuid)
        return [], False

    def _get_uuid_variants(self, machine_uuid: str) -> list[str]:
        """Get different UUID format variants to try.
        
        The Speidel API may accept different formats:
        - "323" (short ID)
        - "0004A30B003D70F4" (long UUID)
        - "0004A30B003D70F4.323" (combined format from data-machine attribute)
        """
        variants = [machine_uuid]
        
        # If the UUID contains a dot, it might already be the combined format
        if "." in machine_uuid:
            parts = machine_uuid.split(".")
            if len(parts) == 2:
                long_uuid, short_id = parts
                # Also try just the short ID
                if short_id not in variants:
                    variants.append(short_id)
                # Also try just the long UUID
                if long_uuid not in variants:
                    variants.append(long_uuid)
        else:
            # If it's a short numeric ID, we might need to find the long UUID
            # If it's a long UUID, we might need the short ID
            # We'll try the original first, then any discovered combinations
            pass
        
        return variants

    async def get_machine_actors(self, machine_uuid: str) -> tuple[list[dict[str, Any]], bool]:
        """Get actor data for a machine.
        
        Returns:
            tuple: (data list, uuid_valid bool)
        """
        await self.ensure_authenticated()
        
        # Try different UUID formats
        uuid_variants = self._get_uuid_variants(machine_uuid)
        
        for uuid_variant in uuid_variants:
            try:
                result = await self._request("GET", f"/machine/{uuid_variant}/timeseries/actor")
                _LOGGER.info("Actor API response for machine %s: %s", uuid_variant, result)
                return result, True
            except SpeidelApiError as err:
                if "404" in str(err) or "not found" in str(err).lower():
                    _LOGGER.debug("UUID variant %s not found for actors, trying next", uuid_variant)
                    continue
                raise
        
        _LOGGER.error("No valid UUID format found for actors: %s", machine_uuid)
        return [], False

    async def get_machine_processes(self, machine_uuid: str) -> tuple[list[dict[str, Any]], bool]:
        """Get process data for a machine.
        
        Returns:
            tuple: (data list, uuid_valid bool)
        """
        await self.ensure_authenticated()
        
        # Try different UUID formats
        uuid_variants = self._get_uuid_variants(machine_uuid)
        
        for uuid_variant in uuid_variants:
            try:
                result = await self._request("GET", f"/machine/{uuid_variant}/timeseries/process")
                _LOGGER.info("Process API response for machine %s: %s", uuid_variant, result)
                return result, True
            except SpeidelApiError as err:
                if "404" in str(err) or "not found" in str(err).lower():
                    _LOGGER.debug("UUID variant %s not found for processes, trying next", uuid_variant)
                    continue
                raise
        
        _LOGGER.error("No valid UUID format found for processes: %s", machine_uuid)
        return [], False

    async def get_latest_data(self, machine_uuid: str) -> dict[str, Any]:
        """Get the latest data for a machine.
        
        Uses XHR polling as the primary method for real-time data.
        Falls back to cloud API endpoints when needed.
        """
        _LOGGER.info("Getting latest data for machine %s", machine_uuid)
        
        result = {
            "temperature": None,
            "target_temperature": None,
            "pump": "unknown",
            "heating": "unknown",
            "process_status": "unknown",
            "current_phase": "unknown",
            "remaining_time": None,
            "brew_name": None,
            "connection_status": "unknown",
            "uuid_valid": True,
        }
        
        # =============================================
        # PRIORITY 1: Try XHR polling (web interface method)
        # This is the most reliable way to get real-time data
        # =============================================
        try:
            xhr_client = self._get_xhr_client()
            xhr_data = await xhr_client.get_device_status(machine_uuid)
            
            if xhr_data:
                _LOGGER.info("Got XHR data: %s", xhr_data)
                
                # Copy relevant fields
                if xhr_data.get('temperature') is not None:
                    result['temperature'] = xhr_data['temperature']
                if xhr_data.get('target_temperature') is not None:
                    result['target_temperature'] = xhr_data['target_temperature']
                if xhr_data.get('pump'):
                    result['pump'] = xhr_data['pump']
                if xhr_data.get('heating'):
                    result['heating'] = xhr_data['heating']
                if xhr_data.get('process_status'):
                    result['process_status'] = xhr_data['process_status']
                if xhr_data.get('remaining_time') is not None:
                    result['remaining_time'] = xhr_data['remaining_time']
                if xhr_data.get('brew_name'):
                    result['brew_name'] = xhr_data['brew_name']
                if xhr_data.get('connection_status'):
                    result['connection_status'] = xhr_data['connection_status']
                
                # If we got temperature data, consider it a success
                if result['temperature'] is not None:
                    _LOGGER.info("Successfully got data via XHR polling")
                    return result
                
        except Exception as err:
            _LOGGER.warning("XHR polling error: %s", err)
        
        # =============================================
        # PRIORITY 2: Try the web API getDeviceStatusControl endpoint
        # (legacy method, kept for compatibility)
        # =============================================
        try:
            device_status = await self.get_device_status_control(machine_uuid)
            if device_status and isinstance(device_status, dict):
                _LOGGER.info("Got device status from web API: %s", device_status)
                
                # Parse the response - the structure may vary
                # Common fields based on web interface observation
                if "temperature" in device_status or "temp" in device_status:
                    result["temperature"] = device_status.get("temperature") or device_status.get("temp")
                if "targetTemperature" in device_status or "target_temperature" in device_status or "setTemp" in device_status:
                    result["target_temperature"] = (
                        device_status.get("targetTemperature") or 
                        device_status.get("target_temperature") or 
                        device_status.get("setTemp")
                    )
                if "pump" in device_status:
                    pump_val = device_status.get("pump")
                    if isinstance(pump_val, bool):
                        result["pump"] = "on" if pump_val else "off"
                    elif isinstance(pump_val, (int, float)):
                        result["pump"] = "on" if pump_val else "off"
                    else:
                        result["pump"] = str(pump_val).lower()
                if "heating" in device_status or "heater" in device_status:
                    heat_val = device_status.get("heating") or device_status.get("heater")
                    if isinstance(heat_val, bool):
                        result["heating"] = "on" if heat_val else "off"
                    elif isinstance(heat_val, (int, float)):
                        result["heating"] = "on" if heat_val else "off"
                    else:
                        result["heating"] = str(heat_val).lower()
                if "status" in device_status:
                    result["process_status"] = str(device_status.get("status")).lower()
                if "phase" in device_status or "currentPhase" in device_status:
                    result["current_phase"] = device_status.get("phase") or device_status.get("currentPhase")
                if "remainingTime" in device_status or "remaining_time" in device_status or "timeLeft" in device_status:
                    result["remaining_time"] = (
                        device_status.get("remainingTime") or 
                        device_status.get("remaining_time") or
                        device_status.get("timeLeft")
                    )
                if "recipe" in device_status or "recipeName" in device_status or "name" in device_status:
                    result["brew_name"] = (
                        device_status.get("recipe") or 
                        device_status.get("recipeName") or
                        device_status.get("name")
                    )
                
                # If we got any meaningful data, mark as online
                if result["temperature"] is not None or result["process_status"] != "unknown":
                    result["connection_status"] = "online"
                    _LOGGER.info("Successfully got real-time data from web API")
                    return result
                    
        except Exception as err:
            _LOGGER.warning("Error getting device status from web API: %s", err)
        
        # =============================================
        # PRIORITY 3: DIAGNOSTIC - Check account-level data (FREE endpoint)
        # =============================================
        try:
            account_processes = await self.get_account_processes()
            if account_processes:
                _LOGGER.info("Account has %d processes - data exists", len(account_processes))
                # Extract machine IDs from processes to help with UUID discovery
                machine_ids = set()
                for proc in account_processes:
                    if 'machine' in proc:
                        machine_ids.add(proc.get('machine'))
                if machine_ids:
                    _LOGGER.info("Discovered machine IDs from account processes: %s", machine_ids)
            else:
                _LOGGER.warning("Account has NO processes - this may indicate no machines are registered")
        except Exception as err:
            _LOGGER.warning("Could not fetch account processes: %s", err)
        
        # PRIORITY 2: Try the cloud API machine status endpoint
        try:
            machine_status = await self.get_machine_status(machine_uuid)
            if machine_status and isinstance(machine_status, dict):
                _LOGGER.info("Got machine status from cloud API: %s", machine_status)
                if "temperature" in machine_status:
                    result["temperature"] = machine_status.get("temperature")
                if "targetTemperature" in machine_status or "target_temperature" in machine_status:
                    result["target_temperature"] = machine_status.get("targetTemperature") or machine_status.get("target_temperature")
                if "pump" in machine_status:
                    result["pump"] = "on" if machine_status.get("pump") else "off"
                if "heating" in machine_status:
                    result["heating"] = "on" if machine_status.get("heating") else "off"
                if "status" in machine_status:
                    result["process_status"] = machine_status.get("status")
                    
                if result["temperature"] is not None:
                    result["connection_status"] = "online"
                    return result
        except Exception as err:
            _LOGGER.debug("Machine status endpoint error: %s", err)
        
        # PRIORITY 3: Try timeseries endpoints (historical data)
        # NOTE: These endpoints require a subscription and return 402 if not subscribed
        # Try to get sensor data
        try:
            sensors, uuid_valid = await self.get_machine_sensors(machine_uuid)
            if not uuid_valid:
                result["connection_status"] = "invalid_uuid"
                result["uuid_valid"] = False
                return result
            _LOGGER.info("Sensor data received: %s", sensors)
            
            if sensors and isinstance(sensors, list):
                for sensor in reversed(sensors):
                    sensor_type = sensor.get("type", "")
                    values = sensor.get("values", {})
                    
                    if sensor_type == "temperature" and result["temperature"] is None:
                        result["temperature"] = values.get("temperature")
                    elif sensor_type == "target_temperature" and result["target_temperature"] is None:
                        result["target_temperature"] = values.get("temperature")
        except SpeidelPaymentRequiredError as err:
            _LOGGER.warning("Timeseries sensor data requires subscription: %s", err)
            self._payment_required = True
        except Exception as err:
            _LOGGER.warning("Error fetching sensor data: %s", err)
        
        # Try to get actor data
        try:
            actors, uuid_valid = await self.get_machine_actors(machine_uuid)
            if not uuid_valid:
                result["connection_status"] = "invalid_uuid"
                result["uuid_valid"] = False
                return result
            _LOGGER.debug("Actor data: %s", actors)
            
            if actors and isinstance(actors, list):
                for actor in reversed(actors):
                    actor_type = actor.get("type", "")
                    values = actor.get("values", {})
                    
                    if actor_type == "pump" and result["pump"] == "unknown":
                        result["pump"] = "on" if values.get("pump", 0) else "off"
                    elif actor_type == "heating" and result["heating"] == "unknown":
                        result["heating"] = "on" if values.get("heating", 0) else "off"
        except SpeidelPaymentRequiredError as err:
            _LOGGER.warning("Timeseries actor data requires subscription: %s", err)
            self._payment_required = True
        except Exception as err:
            _LOGGER.warning("Error fetching actor data: %s", err)
        
        # Try to get process data
        try:
            processes, uuid_valid = await self.get_machine_processes(machine_uuid)
            if not uuid_valid:
                result["connection_status"] = "invalid_uuid"
                result["uuid_valid"] = False
                return result
            _LOGGER.debug("Process data: %s", processes)
            
            if processes and isinstance(processes, list):
                for process in processes:
                    status = process.get("status")
                    if status == "running":
                        result["process_status"] = "running"
                        
                        phases = process.get("phases", [])
                        if phases:
                            result["current_phase"] = phases[-1].get("type", "unknown")
                        
                        metadata = process.get("metadata", {})
                        result["brew_name"] = metadata.get("name")
                        break
                    elif status in ["finished", "aborted", "user abort"]:
                        if result["process_status"] == "unknown":
                            result["process_status"] = status
        except SpeidelPaymentRequiredError as err:
            _LOGGER.warning("Timeseries process data requires subscription: %s", err)
            self._payment_required = True
        except Exception as err:
            _LOGGER.warning("Error fetching process data: %s", err)
        
        # Determine connection status
        if result["uuid_valid"]:
            if (result["temperature"] is not None or 
                result["process_status"] != "unknown" or
                result["pump"] != "unknown" or
                result["heating"] != "unknown"):
                result["connection_status"] = "online"
            else:
                result["connection_status"] = "offline"
        
        return result

    @property
    def token(self) -> Optional[str]:
        """Return the current token."""
        return self._token

    @property
    def user_id(self) -> Optional[str]:
        """Return the user ID."""
        return self._user_id

    @property
    def machine_uuid(self) -> Optional[str]:
        """Return the machine UUID."""
        return self._machine_uuid

    @machine_uuid.setter
    def machine_uuid(self, value: str) -> None:
        """Set the machine UUID."""
        self._machine_uuid = value

    @property
    def username(self) -> str:
        """Return the username."""
        return self._username

    @property
    def subscription_id(self) -> Optional[str]:
        """Return the subscription ID."""
        return self._subscription_id

    @property
    def subscription_end(self) -> Optional[str]:
        """Return the subscription end date."""
        return self._subscription_end

    @property
    def has_subscription(self) -> bool:
        """Return True if user has an active subscription."""
        return self._subscription_id is not None

    @property
    def payment_required(self) -> bool:
        """Return True if we've encountered 402 Payment Required errors."""
        return self._payment_required
