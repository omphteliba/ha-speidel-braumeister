"""Read-only status from the My Speidel Cloud API v1.0 timeseries.

The API (https://api.cloud.myspeidel.com/v1.0/api-docs) has no live-status endpoint,
only timeseries of processes, phases, sensor and actor readouts. It is most likely fed
by the PLUS models with the new electronics (Linux controller, firmware 0.x-2.x); for
devices with firmware V1.x (api2.myspeidel.com) all timeseries are empty.

The spec documents the process status values, but sensor/actor ``type`` strings and
their ``values`` objects are free-form. The mapping below is therefore a best guess
that is meant to be checked against real data (see docs/NEW_DEVICES.md); everything
unrecognised is left out instead of being guessed further.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Readouts older than this mean the device is not sending (seconds)
FRESH_SECONDS = 300

PROCESS_STATUS = {
    "running": "running",
    "finished": "finished",
    "aborted": "idle",
    "user abort": "idle",
}

# Preferred keys inside a readout's ``values`` object
VALUE_KEYS = ("value", "temperature", "temp", "celsius", "current", "state", "on", "active")


def parse_ts(value: Any) -> Optional[datetime]:
    """ISO 8601 date-time (as documented) or epoch milliseconds."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _items(data: Any) -> list[dict[str, Any]]:
    """Spec: a JSON list. Tolerate a ``collection`` wrapper as used by /firmware."""
    if isinstance(data, dict):
        data = data.get("collection")
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def latest(data: Any, key: str = "ts") -> Optional[dict[str, Any]]:
    """The newest item by ``key`` (``ts`` for readouts, ``start`` for processes/phases)."""
    dated = [(parse_ts(item.get(key)), item) for item in _items(data)]
    dated = [(ts, item) for ts, item in dated if ts is not None]
    return max(dated, key=lambda pair: pair[0])[1] if dated else None


def latest_by_type(data: Any) -> dict[str, dict[str, Any]]:
    """Newest readout per sensor/actor type."""
    result: dict[str, dict[str, Any]] = {}
    for item in _items(data):
        kind, ts = item.get("type"), parse_ts(item.get("ts"))
        if not isinstance(kind, str) or ts is None:
            continue
        if kind not in result or ts > parse_ts(result[kind]["ts"]):
            result[kind] = item
    return result


def _value(readout: dict[str, Any]) -> Any:
    values = readout.get("values")
    if not isinstance(values, dict) or not values:
        return None
    for key in VALUE_KEYS:
        if key in values:
            return values[key]
    return next(iter(values.values())) if len(values) == 1 else None


def _find(readouts: dict[str, dict[str, Any]], *words: str) -> Optional[dict[str, Any]]:
    for kind, readout in sorted(readouts.items()):
        if any(word in kind.lower() for word in words):
            return readout
    return None


def _on_off(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        return "on" if value > 0 else "off"
    if isinstance(value, str) and value.lower() in ("on", "off", "true", "false", "1", "0"):
        return "on" if value.lower() in ("on", "true", "1") else "off"
    return None


def from_timeseries(series: dict[str, Any], now: Optional[datetime] = None) -> dict[str, Any]:
    """Map the latest timeseries items to the coordinator's data keys.

    ``series`` holds the raw answers: ``process``, ``phase``, ``sensor``, ``actor``.
    Returns only keys that could be derived; an empty dict means no usable data.
    """
    now = now or datetime.now(timezone.utc)
    result: dict[str, Any] = {}

    process = latest(series.get("process"), "start")
    if process:
        status = PROCESS_STATUS.get(str(process.get("status")).lower())
        if status:
            result["process_status"] = status
        metadata = process.get("metadata")
        if status == "running" and isinstance(metadata, dict):
            name = metadata.get("recipeName") or metadata.get("recipe_name") or metadata.get("name")
            if isinstance(name, str) and name:
                result["brew_name"] = name

    phase = latest(series.get("phase"), "start")
    if phase and isinstance(phase.get("type"), str) and not phase.get("end"):
        result["current_phase"] = phase["type"]

    sensors = latest_by_type(series.get("sensor"))
    actors = latest_by_type(series.get("actor"))

    temperature = _find(sensors, "temp")
    if temperature:
        value = _value(temperature)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result["temperature"] = float(value)
    target = _find(sensors, "target", "setpoint", "soll")
    if target:
        value = _value(target)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result["target_temperature"] = float(value)
    for key, words in (("pump", ("pump", "pumpe")), ("heating", ("heat", "heiz"))):
        readout = _find(actors, *words)
        state = _on_off(_value(readout)) if readout else None
        if state:
            result[key] = state

    newest = [parse_ts(r.get("ts")) for r in [*sensors.values(), *actors.values()]]
    newest = [ts for ts in newest if ts is not None]
    if newest:
        last = max(newest)
        result["device_timestamp"] = int(last.timestamp())
        fresh = (now - last).total_seconds() <= FRESH_SECONDS
        result["connection_status"] = "online" if fresh else "offline"
        if not fresh:
            # Old readouts are history, not the current device state
            for key in ("temperature", "target_temperature", "pump", "heating"):
                result.pop(key, None)
    if result:
        result["data_source"] = "cloud_timeseries"
    return result
