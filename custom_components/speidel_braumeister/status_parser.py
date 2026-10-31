"""Decode actuator indicators from the MySpeidel control status payload."""


def parse_actuator_status(data_parts: list[str]) -> dict[str, str]:
    """Read the case-sensitive pump/heater indicators at X-field 14.

    MySpeidel's bm_controll.min.js parseStatus reads a[14][0:2].
    updateScreen marks only P/H as current, and q/i as inactive.
    Represent known inactive indicators as off in the existing on/off model;
    missing or unrecognized indicators remain unknown, never inferred from
    the timer/counter fields at positions 7 and 8.
    """
    indicators = data_parts[14] if len(data_parts) > 14 else ""
    if len(indicators) > 2:
        return {"pump": "unknown", "heating": "unknown"}
    pump = indicators[0:1]
    heating = indicators[1:2]
    return {
        "pump": {"P": "on", "p": "off", "q": "off"}.get(pump, "unknown"),
        "heating": {"H": "on", "h": "off", "i": "off"}.get(heating, "unknown"),
    }
