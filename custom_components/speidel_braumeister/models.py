"""Pydantic v2 models for Speidel Braumeister API.

These models provide type-safe parsing and validation for all API responses.
Compatible with Home Assistant 2025.1+ which includes Pydantic v2.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, List

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# ENUMS
# =============================================================================

class ConnectionStatus(str, Enum):
    """Device connection status."""
    ONLINE = "online"
    OFFLINE = "offline"
    INVALID_UUID = "invalid_uuid"


class BrewPhase(str, Enum):
    """Brewing phases (German terms from Braumeister)."""
    EINMAISCHEN = "Einmaischen"      # Mashing in
    RAST = "Rast"                     # Rest/mash rest
    KOCHEN = "Kochen"                 # Boiling
    ABMAISCHEN = "Abmaischen"         # Mash out
    LAEGERRUHE = "Lägerruhe"          # Resting
    HEFE = "Hefe"                     # Yeast
    IDLE = "idle"                     # Not brewing


class ProcessStatus(str, Enum):
    """Brewing process status."""
    RUNNING = "running"
    IDLE = "idle"
    FINISHED = "finished"
    ABORTED = "aborted"
    USER_ABORT = "user abort"
    PAUSED = "paused"
    UNKNOWN = "unknown"


class DeviceMode(str, Enum):
    """Device operating mode."""
    AUTOMATIK = "Automatik"           # Automatic mode
    MANUELL = "Manuell"               # Manual mode
    WARTET = "wartet"                 # Waiting
    IDLE = "idle"


class OnOffStatus(str, Enum):
    """On/Off status (German: Ein/Aus)."""
    ON = "Ein"
    OFF = "Aus"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_value(cls, value: Any) -> "OnOffStatus":
        """Convert various representations to OnOffStatus."""
        if isinstance(value, bool):
            return cls.ON if value else cls.OFF
        if isinstance(value, (int, float)):
            return cls.ON if value else cls.OFF
        if isinstance(value, str):
            value_lower = value.lower()
            if value_lower in ("ein", "on", "true", "1"):
                return cls.ON
            if value_lower in ("aus", "off", "false", "0"):
                return cls.OFF
        return cls.UNKNOWN
    
    @property
    def is_on(self) -> bool:
        """Check if status is on."""
        return self == self.ON


# =============================================================================
# AUTH MODELS
# =============================================================================

class AuthResponse(BaseModel):
    """Authentication response from the API."""
    
    token: str = Field(..., description="JWT authentication token")
    user_id: str = Field(..., alias="userid", description="User ID")
    subscription_id: Optional[str] = Field(
        None, 
        alias="subscription_id",
        description="Subscription ID if user has one"
    )
    subscription_end: Optional[str] = Field(
        None,
        alias="subscription_end", 
        description="Subscription end date"
    )
    
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }
    
    @field_validator("user_id", mode="before")
    @classmethod
    def convert_userid_to_str(cls, v: Any) -> str:
        """Convert userid to string (API may return int)."""
        if isinstance(v, int):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v) if v is not None else ""
    
    @property
    def has_subscription(self) -> bool:
        """Check if user has an active subscription."""
        return self.subscription_id is not None


# =============================================================================
# DEVICE STATUS MODELS
# =============================================================================

class DeviceStatus(BaseModel):
    """Real-time device status from XHR polling."""
    
    temperature: Optional[float] = Field(
        None, 
        description="Current temperature in °C"
    )
    target_temperature: Optional[float] = Field(
        None,
        alias="targetTemp",
        description="Target temperature in °C"
    )
    pump: OnOffStatus = Field(
        default=OnOffStatus.UNKNOWN,
        description="Pump status"
    )
    heating: OnOffStatus = Field(
        default=OnOffStatus.UNKNOWN,
        description="Heating element status"
    )
    process_status: ProcessStatus = Field(
        default=ProcessStatus.UNKNOWN,
        alias="status",
        description="Current brewing process status"
    )
    current_phase: Optional[BrewPhase] = Field(
        None,
        alias="phase",
        description="Current brewing phase"
    )
    remaining_time: Optional[int] = Field(
        None,
        alias="remainingTime",
        description="Remaining time in seconds"
    )
    brew_name: Optional[str] = Field(
        None,
        alias="name",
        description="Name of current brew/recipe"
    )
    connection_status: ConnectionStatus = Field(
        default=ConnectionStatus.OFFLINE,
        description="Connection status"
    )
    device_type: Optional[str] = Field(
        None,
        alias="deviceType",
        description="Device model (e.g., 'Braumeister 20 Liter')"
    )
    device_mode: Optional[DeviceMode] = Field(
        None,
        alias="mode",
        description="Current device operating mode"
    )
    current_step: Optional[str] = Field(
        None,
        alias="step",
        description="Full step name"
    )
    progress: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="Brewing progress percentage"
    )
    
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }
    
    @field_validator("pump", "heating", mode="before")
    @classmethod
    def parse_on_off(cls, v: Any) -> OnOffStatus:
        """Parse various on/off representations."""
        return OnOffStatus.from_value(v)
    
    @field_validator("process_status", mode="before")
    @classmethod
    def parse_process_status(cls, v: Any) -> ProcessStatus:
        """Parse process status from various formats."""
        if isinstance(v, ProcessStatus):
            return v
        if isinstance(v, str):
            v_lower = v.lower()
            for status in ProcessStatus:
                if status.value == v_lower:
                    return status
        return ProcessStatus.UNKNOWN
    
    @model_validator(mode="after")
    def set_connection_status(self) -> "DeviceStatus":
        """Auto-determine connection status based on data."""
        if self.connection_status == ConnectionStatus.OFFLINE:
            if self.temperature is not None or self.process_status != ProcessStatus.UNKNOWN:
                self.connection_status = ConnectionStatus.ONLINE
        return self
    
    @property
    def is_brewing(self) -> bool:
        """Check if currently brewing."""
        return self.process_status == ProcessStatus.RUNNING
    
    @property
    def remaining_time_formatted(self) -> str:
        """Format remaining time as HH:MM:SS."""
        if self.remaining_time is None:
            return "--:--:--"
        hours, remainder = divmod(self.remaining_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class DeviceStatusControl(DeviceStatus):
    """Device status from getDeviceStatusControl endpoint.
    
    Extends DeviceStatus with additional metadata fields.
    """
    
    machine_id: Optional[str] = Field(
        None,
        alias="machineId",
        description="Machine identifier"
    )
    last_online: Optional[datetime] = Field(
        None,
        alias="lastOnline",
        description="Last online timestamp"
    )
    firmware_version: Optional[str] = Field(
        None,
        alias="firmware",
        description="Device firmware version"
    )


# =============================================================================
# RECIPE MODELS
# =============================================================================

class RecipeSlot(BaseModel):
    """Recipe stored in a device slot (0-8)."""
    
    slot: int = Field(..., ge=0, le=4, description="Slot number")
    name: str = Field(..., description="Recipe name")
    style: Optional[str] = Field(None, description="Beer style")
    created_at: Optional[datetime] = Field(
        None,
        alias="created",
        description="Recipe creation date"
    )
    account_recipe_id: Optional[str] = Field(
        None,
        alias="recipeId",
        description="Account recipe ID if matched"
    )
    is_matched: bool = Field(
        default=False,
        alias="matched",
        description="Whether recipe matched account recipe"
    )
    
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


class AccountRecipe(BaseModel):
    """Recipe from user's My Speidel account."""
    
    id: str = Field(..., description="Recipe ID")
    name: str = Field(..., alias="recipeName", description="Recipe name")
    style: Optional[str] = Field(None, description="Beer style")
    created_at: Optional[datetime] = Field(
        None,
        alias="createdAt",
        description="Creation date"
    )
    updated_at: Optional[datetime] = Field(
        None,
        alias="updatedAt", 
        description="Last update date"
    )
    abv: Optional[float] = Field(None, description="Alcohol by volume")
    ibu: Optional[float] = Field(None, description="International Bitterness Units")
    og: Optional[float] = Field(None, description="Original gravity")
    fg: Optional[float] = Field(None, description="Final gravity")
    
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


# =============================================================================
# MACHINE MODELS
# =============================================================================

class Machine(BaseModel):
    """Braumeister machine information."""
    
    id: str = Field(..., description="Machine ID")
    uuid: Optional[str] = Field(None, description="Full machine UUID")
    name: Optional[str] = Field(None, alias="machineName", description="Machine name")
    device_type: Optional[str] = Field(
        None,
        alias="deviceType",
        description="Device type/model"
    )
    volume: Optional[int] = Field(None, description="Volume in liters (10, 20, 50, 100)")
    is_online: bool = Field(False, alias="online", description="Online status")
    last_seen: Optional[datetime] = Field(
        None,
        alias="lastSeen",
        description="Last online timestamp"
    )
    
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }
    
    @field_validator("id", mode="before")
    @classmethod
    def convert_id_to_str(cls, v: Any) -> str:
        """Convert id to string (API may return int)."""
        if isinstance(v, int):
            return str(v)
        return str(v) if v is not None else ""
    
    @property
    def combined_uuid(self) -> Optional[str]:
        """Get combined UUID format (long_uuid.short_id)."""
        if self.uuid and "." not in self.uuid:
            return f"{self.uuid}.{self.id}"
        return self.uuid or self.id


class MachineList(BaseModel):
    """List of machines for an account."""
    
    machines: List[Machine] = Field(default_factory=list)
    
    @model_validator(mode="before")
    @classmethod
    def parse_list(cls, v: Any) -> dict:
        """Parse list response into machines list."""
        if isinstance(v, list):
            return {"machines": v}
        return v


# =============================================================================
# TIME SERIES MODELS (Historical Data)
# =============================================================================

class SensorReading(BaseModel):
    """Single sensor reading from timeseries."""
    
    timestamp: datetime = Field(..., alias="time", description="Reading timestamp")
    sensor_type: str = Field(..., alias="type", description="Sensor type")
    value: float = Field(..., description="Sensor value")
    
    model_config = {
        "populate_by_name": True,
    }


class ActorReading(BaseModel):
    """Single actor (pump/heater) reading from timeseries."""
    
    timestamp: datetime = Field(..., alias="time", description="Reading timestamp")
    actor_type: str = Field(..., alias="type", description="Actor type")
    value: float = Field(..., description="Actor value (0 or 1)")
    
    model_config = {
        "populate_by_name": True,
    }


class ProcessPhase(BaseModel):
    """A phase within a brewing process."""
    
    phase_type: str = Field(..., alias="type", description="Phase type")
    start_time: Optional[datetime] = Field(None, alias="start", description="Start time")
    end_time: Optional[datetime] = Field(None, alias="end", description="End time")
    target_temp: Optional[float] = Field(None, alias="targetTemp", description="Target temperature")
    duration: Optional[int] = Field(None, description="Duration in seconds")
    
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }


class BrewingProcess(BaseModel):
    """A brewing process with phases."""
    
    id: str = Field(..., description="Process ID")
    status: ProcessStatus = Field(..., description="Process status")
    machine_id: Optional[str] = Field(None, alias="machine", description="Machine ID")
    recipe_name: Optional[str] = Field(None, description="Recipe name")
    phases: List[ProcessPhase] = Field(default_factory=list)
    start_time: Optional[datetime] = Field(None, alias="start", description="Start time")
    end_time: Optional[datetime] = Field(None, alias="end", description="End time")
    
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }
    
    @property
    def current_phase(self) -> Optional[ProcessPhase]:
        """Get the current (latest) phase."""
        if self.phases:
            return self.phases[-1]
        return None


# =============================================================================
# API RESPONSE WRAPPERS
# =============================================================================

class APIResponse(BaseModel):
    """Generic API response wrapper."""
    
    success: bool = Field(True, description="Whether request succeeded")
    data: Optional[Any] = Field(None, description="Response data")
    error: Optional[str] = Field(None, description="Error message if failed")
    
    @model_validator(mode="after")
    def check_success(self) -> "APIResponse":
        """Set success based on presence of error."""
        if self.error:
            self.success = False
        return self


class DeviceDataResult(BaseModel):
    """Aggregated device data result.
    
    This is the main data structure returned by get_latest_data().
    Combines data from multiple sources into a single coherent model.
    """
    
    # Core metrics
    temperature: Optional[float] = None
    target_temperature: Optional[float] = None
    pump: OnOffStatus = OnOffStatus.UNKNOWN
    heating: OnOffStatus = OnOffStatus.UNKNOWN
    
    # Process info
    process_status: ProcessStatus = ProcessStatus.UNKNOWN
    current_phase: Optional[BrewPhase] = None
    remaining_time: Optional[int] = None
    remaining_seconds: Optional[int] = None
    brew_name: Optional[str] = None
    progress: Optional[float] = None
    
    # Device info
    device_type: Optional[str] = None
    device_name: Optional[str] = None
    device_mode: Optional[DeviceMode] = None
    current_step: Optional[str] = None
    current_stage: Optional[str] = None
    
    # Connection
    connection_status: ConnectionStatus = ConnectionStatus.OFFLINE
    uuid_valid: bool = True
    last_online: Optional[datetime] = None
    
    # Recipe info
    recipe: Optional[RecipeSlot] = None
    recipe_slot: Optional[int] = None
    recipe_matched: bool = False
    recipe_account_id: Optional[str] = None
    recipe_date: Optional[str] = None
    recipe_style: Optional[str] = None
    
    # Metadata
    payment_required: bool = False
    data_source: str = Field(
        default="unknown",
        description="Source of data (xhr, mqtt, cloud_api)"
    )
    
    model_config = {
        "populate_by_name": True,
        "extra": "ignore",
    }
    
    @field_validator("pump", "heating", mode="before")
    @classmethod
    def parse_on_off(cls, v: Any) -> OnOffStatus:
        """Parse various on/off representations."""
        return OnOffStatus.from_value(v)
    
    @property
    def is_online(self) -> bool:
        """Check if device is online."""
        return self.connection_status == ConnectionStatus.ONLINE
    
    @property
    def is_brewing(self) -> bool:
        """Check if actively brewing."""
        return self.process_status == ProcessStatus.RUNNING
    
    @property
    def remaining_time_formatted(self) -> str:
        """Format remaining time."""
        if self.remaining_time is None:
            return "--:--:--"
        hours, remainder = divmod(self.remaining_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    @property
    def progress_percent(self) -> int:
        """Get progress as integer percentage."""
        return int(self.progress or 0)
    
    def merge_mqtt_data(self, mqtt_data: dict[str, Any]) -> "DeviceDataResult":
        """Merge MQTT data into this result (MQTT takes precedence)."""
        return DeviceDataResult.model_validate({
            **self.model_dump(),
            **mqtt_data,
            "connection_status": ConnectionStatus.ONLINE,
            "data_source": "mqtt" if mqtt_data else self.data_source,
        })
