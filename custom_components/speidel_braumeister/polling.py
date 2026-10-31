"""Adaptive polling and fast display flags (no Home Assistant dependencies)."""

CONF_ONLINE_INTERVAL = "online_scan_interval"
CONF_ACTIVE_INTERVAL = "active_scan_interval"
DEFAULT_ONLINE_INTERVAL = 10
DEFAULT_ACTIVE_INTERVAL = 5
METADATA_INTERVAL = 30
RECIPES_INTERVAL = 300
MQTT_MAX_AGE = 30


def configured_interval(data, options, key, default, minimum=3):
    """Prefer saved options, keeping legacy config-entry values as fallback."""
    value = options.get(key, data.get(key, default))
    try:
        return max(minimum, min(3600, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def display_flags(fields):
    """Decode field 3 and 15 as in MySpeidel parseStatus/updateScreen.

    Field 15: interrupt digit, beep digit (or D for cover), edit mode.
    Hop-addition screen: 3080 <= BrauStatus < 3450, unless interrupted.
    Unknown/missing flags must not be guessed to mean alarm off.
    """
    try:
        code = int(fields[3])
    except (IndexError, ValueError, TypeError):
        code = None
    flags = fields[15] if len(fields) > 15 else ""
    interrupt = int(flags[0]) if flags[:1] in tuple("0123456789") else None
    beep = flags[1:2]
    hop = code is not None and 3080 <= code < 3450 and interrupt == 0
    alarm = True if beep in ("1", "2", "D") or hop else False if beep == "0" and interrupt is not None else None
    return {"brew_status_code": code, "alarm": alarm}


def polling_state(data):
    """Select a cadence from fresh telemetry, not cached recipe names/timers."""
    if data.get("connection_status") != "online":
        return "offline"
    if data.get("alarm") is True:
        return "active"
    if any(str(data.get(k, "")).lower() in ("on", "ein", "true", "1") for k in ("pump", "heating")):
        return "active"
    code = data.get("brew_status_code")
    if isinstance(code, int):
        # Includes brewing dialogs/pauses and manual operation, even with P/H off.
        return "active" if 2020 < code < 3450 or code in (4006, 4007) else "online"
    if str(data.get("process_status", "")).lower() in ("running", "paused"):
        return "active"
    if str(data.get("device_mode", "")).lower() in ("automatic", "automatik", "manual", "manuell"):
        return "active"
    return "online"
