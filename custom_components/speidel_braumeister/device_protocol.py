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
  [4]  = target temperature x10, <= -1000 = none, 0 between steps (stale in main menu, ignored there)
  [5]  = current temperature (°C)
  [6]  = duration of the current program step in seconds (rest, boil)
  [7]  = seconds since the current state was entered
  [8]  = probably number of synced recipe slots
  [9]  = recipe slot of the running program
  [13] = screen/message code (EMSR, APHT, ADUS, A000, ...)
  [14] = actuator flags: "P"/"H" = pump/heater on; "p"/"q" and "h"/"i" = off
  [15] = interrupt, beep, edit mode: 2nd char "1"/"2" = beeping alarm, "D" = remove lid
"""

from __future__ import annotations

import math
from typing import Any, Optional
from urllib.parse import unquote

from .brew_display import brew_display

NO_TARGET_TEMPERATURE = -1000
STATE_MAIN_MENU = 101
STATE_BREW_FINISHED = 3450
PROGRESS_FULL = 318

# An alarm is active while the device beeps, as in MySpeidel's own web display:
# field 15, 2nd character: "1"/"2" = beep, "D" = remove lid (also beeps).
# The state code only names the alarm; unknown codes give a generic "alarm".
BEEP_INDICATORS = {"1", "2"}
LID_INDICATOR = "D"
ALARM_STATES = {
    2510: "mash_in_temperature_reached",
    2610: "mash_in_temperature_reached",
    2910: "rest_end_reached",
    3080: "hop_addition",
    3450: "brew_finished",
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


# Field 14 as read by MySpeidel's bm_controll.min.js: P/H are shown as active,
# q/i as inactive, p/h unmarked. Inactive maps to off in the on/off model.
PUMP_FLAGS = {"P": "on", "p": "off", "q": "off"}
HEATER_FLAGS = {"H": "on", "h": "off", "i": "off"}


def _actuators(flags: Optional[str]) -> tuple[str, str]:
    """Decode the pump and heater indicators of field 14."""
    flags = flags or ""
    if len(flags) > 2:
        return "unknown", "unknown"
    return PUMP_FLAGS.get(flags[0:1], "unknown"), HEATER_FLAGS.get(flags[1:2], "unknown")


STEP_SEPARATORS = (" – ", " - ")
STEP_PREFIXES_WITHOUT_RECIPE = {"automatik", "automatic", "manuell", "manual mode"}


def brew_name_from_step(step: Optional[str]) -> Optional[str]:
    """Recipe name from the web interface's step text, e.g. "Weizen – 1. Rast" -> "Weizen".

    The web interface shows the account recipe name of the running program; it is
    more reliable than looking up field 9 in the device's recipe list.
    """
    if not step:
        return None
    for separator in STEP_SEPARATORS:
        if separator in step:
            name = step.split(separator, 1)[0].strip()
            return None if name.lower() in STEP_PREFIXES_WITHOUT_RECIPE else name or None
    return None


def parse_recipe_line(line: str) -> Optional[dict[str, Any]]:
    """Decode one recipe slot line, e.g. ``0X40X44X20X…X0.Weizen``.

    20 numbers: slot, mash-in °C, 5 rests as (°C, minutes), boil minutes, boil °C,
    6 hop additions (minutes before the end of the boil). Unused rests have 0 minutes,
    unused hop additions are 0. Other lines (e.g. the rz header) give None.
    """
    head, _, name = line.split(";")[0].strip().partition(".")
    values = head.split("X")
    if not name or len(values) != 20 or not all(v.lstrip("-").isdigit() for v in values):
        return None
    v = [int(x) for x in values]
    return {
        "slot": v[0],
        "name": name.strip(),
        "mash_in_temperature": v[1],
        "rests": [{"temperature": v[i], "minutes": v[i + 1]} for i in range(2, 12, 2) if v[i + 1] > 0],
        "boil_minutes": v[12],
        "boil_temperature": v[13],
        "hop_additions": [m for m in v[14:20] if m > 0],
    }


def parse_recipes(text: str) -> list[dict[str, Any]]:
    """All recipe slots in an ``rz`` payload or a getDeviceRecipes response, sorted by slot."""
    recipes = [r for line in text.replace("\r\n", "\n").split("\n") if (r := parse_recipe_line(line))]
    return sorted(recipes, key=lambda r: r["slot"])


def parse_rz(payload: str) -> dict[int, str]:
    """Parse an ``rz`` payload (recipe slots) into {slot: name}."""
    return {r["slot"]: r["name"] for r in parse_recipes(payload)}


def recipes_from_bridge(status: dict[str, Any], device_id: str) -> Optional[list[dict[str, Any]]]:
    """This device's recipe slots from the bridge, also when the device is currently off."""
    for device in status.get("devices", []):
        if device.get("device_id", "").lower() == device_id.lower() and device.get("rz"):
            return parse_recipes(device["rz"])
    return None


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
        details = parse_recipes(device["rz"]) if device.get("rz") else []
        recipes = {r["slot"]: r["name"] for r in details}
        slot = parsed.get("recipe_slot")
        parsed["brew_name"] = recipes.get(slot) if slot is not None else None
        parsed["device_recipes"] = recipes
        parsed["device_recipe_details"] = details
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

    # In the main menu the device keeps reporting the last program's target, so it
    # is ignored there. "None" is -1000 (seen once as -10000). Between steps the
    # device reports 0, shown as 0 °C like MySpeidel's web interface does.
    target_raw = _int(fields, 4)
    result["target_temperature"] = (
        target_raw / 10
        if target_raw is not None
        and target_raw > NO_TARGET_TEMPERATURE
        and state_code != STATE_MAIN_MENU
        else None
    )

    # Field 9 holds the slot of the running program; outside a program it is
    # not meaningful (seen as 4 right after entering manual mode)
    result["recipe_slot"] = _int(fields, 9) if in_program else None

    # Field 12: program progress, 318 = 100 % (MySpeidel: progress = a[12] / 318 * 100,
    # rounded up to match the percentage the web interface shows)
    progress_raw = _int(fields, 12)
    result["progress"] = (
        min(math.ceil(progress_raw * 100 / PROGRESS_FULL), 100)
        if in_program and progress_raw is not None and progress_raw >= 0
        else None
    )

    flags = _field(fields, 14)
    result["pump"], result["heating"] = _actuators(flags)

    indicator = _field(fields, 15)
    beep = indicator[1] if indicator and len(indicator) > 1 else None
    if beep == LID_INDICATOR:
        result["alarm"] = "remove_lid"
    elif beep in BEEP_INDICATORS:
        result["alarm"] = ALARM_STATES.get(state_code, "alarm")
    else:
        result["alarm"] = None

    if state_code is None:
        result["process_status"] = "unknown"
    elif state_code == STATE_BREW_FINISHED:
        result["process_status"] = "finished"
    elif in_program:
        result["process_status"] = "running"
    else:
        result["process_status"] = "idle"

    result.update(brew_display(fields))
    return result
