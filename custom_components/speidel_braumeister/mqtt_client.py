"""MQTT WebSocket client for real-time Speidel Braumeister data."""

import asyncio
import json
import logging
from typing import Any, Callable, Optional

import aiohttp

from .const import MQTT_URL

_LOGGER = logging.getLogger(__name__)


class SpeidelMQTTClient:
    """MQTT WebSocket client for real-time data from Speidel Cloud."""

    def __init__(
        self,
        token: str,
        user_id: str,
        machine_id: str,
        on_data_callback: Optional[Callable[[dict], None]] = None,
        session_value: Optional[str] = None,
    ) -> None:
        """Initialize the MQTT client.
        
        Args:
            token: Bearer token from cloud API (used as fallback)
            user_id: User ID from authentication
            machine_id: Machine ID (short format like '323')
            on_data_callback: Callback for incoming data
            session_value: Session value from web interface for MQTT auth
        """
        self._token = token
        self._user_id = user_id
        self._machine_id = machine_id
        self._on_data_callback = on_data_callback
        self._session_value = session_value
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._connected = False
        self._running = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._listen_task: Optional[asyncio.Task] = None
        
        # Latest data cache
        self._latest_data: dict[str, Any] = {}
        
    @property
    def connected(self) -> bool:
        """Return if client is connected."""
        return self._connected
        
    @property
    def latest_data(self) -> dict[str, Any]:
        """Return the latest received data."""
        return self._latest_data.copy()
    
    async def connect(self) -> bool:
        """Connect to the MQTT WebSocket."""
        if self._connected:
            return True
            
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()
                
            _LOGGER.info("Connecting to MQTT WebSocket: %s", MQTT_URL)
            
            # Connect with authentication headers
            headers = {
                "Authorization": f"Bearer {self._token}",
            }
            
            self._ws = await self._session.ws_connect(
                MQTT_URL,
                headers=headers,
                heartbeat=30,
            )
            
            self._connected = True
            _LOGGER.info("Connected to MQTT WebSocket")
            
            # Send connect message
            await self._send_connect()
            
            # Subscribe to machine topics
            await self._subscribe_machine()
            
            return True
            
        except aiohttp.ClientError as err:
            _LOGGER.error("Failed to connect to MQTT: %s", err)
            self._connected = False
            return False
        except Exception as err:
            _LOGGER.error("Unexpected error connecting to MQTT: %s", err)
            self._connected = False
            return False
    
    async def _send_connect(self) -> None:
        """Send MQTT connect message."""
        if not self._ws:
            return
            
        # The web interface uses session-based authentication for MQTT
        # Try session value first (from web login), fall back to token
        if self._session_value:
            # Session-based auth (preferred - same as web interface)
            connect_msg = {
                "type": "connect",
                "session": self._session_value,
                "userId": self._user_id,
            }
            _LOGGER.debug("Sending connect message with session auth")
        else:
            # Token-based auth (fallback)
            connect_msg = {
                "type": "connect",
                "token": self._token,
                "userId": self._user_id,
            }
            _LOGGER.debug("Sending connect message with token auth")
        
        await self._ws.send_json(connect_msg)
    
    async def _subscribe_machine(self) -> None:
        """Subscribe to machine status topics."""
        if not self._ws:
            return
            
        # Subscribe to machine status updates
        # The topic format is likely: machine/{machineId}/status
        topics = [
            f"machine/{self._machine_id}/status",
            f"machine/{self._machine_id}/sensors",
            f"machine/{self._machine_id}/actors",
            f"device/{self._machine_id}",
            f"braumeister/{self._machine_id}",
        ]
        
        for topic in topics:
            subscribe_msg = {
                "type": "subscribe",
                "topic": topic,
            }
            _LOGGER.debug("Subscribing to topic: %s", topic)
            await self._ws.send_json(subscribe_msg)
    
    async def listen(self) -> None:
        """Listen for incoming messages."""
        if not self._ws:
            return
            
        self._running = True
        _LOGGER.info("Starting MQTT message listener")
        
        try:
            async for msg in self._ws:
                if not self._running:
                    break
                    
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", self._ws.exception())
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    _LOGGER.warning("WebSocket connection closed")
                    break
                    
        except asyncio.CancelledError:
            _LOGGER.debug("Listen task cancelled")
        except Exception as err:
            _LOGGER.error("Error in listen loop: %s", err)
        finally:
            self._running = False
            self._connected = False
    
    async def _handle_message(self, data: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            message = json.loads(data)
            _LOGGER.debug("Received MQTT message: %s", message)
            
            msg_type = message.get("type", "")
            topic = message.get("topic", "")
            payload = message.get("payload", message.get("data", {}))
            
            # Handle different message types
            if msg_type == "status" or "status" in topic:
                self._process_status(payload)
            elif msg_type == "sensor" or "sensor" in topic:
                self._process_sensor(payload)
            elif msg_type == "actor" or "actor" in topic:
                self._process_actor(payload)
            elif msg_type == "connected":
                _LOGGER.info("MQTT connection confirmed")
            elif msg_type == "subscribed":
                _LOGGER.debug("Subscription confirmed: %s", topic)
            else:
                # Try to extract data from any message
                self._process_generic(message)
                
        except json.JSONDecodeError as err:
            _LOGGER.warning("Failed to parse MQTT message: %s", err)
        except Exception as err:
            _LOGGER.error("Error handling MQTT message: %s", err)
    
    def _process_status(self, payload: dict) -> None:
        """Process status update."""
        _LOGGER.info("Processing status payload: %s", payload)
        
        # Extract temperature
        if "temperature" in payload:
            self._latest_data["temperature"] = payload["temperature"]
        if "temp" in payload:
            self._latest_data["temperature"] = payload["temp"]
        if "targetTemperature" in payload:
            self._latest_data["target_temperature"] = payload["targetTemperature"]
        if "setTemp" in payload:
            self._latest_data["target_temperature"] = payload["setTemp"]
            
        # Extract pump/heating status
        if "pump" in payload:
            pump_val = payload["pump"]
            self._latest_data["pump"] = "on" if pump_val else "off"
        if "heating" in payload:
            heat_val = payload["heating"]
            self._latest_data["heating"] = "on" if heat_val else "off"
        if "heater" in payload:
            heat_val = payload["heater"]
            self._latest_data["heating"] = "on" if heat_val else "off"
            
        # Extract process info
        if "status" in payload:
            self._latest_data["process_status"] = payload["status"]
        if "phase" in payload:
            self._latest_data["current_phase"] = payload["phase"]
        if "currentPhase" in payload:
            self._latest_data["current_phase"] = payload["currentPhase"]
        if "remainingTime" in payload:
            self._latest_data["remaining_time"] = payload["remainingTime"]
        if "timeLeft" in payload:
            self._latest_data["remaining_time"] = payload["timeLeft"]
            
        # Recipe name
        if "recipe" in payload:
            self._latest_data["brew_name"] = payload["recipe"]
        if "recipeName" in payload:
            self._latest_data["brew_name"] = payload["recipeName"]
            
        self._notify_callback()
    
    def _process_sensor(self, payload: dict) -> None:
        """Process sensor update."""
        _LOGGER.debug("Processing sensor payload: %s", payload)
        
        sensor_type = payload.get("type", payload.get("sensorType", ""))
        value = payload.get("value", payload.get("temperature", payload.get("data")))
        
        if sensor_type == "temperature" or "temp" in str(sensor_type).lower():
            if value is not None:
                self._latest_data["temperature"] = value
                
        self._notify_callback()
    
    def _process_actor(self, payload: dict) -> None:
        """Process actor update."""
        _LOGGER.debug("Processing actor payload: %s", payload)
        
        actor_type = payload.get("type", payload.get("actorType", ""))
        value = payload.get("value", payload.get("state"))
        
        if actor_type == "pump":
            self._latest_data["pump"] = "on" if value else "off"
        elif actor_type == "heating" or actor_type == "heater":
            self._latest_data["heating"] = "on" if value else "off"
            
        self._notify_callback()
    
    def _process_generic(self, message: dict) -> None:
        """Try to extract data from a generic message."""
        _LOGGER.debug("Processing generic message: %s", message)
        
        # Try to find common data fields
        for key in ["temperature", "temp", "targetTemperature", "setTemp", 
                    "pump", "heating", "heater", "status", "phase", 
                    "remainingTime", "recipe", "recipeName"]:
            if key in message:
                if key == "temp":
                    self._latest_data["temperature"] = message[key]
                elif key == "setTemp":
                    self._latest_data["target_temperature"] = message[key]
                elif key == "heater":
                    self._latest_data["heating"] = "on" if message[key] else "off"
                elif key in ["pump", "heating"]:
                    self._latest_data[key] = "on" if message[key] else "off"
                else:
                    # Map to our internal naming
                    mapped_key = key
                    if key == "targetTemperature":
                        mapped_key = "target_temperature"
                    elif key == "remainingTime":
                        mapped_key = "remaining_time"
                    elif key in ["recipe", "recipeName"]:
                        mapped_key = "brew_name"
                    self._latest_data[mapped_key] = message[key]
        
        # Check for nested data/payload
        if "data" in message and isinstance(message["data"], dict):
            self._process_generic(message["data"])
        if "payload" in message and isinstance(message["payload"], dict):
            self._process_generic(message["payload"])
            
        self._notify_callback()
    
    def _notify_callback(self) -> None:
        """Notify the callback with updated data."""
        if self._on_data_callback:
            try:
                self._on_data_callback(self._latest_data)
            except Exception as err:
                _LOGGER.error("Error in data callback: %s", err)
    
    async def start(self) -> None:
        """Start the MQTT client with auto-reconnect."""
        while True:
            try:
                if await self.connect():
                    await self.listen()
            except asyncio.CancelledError:
                _LOGGER.info("MQTT client stopped")
                break
            except Exception as err:
                _LOGGER.error("MQTT client error: %s", err)
            
            # Reconnect delay
            _LOGGER.info("Reconnecting in 5 seconds...")
            await asyncio.sleep(5)
    
    async def stop(self) -> None:
        """Stop the MQTT client."""
        _LOGGER.info("Stopping MQTT client")
        self._running = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
            
        self._connected = False
    
    async def close(self) -> None:
        """Close the MQTT client and session."""
        await self.stop()
        
        if self._session:
            await self._session.close()
            self._session = None
