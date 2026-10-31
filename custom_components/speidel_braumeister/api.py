"""API client for the Speidel Braumeister Cloud API.

Refactored to use Pydantic v2 models for type-safe data handling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote, urlencode

import aiohttp
from aiohttp import ClientError, ClientTimeout
from yarl import URL

from .const import API_BASE_URL, WEB_API_BASE_URL
from .models import (
    AuthResponse,
    ConnectionStatus,
    DeviceDataResult,
    DeviceStatusControl,
    Machine,
    MachineList,
    OnOffStatus,
    ProcessStatus,
    AccountRecipe,
    RecipeSlot,
    BrewingProcess,
)
from .xhr_client import SpeidelXHRClient

_LOGGER = logging.getLogger(__name__)


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class SpeidelError(Exception):
    """Base exception for Speidel integration errors."""
    pass


class SpeidelAuthError(SpeidelError):
    """Authentication failed."""
    pass


class SpeidelApiError(SpeidelError):
    """API request failed."""
    pass


class SpeidelInvalidUUIDError(SpeidelError):
    """Invalid machine UUID - device not found."""
    pass


class SpeidelPaymentRequiredError(SpeidelError):
    """Subscription required for this endpoint."""
    
    def __init__(self, endpoint: str, message: str = ""):
        self.endpoint = endpoint
        super().__init__(
            f"Payment required for {endpoint}. "
            f"A My Speidel subscription is needed. {message}"
        )


class SpeidelConnectionError(SpeidelError):
    """Connection to device/API failed."""
    pass


# =============================================================================
# API CLIENT
# =============================================================================

class SpeidelBraumeisterAPI:
    """API client for Speidel Braumeister Cloud API.
    
    Uses XHR polling as the primary data source for real-time device status.
    Falls back to cloud API endpoints when needed.
    
    Example:
        async with SpeidelBraumeisterAPI(username, password) as client:
            await client.authenticate()
            data = await client.get_latest_data("1234567890ABCDEF.123")
            print(f"Temperature: {data.temperature}°C")
    """
    
    def __init__(
        self,
        username: str,
        password: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        """Initialize the API client.
        
        Args:
            username: My Speidel account username
            password: My Speidel account password
            session: Optional aiohttp session (will create one if not provided)
        """
        self._username = username
        self._password = password
        self._session = session
        self._own_session = False
        
        # Auth state
        self._token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._user_id: Optional[str] = None
        self._auth_response: Optional[AuthResponse] = None
        
        # Subscription info
        self._payment_required = False
        
        # XHR client for web interface polling
        self._xhr_client: Optional[SpeidelXHRClient] = None

    async def __aenter__(self) -> "SpeidelBraumeisterAPI":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - cleanup resources."""
        await self.close()

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

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    async def authenticate(self) -> AuthResponse:
        """Authenticate with the Speidel Cloud API.
        
        Returns:
            AuthResponse with token and user info
            
        Raises:
            SpeidelAuthError: If authentication fails
        """
        _LOGGER.info("Authenticating with Speidel Cloud API...")
        
        session = await self._get_session()
        url = f"{API_BASE_URL}/auth/authentication"
        
        form_data = aiohttp.FormData()
        form_data.add_field("username", self._username)
        form_data.add_field("pass", self._password)
        
        try:
            async with session.post(url, data=form_data) as response:
                if response.status == 401:
                    raise SpeidelAuthError("Invalid credentials")
                
                if response.status != 200:
                    text = await response.text()
                    raise SpeidelAuthError(f"Auth failed: {response.status} - {text}")
                
                data = await response.json()
                self._auth_response = AuthResponse.model_validate(data)
                self._token = self._auth_response.token
                self._user_id = self._auth_response.user_id
                self._token_expires = datetime.now() + timedelta(hours=23)
                
                _LOGGER.info(
                    "Authenticated successfully. User: %s, Has subscription: %s",
                    self._user_id,
                    self._auth_response.has_subscription
                )
                
                return self._auth_response
                
        except ClientError as err:
            raise SpeidelConnectionError(f"Connection error: {err}") from err

    async def ensure_authenticated(self) -> None:
        """Ensure we have a valid authentication token."""
        if self._token and self._token_expires:
            if datetime.now() < self._token_expires:
                return
        await self.authenticate()

    # =========================================================================
    # LOW-LEVEL API REQUESTS
    # =========================================================================

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> Any:
        """Make an authenticated API request.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            params: Optional query parameters
            
        Returns:
            Parsed JSON response
            
        Raises:
            SpeidelApiError: On API errors
            SpeidelAuthError: On auth failures
            SpeidelPaymentRequiredError: On 402 responses
        """
        await self.ensure_authenticated()
        session = await self._get_session()
        url = f"{API_BASE_URL}{endpoint}"
        
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        
        _LOGGER.debug("API request: %s %s", method, url)
        
        try:
            async with session.get(url, headers=headers, params=params) as response:
                return await self._handle_response(response, endpoint)
                
        except ClientError as err:
            raise SpeidelConnectionError(f"Connection error: {err}") from err

    async def _handle_response(
        self, 
        response: aiohttp.ClientResponse, 
        endpoint: str
    ) -> Any:
        """Handle API response and raise appropriate exceptions."""
        status = response.status
        _LOGGER.debug("API response: %d for %s", status, endpoint)
        
        # Error handling
        if status == 401:
            raise SpeidelAuthError("Authentication expired or invalid")
        
        if status == 402:
            self._payment_required = True
            raise SpeidelPaymentRequiredError(endpoint)
        
        if status == 404:
            raise SpeidelInvalidUUIDError(f"Resource not found: {endpoint}")
        
        if status == 400:
            text = await response.text()
            raise SpeidelApiError(f"Bad request: {text}")
        
        if status >= 500:
            text = await response.text()
            raise SpeidelApiError(f"Server error: {status} - {text}")
        
        if status >= 400:
            text = await response.text()
            raise SpeidelApiError(f"API error {status}: {text}")
        
        # Parse response
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            return await response.json()
        else:
            text = await response.text()
            if not text:
                return {}
            try:
                import json
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw_response": text}

    # =========================================================================
    # MACHINE METHODS
    # =========================================================================

    async def get_machines(self) -> list[Machine]:
        """Get all machines for the authenticated account.
        
        Returns:
            List of Machine objects
        """
        try:
            data = await self._request("GET", "/account/machines")
            result = MachineList.model_validate(data)
            _LOGGER.info("Found %d machines", len(result.machines))
            return result.machines
        except SpeidelApiError as err:
            _LOGGER.warning("Could not get machines: %s", err)
            return []

    async def get_machine_status(self, machine_uuid: str) -> DeviceStatusControl:
        """Get real-time status for a machine.
        
        Args:
            machine_uuid: Machine UUID (supports multiple formats)
            
        Returns:
            DeviceStatusControl with current status
        """
        for uuid_variant in self._get_uuid_variants(machine_uuid):
            try:
                data = await self._request(
                    "GET", 
                    f"/machine/{uuid_variant}/status"
                )
                return DeviceStatusControl.model_validate(data)
            except SpeidelInvalidUUIDError:
                continue
        
        return DeviceStatusControl(connection_status=ConnectionStatus.INVALID_UUID)

    # =========================================================================
    # DEVICE DATA (MAIN METHOD)
    # =========================================================================

    async def get_latest_data(self, machine_uuid: str) -> DeviceDataResult:
        """Get the latest data for a machine.
        
        This is the main method for fetching device data. It tries multiple
        data sources in order of reliability:
        
        1. XHR polling (web interface method) - most reliable for real-time
        2. Web API getDeviceStatusControl endpoint
        3. Cloud API endpoints (may require subscription)
        
        Args:
            machine_uuid: Machine UUID (supports multiple formats)
            
        Returns:
            DeviceDataResult with aggregated device data
        """
        _LOGGER.info("Fetching latest data for machine %s", machine_uuid)
        
        result = DeviceDataResult(
            connection_status=ConnectionStatus.OFFLINE,
            data_source="unknown",
        )
        
        # PRIORITY 1: XHR Polling (most reliable)
        try:
            xhr_client = self._get_xhr_client()
            xhr_data = await xhr_client.get_device_status(machine_uuid)
            
            if xhr_data:
                result = self._parse_xhr_data(xhr_data, result)
                if result.temperature is not None:
                    result.data_source = "xhr"
                    _LOGGER.info("Got data via XHR: temp=%s", result.temperature)
                    return result
                    
        except Exception as err:
            _LOGGER.warning("XHR polling error: %s", err)
        
        # PRIORITY 2: Web API
        try:
            web_data = await self._get_device_status_web(machine_uuid)
            if web_data:
                result = self._parse_web_data(web_data, result)
                if result.temperature is not None:
                    result.data_source = "web_api"
                    _LOGGER.info("Got data via Web API: temp=%s", result.temperature)
                    return result
                    
        except Exception as err:
            _LOGGER.warning("Web API error: %s", err)
        
        # PRIORITY 3: Cloud API
        try:
            cloud_data = await self._get_device_status_cloud(machine_uuid)
            if cloud_data:
                result = self._parse_cloud_data(cloud_data, result)
                result.data_source = "cloud_api"
                
        except SpeidelPaymentRequiredError:
            _LOGGER.warning("Cloud API requires subscription")
            self._payment_required = True
        except Exception as err:
            _LOGGER.warning("Cloud API error: %s", err)
        
        # Finalize connection status
        self._finalize_connection_status(result)
        
        return result

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    # =========================================================================
    # TIMESERIES PROBE (diagnostic, see docs/DEVICE_PROTOCOL.md)
    # =========================================================================

    async def _probe_get(self, endpoint: str, params: Optional[dict] = None) -> Any:
        """GET an endpoint and log status and body, never raising."""
        await self.ensure_authenticated()
        session = await self._get_session()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        # The API rejects unencoded reserved characters (e.g. ':' in timestamps)
        url = f"{API_BASE_URL}{endpoint}"
        if params:
            url += "?" + urlencode(params, quote_via=quote)
        try:
            async with session.get(URL(url, encoded=True), headers=headers) as response:
                text = await response.text()
                _LOGGER.info(
                    "TIMESERIES PROBE %s %s -> %d, %d bytes: %s",
                    endpoint, params or "", response.status, len(text), text[:1500],
                )
                if response.status == 200:
                    try:
                        return await response.json(content_type=None)
                    except ValueError:
                        return None
        except Exception as err:  # diagnostic only
            _LOGGER.info("TIMESERIES PROBE %s failed: %s", endpoint, err)
        return None

    async def probe_timeseries(self, machine_uuid: str) -> None:
        """Log what the documented timeseries endpoints return for this account.

        Runs once at setup. The endpoints are documented at
        https://api.cloud.myspeidel.com/v1.0/api-docs and need a subscription.
        """
        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%S.000Z"
        recent = {"from": (now - timedelta(days=1)).strftime(fmt), "to": now.strftime(fmt)}
        history = {"from": (now - timedelta(days=365)).strftime(fmt), "to": now.strftime(fmt)}

        processes = await self._probe_get("/account/timeseries/process")

        uuids = self._get_uuid_variants(machine_uuid)
        # Machine UUIDs referenced by the account's processes, if any
        items = processes if isinstance(processes, list) else (
            (processes or {}).get("collection") or [] if isinstance(processes, dict) else []
        )
        for item in items[:20]:
            if isinstance(item, dict):
                for key in ("machine_uuid", "machineUuid", "machine", "machine_id"):
                    val = item.get(key)
                    if isinstance(val, dict):
                        val = val.get("uuid")
                    if isinstance(val, str) and val not in uuids:
                        uuids.append(val)

        for uuid in uuids:
            await self._probe_get(f"/machine/{uuid}/timeseries/process")
            await self._probe_get(f"/machine/{uuid}/timeseries/process", history)
            await self._probe_get(f"/machine/{uuid}/timeseries/phase", recent)
            await self._probe_get(f"/machine/{uuid}/timeseries/sensor", {**recent, "granularity": 100})
            await self._probe_get(f"/machine/{uuid}/timeseries/actor", {**recent, "granularity": 100})

        _LOGGER.info("TIMESERIES PROBE done for %s (tried %s)", machine_uuid, uuids)

    def _get_uuid_variants(self, machine_uuid: str) -> list[str]:
        """Get UUID format variants to try.
        
        The Speidel API may accept different formats:
        - "323" (short ID)
        - "1234567890ABCDEF" (long UUID)
        - "1234567890ABCDEF.123" (combined format)
        """
        variants = [machine_uuid]
        
        if "." in machine_uuid:
            parts = machine_uuid.split(".")
            if len(parts) == 2:
                long_uuid, short_id = parts
                if short_id not in variants:
                    variants.append(short_id)
                if long_uuid not in variants:
                    variants.append(long_uuid)
        
        return variants

    def _parse_xhr_data(
        self, 
        xhr_data: dict[str, Any], 
        result: DeviceDataResult
    ) -> DeviceDataResult:
        """Parse XHR polling data into result."""
        if xhr_data.get("temperature") is not None:
            result.temperature = xhr_data["temperature"]
        if xhr_data.get("target_temperature") is not None:
            result.target_temperature = xhr_data["target_temperature"]
        if xhr_data.get("pump"):
            result.pump = OnOffStatus.from_value(xhr_data["pump"])
        if xhr_data.get("heating"):
            result.heating = OnOffStatus.from_value(xhr_data["heating"])
        if xhr_data.get("process_status"):
            result.process_status = ProcessStatus(
                xhr_data["process_status"].lower()
            )
        if xhr_data.get("remaining_time") is not None:
            result.remaining_time = xhr_data["remaining_time"]
        if xhr_data.get("brew_name"):
            result.brew_name = xhr_data["brew_name"]
        if xhr_data.get("connection_status"):
            result.connection_status = ConnectionStatus(
                xhr_data["connection_status"]
            )
        return result

    def _parse_web_data(
        self, 
        web_data: dict[str, Any], 
        result: DeviceDataResult
    ) -> DeviceDataResult:
        """Parse web API data into result."""
        # Temperature fields
        result.temperature = (
            web_data.get("temperature") or 
            web_data.get("temp")
        )
        result.target_temperature = (
            web_data.get("targetTemperature") or
            web_data.get("target_temp") or
            web_data.get("setTemp")
        )
        
        # Actor fields
        result.pump = OnOffStatus.from_value(
            web_data.get("pump") or web_data.get("pumpStatus")
        )
        result.heating = OnOffStatus.from_value(
            web_data.get("heating") or web_data.get("heater")
        )
        
        # Process fields
        result.process_status = ProcessStatus(
            str(web_data.get("status", "unknown")).lower()
        )
        result.current_phase = web_data.get("phase") or web_data.get("currentPhase")
        result.remaining_time = (
            web_data.get("remainingTime") or
            web_data.get("remaining_time") or
            web_data.get("timeLeft")
        )
        result.brew_name = (
            web_data.get("recipe") or
            web_data.get("recipeName") or
            web_data.get("name")
        )
        
        return result

    def _parse_cloud_data(
        self, 
        cloud_data: dict[str, Any], 
        result: DeviceDataResult
    ) -> DeviceDataResult:
        """Parse cloud API data into result."""
        result.temperature = cloud_data.get("temperature")
        result.target_temperature = cloud_data.get("targetTemperature")
        result.pump = OnOffStatus.from_value(cloud_data.get("pump"))
        result.heating = OnOffStatus.from_value(cloud_data.get("heating"))
        result.process_status = ProcessStatus(
            str(cloud_data.get("status", "unknown")).lower()
        )
        return result

    def _finalize_connection_status(self, result: DeviceDataResult) -> None:
        """Determine final connection status."""
        if not result.uuid_valid:
            result.connection_status = ConnectionStatus.INVALID_UUID
        elif result.temperature is not None or result.process_status != ProcessStatus.UNKNOWN:
            result.connection_status = ConnectionStatus.ONLINE
        else:
            result.connection_status = ConnectionStatus.OFFLINE

    async def _get_device_status_web(self, machine_uuid: str) -> Optional[dict]:
        """Get status from web API endpoint."""
        await self.ensure_authenticated()
        session = await self._get_session()
        
        for uuid_variant in self._get_uuid_variants(machine_uuid):
            url = f"{WEB_API_BASE_URL}/getDeviceStatusControl/{uuid_variant}"
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
            }
            
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    if response.status != 404:
                        _LOGGER.debug("Web API status %d for %s", response.status, url)
            except ClientError as err:
                _LOGGER.debug("Web API error: %s", err)
        
        return None

    async def _get_device_status_cloud(self, machine_uuid: str) -> Optional[dict]:
        """Get status from cloud API endpoint."""
        try:
            return await self._request("GET", f"/machine/{machine_uuid}/status")
        except SpeidelInvalidUUIDError:
            return None

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def token(self) -> Optional[str]:
        """Current authentication token."""
        return self._token

    @property
    def user_id(self) -> Optional[str]:
        """Authenticated user ID."""
        return self._user_id

    @property
    def has_subscription(self) -> bool:
        """Whether user has an active subscription."""
        return self._auth_response.has_subscription if self._auth_response else False

    @property
    def payment_required(self) -> bool:
        """Whether we've encountered payment-required errors."""
        return self._payment_required


    # Add these properties to the SpeidelBraumeisterAPI class
    # (add them near the end of the class, after the existing properties)

    @property
    def subscription_id(self) -> Optional[str]:
        """Return the subscription ID."""
        if self._auth_response:
            return self._auth_response.subscription_id
        return None

    @property
    def subscription_end(self) -> Optional[str]:
        """Return the subscription end date."""
        if self._auth_response:
            return self._auth_response.subscription_end
        return None
