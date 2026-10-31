"""Parser for the Braumeister device status message (``bm_stat``).

The device POSTs this message to the My Speidel cloud roughly every second, and
the web interface's XHR endpoint returns it unchanged. See
``docs/DEVICE_PROTOCOL.md`` for the field reference and which fields are still
hypotheses.

Envelope: firmware;device_id;unix_time;X-separated-status;constant;signature

Status fields (X-separated):
  [0]  = unknown (always 0)
  [1]  = device clock (HH:MM)
  [2]  = temperature unit ("C")
  [3]  = state / screen code (101 = main menu, 2xxx = mashing, 3xxx = boiling, 4xxx = manual mode)
  [4]  = target temperature x10, <= -1000 or 0 = none (stale in main menu, ignored there)
  [5]  = current temperature (°C)
  [6]  = duration of the current program step in seconds (rest, boil)
  [7]  = seconds since the current state was entered
  [8]  = probably number of synced recipe slots
  [9]  = recipe slot of the running program
  [13] = screen/message code (EMSR, APHT, ADUS, A000, ...)
  [14] = actuator flags: "P"/"p" = pump on/off, "H"/"h" = heater on/off
  [15] = alarm indicator: middle char "1" = alarm, "D" = remove lid
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import unquote

NO_TARGET_TEMPERATURE = -1000
STATE_MAIN_MENU = 101
STATE_BREW_FINISHED = 3450

# State codes in which the device shows an alarm and waits for the user.
# Only codes actually observed are listed; extend when new ones are seen.
ALARM_STATES = {
    2510: "mash_in_temperature_reached",
    2610: "mash_in_temperature_reached",
    2910: "rest_end_reached",
    2960: "rest_end_reached",
    3450: "brew_finished",
}

# Alarm indicator in field 15 (middle character), independent of the state code
ALARM_INDICATORS = {
    "D": "remove_lid",
}

# Automatic program: 2xxx = mashing, 3xxx = boiling
PROGRAM_STATES = range(2000, 4000)

# Timed steps: field 6 is the step duration, field 7 the elapsed seconds
TIMED_STATES = {
    2820,  # holding a rest
    3070,  # boiling
}


def _field(fields: list[str], idx: int) -> Optional[str]:
    if idx < len(fields):
        val = fields[idx].strip()
        return val or None
    return None


def _int(fields: list[str], idx: int) -> Optional[int]:
    val = _field(fields, idx)
    try:
        return int(float(val)) if val is not None else None
    except ValueError:
        return None


def _float(fields: list[str], idx: int) -> Optional[float]:
    val = _field(fields, idx)
    try:
        return float(val) if val is not None else None
    except ValueError:
        return None


def _flag(flags: Optional[str], idx: int, letter: str) -> str:
    """Decode one actuator flag: upper case = on, lower case = off."""
    if not flags or idx >= len(flags) or flags[idx].lower() != letter:
        return "unknown"
    return "on" if flags[idx].isupper() else "off"


def parse_rz(payload: str) -> dict[int, str]:
    """Parse an ``rz`` payload (recipe slots) into {slot: name}."""
    recipes: dict[int, str] = {}
    for line in payload.replace("\r\n", "\n").split("\n")[1:]:
        line = line.split(";")[0]
        head, _, name = line.partition(".")
        slot = head.split("X")[0]
        if name and slot.isdigit():
            recipes[int(slot)] = name.strip()
    return recipes


def from_bridge(status: dict[str, Any], device_id: str, max_age: float) -> dict[str, Any] | None:
    """Pick this device's latest bm_stat from the Braumeister Bridge app's /api/status."""
    now = status.get("now", 0)
    for device in status.get("devices", []):
        if device.get("device_id", "").lower() != device_id.lower():
            continue
        if not device.get("bm_stat") or now - device.get("bm_stat_received", 0) > max_age:
            return None
        parsed = parse_bm_stat(device["bm_stat"])
        if not parsed:
            return None
        recipes = parse_rz(device["rz"]) if device.get("rz") else {}
        slot = parsed.get("recipe_slot")
        parsed["brew_name"] = recipes.get(slot) if slot is not None else None
        parsed["device_recipes"] = recipes
        return parsed
    return None


def parse_bm_stat(data_string: str) -> dict[str, Any]:
    """Parse a bm_stat message. Returns an empty dict if it is malformed."""
    data_string = data_string.strip()
    if data_string.startswith("bm_stat="):
        data_string = data_string[len("bm_stat="):]
    if "%" in data_string:
        data_string = unquote(data_string)

    parts = data_string.split(";")
    if len(parts) < 4:
        return {}

    fields = parts[3].split("X")

    result: dict[str, Any] = {
        "firmware": parts[0],
        "device_uuid": parts[1],
        "device_timestamp": _int(parts, 2),
        "time_display": _field(fields, 1),
        "state_code": _int(fields, 3),
        "temperature": _float(fields, 5),
        "state_seconds": _int(fields, 7),
        "recipe_count": _int(fields, 8),
        "display_code": _field(fields, 13),
        "remaining_time": None,
        "remaining_seconds": None,
    }

    state_code = result["state_code"]
    in_program = state_code is not None and state_code in PROGRAM_STATES

    # Remaining time of a timed step (rest, boil): step duration minus elapsed
    duration, elapsed = _int(fields, 6), result["state_seconds"]
    if state_code in TIMED_STATES and duration and elapsed is not None:
        remaining = max(duration - elapsed, 0)
        result["remaining_seconds"] = remaining
        result["remaining_time"] = -(-remaining // 60)  # minutes, rounded up

    # In the main menu the device keeps reporting the last program's target,
    # and between steps it reports 0. "None" is -1000 (seen once as -10000).
    target_raw = _int(fields, 4)
    result["target_temperature"] = (
        target_raw / 10
        if target_raw is not None
        and target_raw != 0
        and target_raw > NO_TARGET_TEMPERATURE
        and state_code != STATE_MAIN_MENU
        else None
    )

    # Field 9 holds the slot of the running program; outside a program it is
    # not meaningful (seen as 4 right after entering manual mode)
    result["recipe_slot"] = _int(fields, 9) if in_program else None

    flags = _field(fields, 14)
    result["pump"] = _flag(flags, 0, "p")
    result["heating"] = _flag(flags, 1, "h")

    indicator = _field(fields, 15)
    result["alarm"] = (
        ALARM_STATES.get(state_code)
        or (ALARM_INDICATORS.get(indicator[1]) if indicator and len(indicator) > 1 else None)
    )

    if state_code is None:
        result["process_status"] = "unknown"
    elif state_code == STATE_BREW_FINISHED:
        result["process_status"] = "finished"
    elif in_program:
        result["process_status"] = "running"
    else:
        result["process_status"] = "idle"

    return result
