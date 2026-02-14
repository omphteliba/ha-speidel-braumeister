"""Web authentication and XHR polling for Speidel My Speidel web interface.

The web interface uses cookie-based session authentication, not Bearer tokens.
This module handles obtaining/maintaining that session AND XHR polling for real-time data.
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


class SpeidelWebAuth:
    """Handle web session authentication and XHR polling for My Speidel."""

    def __init__(
        self,
        username: str,
        password: str,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        """Initialize the web auth client."""
        self._username = username
        self._password = password
        self._session = session
        self._own_session = False
        self._session_cookies: Optional[dict] = None
        self._session_value: Optional[str] = None
        self._user_id: Optional[str] = None
        self._machines: list[dict] = []
        self._last_auth: Optional[datetime] = None
        self._logged_in = False
        self._device_recipes: dict[int, str] = {}  # device slot -> name
        self._account_recipes: dict[int, dict] = {}  # account recipe_id -> {name, date, style}
        self._recipe_mapping: dict[int, int] = {}  # device slot -> account recipe_id (matched by name)
        self._device_name: Optional[str] = None
        self._device_type: Optional[str] = None  # e.g., "Braumeister 20 Liter"
        self._last_online: Optional[str] = None
        self._device_info: dict = {}  # Full device info from JSON

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
        """Login to My Speidel web interface."""
        session = await self._get_session()
        
        _LOGGER.info("Logging into My Speidel web interface...")
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,de;q=0.8',
            }
            
            async with session.get(WEB_BASE_URL, headers=headers) as response:
                _LOGGER.debug("Homepage status: %s", response.status)
                
            async with session.get(LOGIN_URL, headers=headers) as response:
                html = await response.text()
                csrf_match = re.search(r'<input[^>]*name="(_token)"[^>]*value="([^"]+)"', html)
                csrf_token = csrf_match.group(2) if csrf_match else None
            
            form_data = aiohttp.FormData()
            form_data.add_field('identity', self._username)
            form_data.add_field('password', self._password)
            if csrf_token:
                form_data.add_field('_token', csrf_token)
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Origin': WEB_BASE_URL,
                'Referer': LOGIN_URL,
            }
            
            async with session.post(LOGIN_URL, data=form_data, headers=headers, allow_redirects=True) as response:
                html = await response.text()
                
                cookies = {c.key: c.value for c in session.cookie_jar}
                has_session = 'ci_session' in cookies
                
                if has_session:
                    _LOGGER.info("Session cookie (ci_session) received")
                    
                    session_match = re.search(r"var\s+sessionValue\s*=\s*['\"]([^'\"]+)['\"]", html)
                    if session_match:
                        self._session_value = session_match.group(1)
                    
                    user_match = re.search(r"var\s+(?:userId|user_id|uid)\s*=\s*['\"]?(\d+)['\"]?", html)
                    if user_match:
                        self._user_id = user_match.group(1)
                    
                    self._machines = self._extract_machines(html)
                    self._session_cookies = cookies
                    self._last_auth = datetime.now()
                    self._logged_in = True
                    
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

    def _extract_machines(self, html: str) -> list[dict]:
        """Extract machine information from dashboard HTML."""
        machines = []
        device_pattern = re.compile(
            r'<li[^>]*class="teaser-box-item\s+(\w+)"[^>]*id="device_(\d+)"[^>]*data-machine="([^"]+)"',
            re.IGNORECASE
        )
        
        for match in device_pattern.finditer(html):
            machines.append({
                'status': match.group(1),
                'short_id': match.group(2),
                'full_id': match.group(3),
                'name': f"Braumeister {match.group(2)}",
            })
        
        return machines

    async def ensure_logged_in(self) -> bool:
        """Ensure we have a valid session."""
        if self._last_auth and (datetime.now() - self._last_auth) > timedelta(hours=1):
            self._logged_in = False
        
        if not self._logged_in:
            return await self.login()
        return True

    async def get_device_status(self, machine_id: str) -> dict[str, Any]:
        """Get real-time device status from the web API via XHR polling."""
        if not await self.ensure_logged_in():
            return {}
        
        session = await self._get_session()
        id_variants = self._get_id_variants(machine_id)
        
        # Fetch device info JSON
        await self._fetch_device_info_json(id_variants)
        
        # Fetch device recipes (stored on device)
        if not self._device_recipes:
            await self._fetch_device_recipes(id_variants[0] if id_variants else machine_id)
        
        # Fetch account recipes (stored in cloud)
        if not self._account_recipes:
            await self._fetch_account_recipes()
        
        # Build mapping between device slots and account recipes
        if self._device_recipes and self._account_recipes and not self._recipe_mapping:
            self._build_recipe_mapping()
        
        for device_id in id_variants:
            url = f"{WEB_BASE_URL}/braumeister/getDeviceStatusControl/{device_id}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f"{WEB_BASE_URL}/braumeister",
            }
            
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        continue
                    
                    text = await response.text()
                    
                    if text.startswith('<!'):
                        self._logged_in = False
                        if await self.login():
                            async with session.get(url, headers=headers) as retry_response:
                                text = await retry_response.text()
                                if text.startswith('<!'):
                                    continue
                        else:
                            continue
                    
                    if text and not text.startswith('<!'):
                        parsed = self._parse_xhr_response(text)
                        if parsed:
                            return parsed
                            
            except ClientError as err:
                _LOGGER.warning("Error fetching device status: %s", err)
                continue
        
        return {}

    async def _fetch_device_info_json(self, id_variants: list[str]) -> dict:
        """Fetch device info from JSON endpoint.
        
        Returns device info including:
        - device_type: e.g., "Braumeister 20 Liter"
        - device_name: user-defined name
        - last_online: last seen timestamp
        - device_mode: current mode (e.g., "wartet")
        - screen_title: current step name (e.g., "Stone IPA – Einmaischen")
        - progress: brewing progress percentage
        """
        session = await self._get_session()
        
        for device_id in id_variants:
            url = f"{WEB_BASE_URL}/braumeister/getDeviceStatus/{device_id}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json, */*',
                'X-Requested-With': 'XMLHttpRequest',
            }
            
            try:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        text = await response.text()
                        if text.startswith('{'):
                            import json
                            data = json.loads(text)
                            
                            # Extract device info
                            if 'machineInfo' in data:
                                machine_info = data['machineInfo']
                                self._device_name = machine_info.get('name')
                                
                                # Device type
                                machine_type = machine_info.get('machine_type', {})
                                self._device_type = machine_type.get('text')  # "Braumeister 20 Liter"
                            
                            # Last online
                            self._last_online = data.get('lastOnline')
                            
                            # Store full device info for later use
                            self._device_info = {
                                'device_type': self._device_type,
                                'device_name': self._device_name,
                                'last_online': self._last_online,
                                'device_mode': data.get('deviceMode'),  # e.g., "wartet"
                                'screen_title': data.get('screenTitle'),  # e.g., "Stone IPA – Einmaischen"
                                'progress': data.get('progress'),  # e.g., 10
                                'current_stage': data.get('currentStage'),
                                'screen_function': data.get('screenFunction'),  # e.g., "showMashing"
                            }
                            
                            _LOGGER.info("Device info: type=%s, name=%s, mode=%s, step=%s",
                                        self._device_type, self._device_name,
                                        data.get('deviceMode'), data.get('screenTitle'))
                            
                            return self._device_info
            except Exception as err:
                _LOGGER.debug("Error fetching device info JSON: %s", err)
        
        return {}

    async def _fetch_device_recipes(self, machine_id: str) -> None:
        """Fetch recipes stored on the device."""
        session = await self._get_session()
        
        url = f"{WEB_BASE_URL}/braumeister/getDeviceRecipes/{machine_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'X-Requested-With': 'XMLHttpRequest',
        }
        
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    self._device_recipes = self._parse_device_recipes(text)
                    _LOGGER.info("Loaded %d device recipes", len(self._device_recipes))
        except Exception as err:
            _LOGGER.warning("Error fetching device recipes: %s", err)

    async def _fetch_account_recipes(self) -> None:
        """Fetch recipes stored in the My Speidel account."""
        session = await self._get_session()
        
        url = f"{WEB_BASE_URL}/recipes/index/my_recipes"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html',
        }
        
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    html = await response.text()
                    self._account_recipes = self._parse_account_recipes_html(html)
                    _LOGGER.info("Loaded %d account recipes", len(self._account_recipes))
        except Exception as err:
            _LOGGER.warning("Error fetching account recipes: %s", err)

    def _parse_device_recipes(self, data_string: str) -> dict[int, str]:
        """Parse recipes from getDeviceRecipes response.
        
        Format: Each line is: slot_data.recipe_name
        Slot number is first value in slot_data (X-separated)
        """
        recipes = {}
        
        try:
            lines = data_string.strip().split('\n')
            for line in lines:
                if '.' in line:
                    parts = line.rsplit('.', 1)
                    if len(parts) == 2:
                        recipe_data = parts[0].strip()
                        recipe_name = parts[1].strip()
                        
                        data_parts = recipe_data.split('X')
                        if data_parts:
                            try:
                                slot = int(data_parts[0])
                                recipes[slot] = recipe_name
                            except ValueError:
                                pass
        except Exception as err:
            _LOGGER.error("Error parsing device recipes: %s", err)
        
        return recipes

    def _parse_account_recipes_html(self, html: str) -> dict[int, dict]:
        """Parse account recipes from HTML.
        
        Pattern: <li class="recipe-item" data-id="117775">
                 <a class="recipe-name-link">Stone IPA</a>
                 <time datetime="2025-01-12">12.01.2025</time>
                 <span class="recipe-beerstyle">IPA</span>
        """
        recipes = {}
        
        try:
            # Find all recipe items
            pattern = r'<li[^>]*class="recipe-item"[^>]*data-id="(\d+)"[^>]*>(.*?)</li>'
            matches = re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)
            
            for match in matches:
                recipe_id = int(match.group(1))
                content = match.group(2)
                
                # Extract name
                name_match = re.search(r'<a[^>]*class="recipe-name-link"[^>]*>([^<]+)</a>', content)
                name = name_match.group(1).strip() if name_match else "Unknown"
                
                # Extract date
                date_match = re.search(r'<time[^>]*datetime="([^"]+)"', content)
                date = date_match.group(1) if date_match else None
                
                # Extract beer style
                style_match = re.search(r'<span[^>]*class="recipe-beerstyle"[^>]*>([^<]+)</span>', content)
                style = style_match.group(1).strip() if style_match else None
                
                recipes[recipe_id] = {
                    'name': name,
                    'date': date,
                    'style': style,
                }
                
        except Exception as err:
            _LOGGER.error("Error parsing account recipes: %s", err)
        
        return recipes

    def _get_id_variants(self, machine_id: str) -> list[str]:
        """Get different ID format variants to try."""
        variants = [machine_id]
        
        if "." in machine_id:
            parts = machine_id.split(".")
            if len(parts) == 2:
                long_uuid, short_id = parts
                variants.append(short_id)
                variants.append(long_uuid)
                variants.append(f"{long_uuid}.{short_id}")
        
        return variants

    def _parse_xhr_response(self, data_string: str) -> dict[str, Any]:
        """Parse the XHR response string."""
        result = {'raw': data_string, 'connection_status': 'online'}
        
        try:
            parts = data_string.split(';')
            
            if len(parts) < 4:
                return {}
            
            result['firmware'] = parts[0]
            result['device_uuid'] = parts[1]
            result['session_id'] = parts[2]
            
            encoded = parts[3]
            data_parts = encoded.split('X')
            
            def safe_float(idx: int) -> Optional[float]:
                if idx < len(data_parts):
                    try:
                        val = data_parts[idx].strip()
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
            
            # Device recipe slot (position 0)
            recipe_slot = safe_int(0)
            result['recipe_slot'] = recipe_slot
            
            # Look up recipe name from device recipes
            if recipe_slot is not None and recipe_slot in self._device_recipes:
                result['brew_name'] = self._device_recipes[recipe_slot]
            elif recipe_slot is not None:
                result['brew_name'] = f"Recipe {recipe_slot}"
            
            # Get matched recipe info from account
            if recipe_slot is not None:
                matched_info = self.get_matched_recipe_info(recipe_slot)
                result['recipe_matched'] = matched_info['matched']
                if matched_info['matched']:
                    result['recipe_account_id'] = matched_info['account_id']
                    result['recipe_date'] = matched_info['date']
                    result['recipe_style'] = matched_info['style']
            
            # Time display
            if len(data_parts) > 1:
                result['time_display'] = data_parts[1]
            
            # Current temperature (position 5)
            current_temp = safe_float(5)
            result['temperature'] = current_temp
            
            # Target temperature (position 4, divided by 10)
            target_raw = safe_float(4)
            if target_raw is not None:
                result['target_temperature'] = target_raw / 10
            
            # Remaining time in seconds (position 6)
            remaining_seconds = safe_int(6)
            if remaining_seconds is not None:
                result['remaining_time'] = remaining_seconds // 60
                result['remaining_seconds'] = remaining_seconds
            
            # Status flags
            # Heating is at position 8, bit 0
            # Pump is at position 7, bit 1 (different position!)
            heating_flag = safe_int(8)
            pump_flag = safe_int(7)
            
            if heating_flag is not None:
                result['heating'] = 'on' if heating_flag & 0x01 else 'off'
            else:
                result['heating'] = 'unknown'
            
            if pump_flag is not None:
                result['pump'] = 'on' if pump_flag & 0x02 else 'off'
            else:
                result['pump'] = 'unknown'
            
            # Process status
            if current_temp is not None:
                if remaining_seconds and remaining_seconds > 0:
                    result['process_status'] = 'running'
                else:
                    result['process_status'] = 'idle'
            else:
                result['process_status'] = 'unknown'
            
            # Device info from JSON endpoint
            if self._device_name:
                result['device_name'] = self._device_name
            if self._device_type:
                result['device_type'] = self._device_type
            if self._last_online:
                result['last_online'] = self._last_online
            
            # Current brewing step info from device_info
            if self._device_info:
                result['device_mode'] = self._device_info.get('device_mode')
                result['current_step'] = self._device_info.get('screen_title')
                result['progress'] = self._device_info.get('progress')
                result['current_stage'] = self._device_info.get('current_stage')
                result['screen_function'] = self._device_info.get('screen_function')
            
            _LOGGER.info("Parsed: temp=%.1f°C, recipe=%s (slot %s), step=%s, mode=%s", 
                        current_temp or 0, result.get('brew_name', 'unknown'), recipe_slot,
                        result.get('current_step', 'unknown'), result.get('device_mode', 'unknown'))
            
            return result
            
        except Exception as err:
            _LOGGER.error("Error parsing XHR response: %s", err)
            return {}

    @property
    def session_value(self) -> Optional[str]:
        return self._session_value

    @property
    def user_id(self) -> Optional[str]:
        return self._user_id

    @property
    def machines(self) -> list[dict]:
        return self._machines

    @property
    def cookies(self) -> Optional[dict]:
        return self._session_cookies

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    @property
    def device_recipes(self) -> dict[int, str]:
        """Return device recipes (slot -> name)."""
        return self._device_recipes

    def _build_recipe_mapping(self) -> None:
        """Build mapping from device slot to account recipe ID by matching names.
        
        Matching priority:
        1. Exact match (case-insensitive)
        2. Account name contains device name (e.g., "Low Rider Pale" in "Low Rider Pale Ale")
        3. Device name contains account name
        """
        self._recipe_mapping = {}
        
        for slot, device_name in self._device_recipes.items():
            normalized_device_name = device_name.lower().strip()
            
            # Priority 1: Exact match
            for account_id, account_data in self._account_recipes.items():
                account_name = account_data.get('name', '').lower().strip()
                
                if normalized_device_name == account_name:
                    self._recipe_mapping[slot] = account_id
                    _LOGGER.debug("Exact match: device slot %d '%s' to account recipe %d",
                                 slot, device_name, account_id)
                    break
            
            if slot in self._recipe_mapping:
                continue
            
            # Priority 2: Account name contains device name (device name truncated)
            for account_id, account_data in self._account_recipes.items():
                account_name = account_data.get('name', '').lower().strip()
                
                if normalized_device_name in account_name:
                    self._recipe_mapping[slot] = account_id
                    _LOGGER.debug("Partial match (device in account): device slot %d '%s' to account recipe %d '%s'",
                                 slot, device_name, account_id, account_data.get('name'))
                    break
            
            if slot in self._recipe_mapping:
                continue
            
            # Priority 3: Device name contains account name
            for account_id, account_data in self._account_recipes.items():
                account_name = account_data.get('name', '').lower().strip()
                
                if account_name and account_name in normalized_device_name:
                    self._recipe_mapping[slot] = account_id
                    _LOGGER.debug("Partial match (account in device): device slot %d '%s' to account recipe %d '%s'",
                                 slot, device_name, account_id, account_data.get('name'))
                    break
        
        _LOGGER.info("Built recipe mapping: %d of %d device recipes matched to account",
                    len(self._recipe_mapping), len(self._device_recipes))
    
    def get_matched_recipe_info(self, slot: int) -> dict[str, Any]:
        """Get full recipe info for a device slot, including account data if matched.
        
        Returns:
            dict with: device_slot, device_name, account_id, account_name, 
                       date, style, matched
        """
        result = {
            'device_slot': slot,
            'device_name': self._device_recipes.get(slot, f'Unknown Slot {slot}'),
            'account_id': None,
            'account_name': None,
            'date': None,
            'style': None,
            'matched': False,
        }
        
        if slot in self._recipe_mapping:
            account_id = self._recipe_mapping[slot]
            if account_id in self._account_recipes:
                account_data = self._account_recipes[account_id]
                result['account_id'] = account_id
                result['account_name'] = account_data.get('name')
                result['date'] = account_data.get('date')
                result['style'] = account_data.get('style')
                result['matched'] = True
        
        return result

    @property
    def account_recipes(self) -> dict[int, dict]:
        """Return account recipes (id -> {name, date, style})."""
        return self._account_recipes
    
    @property
    def recipe_mapping(self) -> dict[int, int]:
        """Return mapping from device slot to account recipe ID."""
        return self._recipe_mapping
