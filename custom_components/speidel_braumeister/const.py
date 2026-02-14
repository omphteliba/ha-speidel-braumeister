"""Constants for the Speidel Braumeister integration."""

from typing import Final

from homeassistant.components.sensor import SensorEntityDescription

# Integration domain
DOMAIN: Final = "speidel_braumeister"

# Manufacturer and device info
MANUFACTURER: Final = "Speidel"
NAME: Final = "Braumeister"

# Configuration keys
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_MACHINE_UUID: Final = "machine_uuid"
CONF_SCAN_INTERVAL: Final = "scan_interval"

# Default values
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds

# API configuration
API_BASE_URL: Final = "https://api.cloud.myspeidel.com/v1.0"
WEB_API_BASE_URL: Final = "https://www.myspeidel.com/braumeister"
MQTT_URL: Final = "wss://api.cloud.myspeidel.com/mqtt"

# Sensor types using SensorEntityDescription
# Note: Names are provided via translations (strings.json and translations/*.json)
SENSOR_TYPES: Final[tuple[SensorEntityDescription, ...]] = (
    SensorEntityDescription(
        key="connection_status",
        translation_key="connection_status",
        icon="mdi:connection",
    ),
    SensorEntityDescription(
        key="payment_required",
        translation_key="payment_required",
        icon="mdi:credit-card-outline",
    ),
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        icon="mdi:thermometer",
        native_unit_of_measurement="°C",
        device_class="temperature",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="target_temperature",
        translation_key="target_temperature",
        icon="mdi:thermometer",
        native_unit_of_measurement="°C",
        device_class="temperature",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="pump_status",
        translation_key="pump_status",
        icon="mdi:pump",
    ),
    SensorEntityDescription(
        key="heating_status",
        translation_key="heating_status",
        icon="mdi:heating-coil",
    ),
    SensorEntityDescription(
        key="process_status",
        translation_key="process_status",
        icon="mdi:information-outline",
    ),
    SensorEntityDescription(
        key="current_phase",
        translation_key="current_phase",
        icon="mdi:format-list-bulleted-type",
    ),
    SensorEntityDescription(
        key="remaining_time",
        translation_key="remaining_time",
        icon="mdi:timer-outline",
        native_unit_of_measurement="min",
        device_class="duration",
    ),
    SensorEntityDescription(
        key="brew_name",
        translation_key="brew_name",
        icon="mdi:glass-mug-variant",
    ),
    SensorEntityDescription(
        key="device_type",
        translation_key="device_type",
        icon="mdi:kettle",
    ),
    SensorEntityDescription(
        key="device_mode",
        translation_key="device_mode",
        icon="mdi:state-machine",
    ),
    SensorEntityDescription(
        key="current_step",
        translation_key="current_step",
        icon="mdi:format-list-checks",
    ),
    SensorEntityDescription(
        key="progress",
        translation_key="progress",
        icon="mdi:percent",
        native_unit_of_measurement="%",
        state_class="measurement",
    ),
    SensorEntityDescription(
        key="last_online",
        translation_key="last_online",
        icon="mdi:clock-outline",
    ),
)

# Switch types
SWITCH_PUMP = "pump"
SWITCH_HEATING = "heating"

# Note: Names are provided via translations
SWITCH_TYPES: Final[dict[str, dict]] = {
    SWITCH_PUMP: {
        "translation_key": "pump",
        "icon": "mdi:pump",
    },
    SWITCH_HEATING: {
        "translation_key": "heating",
        "icon": "mdi:heating-coil",
    },
}

# Button types
BUTTON_START_PROCESS = "start_process"
BUTTON_STOP_PROCESS = "stop_process"
BUTTON_PAUSE_PROCESS = "pause_process"
BUTTON_NEXT_PHASE = "next_phase"

# Note: Names are provided via translations
BUTTON_TYPES: Final[dict[str, dict]] = {
    BUTTON_START_PROCESS: {
        "translation_key": "start_process",
        "icon": "mdi:play",
    },
    BUTTON_STOP_PROCESS: {
        "translation_key": "stop_process",
        "icon": "mdi:stop",
    },
    BUTTON_PAUSE_PROCESS: {
        "translation_key": "pause_process",
        "icon": "mdi:pause",
    },
    BUTTON_NEXT_PHASE: {
        "translation_key": "next_phase",
        "icon": "mdi:skip-next",
    },
}
