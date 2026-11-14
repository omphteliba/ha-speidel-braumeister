"""Diagnostics download ("Download diagnostics") for the Speidel Braumeister integration.

Meant for owners of devices we cannot test ourselves (e.g. a Braumeister PLUS
50 L with firmware 1.8.3): one file with what each data source returned, without account data.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MACHINE_UUID, CONF_PASSWORD, CONF_USERNAME, DOMAIN

# Keys removed wherever they appear (account data, IDs, signatures, tokens)
TO_REDACT = {
    CONF_USERNAME, CONF_PASSWORD, CONF_MACHINE_UUID, "password", "pass", "email",
    "token", "access_token", "session", "session_value", "user_id", "userId",
    "account_id", "accountId", "recipe_account_id", "device_uuid", "machine_uuid",
    "machineUuid", "machine_id", "uuid", "id", "serial", "signature", "remote",
    "device_name", "name_by_user", "bm_stat", "alarm_bm_stat", "rz",
}

# Long hex IDs and UUIDs inside free text (e.g. URL paths in the status keys)
_ID_PATTERN = re.compile(r"[0-9A-Fa-f]{16,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _scrub(value: Any) -> Any:
    """Mask IDs in strings and dict keys that redaction by key cannot reach."""
    if isinstance(value, str):
        return _ID_PATTERN.sub("**ID**", value)
    if isinstance(value, dict):
        return {_scrub(k) if isinstance(k, str) else k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def build_diagnostics(coordinator: Any, entry_data: dict[str, Any], version: str) -> dict[str, Any]:
    """Collect the coordinator state; separate from HA for testing."""
    data = dict(coordinator.data or {})
    api = getattr(coordinator, "api", None)
    mqtt = getattr(coordinator, "mqtt_client", None)
    machine = str(entry_data.get(CONF_MACHINE_UUID, ""))
    result = {
        "integration_version": version,
        "local_only": getattr(coordinator, "local_only", False),
        "machine_id_format": (
            "combined" if "." in machine else "uuid" if len(machine) == 36
            else "short" if machine.isdigit() else "other"
        ),
        "config_entry": entry_data,
        "data_source": data.get("data_source"),
        "connection_status": data.get("connection_status"),
        "firmware": data.get("firmware"),
        "device_type": data.get("device_type"),
        "last_update_success": getattr(coordinator, "last_update_success", None),
        "cloud_api": {
            "has_subscription": getattr(api, "has_subscription", None),
            "payment_required": getattr(api, "payment_required", None),
            "timeseries": getattr(coordinator, "cloud_series", None),
        },
        "mqtt": {
            "connected": getattr(mqtt, "connected", None),
            "latest_data": getattr(mqtt, "latest_data", None),
        } if mqtt else None,
        "data": data,
    }
    return _scrub(async_redact_data(result, TO_REDACT))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    # Fetch the cloud timeseries now, so the file shows them even when another
    # source (Bridge, web interface) delivers the data and they are never polled.
    api = getattr(coordinator, "api", None)
    if api is not None:
        try:
            coordinator.cloud_series = await api.get_timeseries(coordinator.machine_uuid)
        except Exception as err:  # noqa: BLE001 - diagnostics must not fail
            coordinator.cloud_series = {"error": type(err).__name__}
    integration = await _version(hass)
    return build_diagnostics(coordinator, dict(entry.data), integration)


async def _version(hass: HomeAssistant) -> str:
    from homeassistant.loader import async_get_integration

    try:
        return str((await async_get_integration(hass, DOMAIN)).version)
    except Exception:  # noqa: BLE001
        return "unknown"
