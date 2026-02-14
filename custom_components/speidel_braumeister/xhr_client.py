"""XHR Polling client for Speidel Braumeister web interface.

This module implements real-time data fetching using the same XHR polling
method that the web interface uses. This approach bypasses the need for
MQTT subscription and provides direct access to device status.

Key endpoint: /braumeister/getDeviceStatusControl/{device_uuid}.{machine_id}
Response format: firmware;device_uuid;session_id;X-separated-data;hash1;hash2

Data positions (X-separated):
  [0] = mode/state
  [1] = time display (HH:MM)
  [2] = status character
  [3] = unknown
  [4] = unknown (not target temp)
  [5] = current temperature (°C)
  [6] = remaining time in seconds
  [7] = counter
  [8] = status flags (bit 0 = heating, bit 1 = pump)
  ...
"""

import logging
import re
from typing import Any, Optional
from datetime import datetime, timedelta

import aiohttp
from aiohttp import ClientError, ClientTimeout

_LOGGER = logging.getLogger(__name__)

WEB_BASE_URL = "https://www.myspeidel.com"
LOGIN_URL = f"{WEB_BASE_URL}/auth/login"


class SpeidelXHRError(Exception):
    """Exception for XHR polling errors."""
    pass


class SpeidelXHRClient:
    """XHR polling client for Speidel Braumeister web interface."""

    def __init__(
        self,
        username: str,
        password: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        """Initialize the XHR client."""
        self._username = username
        self._password = password
        self._session = session
        self._own_session = False
        self._logged_in = False
        self._csrf_token: Optional[str] = None
        self._machines: list[dict] = []
        self._last_auth: Optional[datetime] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=ClientTimeout(total=30),
                cookie_jar=aiohttp.CookieJar(),
            )
            self._own_session = True
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session if we own it."""
        if self._own_session and self._session:
            await self._session.close()
            self._session = None
            self._own_session = False

    async def login(self) -> bool:
        """Login to My Speidel web interface.
        
        Note: The server returns 200 with the login page (doesn't redirect)
        but sets the session cookie which is what actually matters.
        We verify login success by testing the XHR endpoint.
        """
        session = await self._get_session()
        
        _LOGGER.info("Logging into My Speidel web interface for XHR polling...")
        
        try:
            # Step 1: Visit homepage to get initial cookies
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
            }
            
            async with session.get(WEB_BASE_URL, headers=headers) as response:
                _LOGGER.debug("Homepage status: %s", response.status)
            
            # Step 2: Get login page
            async with session.get(LOGIN_URL, headers=headers) as response:
                html = await response.text()
                _LOGGER.debug("Login page status: %s", response.status)
                
                # Look for CSRF token (though tests showed none)
                csrf_match = re.search(r'<input[^>]*name="(_token)"[^>]*value="([^"]+)"', html)
                if csrf_match:
                    self._csrf_token = csrf_match.group(2)
                    _LOGGER.debug("Found CSRF token")
            
            # Step 3: Submit login form
            # The form uses 'identity' field (not 'email' or 'username')
            form_data = aiohttp.FormData()
            form_data.add_field('identity', self._username)
            form_data.add_field('password', self._password)
            if self._csrf_token:
                form_data.add_field('_token', self._csrf_token)
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Origin': WEB_BASE_URL,
                'Referer': LOGIN_URL,
            }
            
            async with session.post(
                LOGIN_URL,
                data=form_data,
                headers=headers,
                allow_redirects=True
            ) as response:
                html = await response.text()
                final_url = str(response.url)
                
                _LOGGER.debug("Login POST status: %s, URL: %s", response.status, final_url)
                
                # IMPORTANT: The server may return 200 with login page URL
                # but still set the session cookie. We need to verify by
                # testing the XHR endpoint.
                
                # Check for ci_session cookie
                cookies = {c.key: c.value for c in session.cookie_jar}
                has_session = 'ci_session' in cookies
                
                if has_session:
                    _LOGGER.info("Session cookie received, verifying login...")
                    
                    # Try to extract machines from response
                    self._machines = self._extract_machines(html)
                    
                    # Verify by testing XHR endpoint
                    if self._machines:
                        machine_id = self._machines[0]['full_id']
                        test_data = await self._test_xhr_access(machine_id)
                        if test_data:
                            _LOGGER.info("Login verified - XHR endpoint accessible")
                            self._logged_in = True
                            self._last_auth = datetime.now()
                            return True
                    else:
                        # Try with known machine ID format
                        # Use a test call to verify session
                        self._logged_in = True  # Assume success, will be verified on first data fetch
                        self._last_auth = datetime.now()
                        _LOGGER.info("Session established (will verify on first data fetch)")
                        return True
                else:
                    _LOGGER.error("No session cookie received - login failed")
                    return False
                    
        except ClientError as err:
            _LOGGER.error("Login error: %s", err)
            return False
        except Exception as err:
            _LOGGER.error("Unexpected login error: %s", err)
            return False

    async def _test_xhr_access(self, machine_id: str) -> Optional[dict]:
        """Test if XHR endpoint is accessible with current session."""
        session = await self._get_session()
        
        url = f"{WEB_BASE_URL}/braumeister/getDeviceStatusControl/{machine_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f"{WEB_BASE_URL}/braumeister",
        }
        
        try:
            async with session.get(url, headers=headers) as response:
                text = await response.text()
                
                # Check if we got actual data (not HTML login page)
                if text and not text.startswith('<!'):
                    return self._parse_xhr_response(text)
        except Exception as err:
            _LOGGER.debug("XHR test error: %s", err)
        
        return None

    def _extract_machines(self, html: str) -> list[dict]:
        """Extract machine information from dashboard HTML."""
        machines = []
        
        # Pattern: <li class="teaser-box-item online" id="device_323" data-machine="0004A30B003D70F4.323">
        device_pattern = re.compile(
            r'<li[^>]*class="teaser-box-item\s+(\w+)"[^>]*id="device_(\d+)"[^>]*data-machine="([^"]+)"',
            re.IGNORECASE
        )
        
        for match in device_pattern.finditer(html):
            status = match.group(1)
            short_id = match.group(2)
            full_id = match.group(3)
            
            # Extract name
            remaining_html = html[match.end():match.end()+500]
            name_match = re.search(r'<span[^>]*class="[^"]*teaser-box-title[^"]*"[^>]*>([^<]+)</span>', remaining_html)
            name = name_match.group(1).strip() if name_match else f"Braumeister {short_id}"
            
            machines.append({
                'status': status,
                'short_id': short_id,
                'full_id': full_id,
                'name': name,
            })
            _LOGGER.info("Found machine: %s (id: %s)", name, full_id)
        
        return machines

    async def ensure_logged_in(self) -> bool:
        """Ensure we have a valid session."""
        # Check if session might be expired (older than 1 hour)
        if self._last_auth and (datetime.now() - self._last_auth) > timedelta(hours=1):
            _LOGGER.info("Session may be expired, re-logging in")
            self._logged_in = False
        
        if not self._logged_in:
            return await self.login()
        return True

    async def get_device_status(self, machine_id: str) -> dict[str, Any]:
        """Get real-time device status via XHR polling.
        
        Args:
            machine_id: Can be short ID (323), long UUID, or combined format (0004A30B003D70F4.323)
        
        Returns:
            Dict with parsed device status data
        """
        if not await self.ensure_logged_in():
            _LOGGER.warning("Not logged in, cannot fetch device status")
            return {}
        
        session = await self._get_session()
        
        # Try different ID formats
        id_variants = self._get_id_variants(machine_id)
        
        for device_id in id_variants:
            url = f"{WEB_BASE_URL}/braumeister/getDeviceStatusControl/{device_id}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f"{WEB_BASE_URL}/braumeister",
            }
            
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        _LOGGER.debug("Status %s for device %s", response.status, device_id)
                        continue
                    
                    text = await response.text()
                    
                    # Check if we got HTML (session expired)
                    if text.startswith('<!'):
                        _LOGGER.info("Session expired, re-logging in...")
                        self._logged_in = False
                        if await self.login():
                            # Retry with new session
                            async with session.get(url, headers=headers) as retry_response:
                                text = await retry_response.text()
                                if text.startswith('<!'):
                                    continue
                        else:
                            continue
                    
                    # Parse the XHR response
                    if text and not text.startswith('<!'):
                        parsed = self._parse_xhr_response(text)
                        if parsed:
                            _LOGGER.info("Got device status for %s: temp=%s°C", 
                                       device_id, parsed.get('temperature'))
                            return parsed
                            
            except ClientError as err:
                _LOGGER.warning("Error fetching device status: %s", err)
                continue
        
        _LOGGER.warning("Could not get device status for %s", machine_id)
        return {}

    def _get_id_variants(self, machine_id: str) -> list[str]:
        """Get different ID format variants to try."""
        variants = [machine_id]
        
        if "." in machine_id:
            parts = machine_id.split(".")
            if len(parts) == 2:
                long_uuid, short_id = parts
                if short_id not in variants:
                    variants.append(short_id)
                if long_uuid not in variants:
                    variants.append(long_uuid)
                # Also try the full format
                variants.append(f"{long_uuid}.{short_id}")
        
        return variants

    def _parse_xhr_response(self, data_string: str) -> dict[str, Any]:
        """Parse the XHR response string.
        
        Format: firmware;device_uuid;session_id;X-separated-data;hash1;hash2
        
        Data positions (X-separated):
          [0] = mode/state
          [1] = time display (HH:MM format)
          [2] = status character
          [3] = unknown
          [4] = unknown
          [5] = current temperature (°C)
          [6] = remaining time in seconds
          [7] = counter
          [8] = status flags (bit 0 = heating, bit 1 = pump)
          ...
        """
        result = {
            'raw': data_string,
            'connection_status': 'online',
        }
        
        try:
            parts = data_string.split(';')
            
            if len(parts) < 4:
                _LOGGER.warning("XHR response has fewer than 4 parts: %s", data_string[:100])
                return {}
            
            result['firmware'] = parts[0]
            result['device_uuid'] = parts[1]
            result['session_id'] = parts[2]
            
            # Parse X-separated data
            encoded = parts[3]
            data_parts = encoded.split('X')
            
            # Extract values based on known positions
            def safe_float(idx: int) -> Optional[float]:
                if idx < len(data_parts):
                    try:
                        val = data_parts[idx].strip()
                        # Handle values with leading spaces
                        val = val.strip()
                        return float(val) if val else None
                    except (ValueError, IndexError):
                        pass
                return None
            
            def safe_int(idx: int) -> Optional[int]:
                if idx < len(data_parts):
                    try:
                        val = data_parts[idx].strip()
                        return int(float(val)) if val else None
                    except (ValueError, IndexError):
                        pass
                return None
            
            # Mode
            result['mode'] = safe_int(0)
            
            # Time display (position 1) - format HH:MM
            if len(data_parts) > 1:
                result['time_display'] = data_parts[1]
            
            # Current temperature (position 5)
            current_temp = safe_float(5)
            result['temperature'] = current_temp
            
            # Target temperature - we need to find where this is
            # Based on analysis, position 4 is NOT target temp
            # Target temp might come from a different endpoint or calculation
            # For now, leave as None unless we can determine it
            result['target_temperature'] = None
            
            # Remaining time in seconds (position 6)
            remaining_seconds = safe_int(6)
            if remaining_seconds is not None:
                result['remaining_time'] = remaining_seconds // 60  # Convert to minutes
                result['remaining_seconds'] = remaining_seconds
            
            # Counter (position 7)
            result['counter'] = safe_int(7)
            
            # Status flags (position 8)
            status_flag = safe_int(8)
            if status_flag is not None:
                # Decode status flags
                # Based on testing: value 1 means heating is active
                result['heating'] = 'on' if status_flag & 0x01 else 'off'
                result['pump'] = 'on' if status_flag & 0x02 else 'off'
            else:
                result['heating'] = 'unknown'
                result['pump'] = 'unknown'
            
            # Try to determine process status based on available data
            if current_temp is not None:
                if remaining_seconds and remaining_seconds > 0:
                    result['process_status'] = 'running'
                else:
                    result['process_status'] = 'idle'
            else:
                result['process_status'] = 'unknown'
            
            _LOGGER.debug("Parsed XHR response: temp=%.1f°C, time=%dmin, flags=%s", 
                         current_temp or 0, result.get('remaining_time', 0), status_flag)
            
            return result
            
        except Exception as err:
            _LOGGER.error("Error parsing XHR response: %s", err)
            return {}

    @property
    def machines(self) -> list[dict]:
        """Return the list of discovered machines."""
        return self._machines

    @property
    def is_logged_in(self) -> bool:
        """Return whether we have a valid session."""
        return self._logged_in
