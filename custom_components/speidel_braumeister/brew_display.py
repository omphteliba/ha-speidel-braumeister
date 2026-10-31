"""German display status derived from the firmware 1.1.27 portal screen logic.

Source: user-captured bm_controll.min.js buildScreen/parseStatus and German
bmtext on 2026-10-30. Unknown gaps deliberately retain their numeric code.
This describes the display, not a command or a prediction of device behavior.
"""


def brew_display(fields):
    def field(index):
        return str(fields[index]).strip() if index < len(fields) else ""

    def number(index):
        try:
            return int(field(index))
        except ValueError:
            return None

    code = number(3)
    flags = field(15)
    interrupt = int(flags[0]) if flags[:1].isdigit() else None
    cover = flags[1:2] == "D"
    if cover:
        interrupt = 1  # Same precedence as the portal's parseStatus.
    pump_pause = field(14).startswith("q")
    rest = number(10)
    hop = number(11)
    text = f"Statuscode {code}" if code is not None else "Status unbekannt"
    phase = None
    if code == 101:
        text = phase = "Hauptmenü"
    elif code is not None:
        if 2000 <= code <= 2020:
            text = phase = "Rezept auswählen"
        elif 2020 < code < 2200:
            phase, text = "Einmaischen", "Wasser eingefüllt?"
        elif 2200 <= code < 2400:
            phase, text = "Einmaischen", "Pumpe wird entlüftet"
        elif 2400 <= code < 2500:
            phase, text = "Einmaischen", "Aufheizen"
        elif 2510 <= code < 2610:
            phase = "Einmaischen"
            text = "Pumpenabschaltung" if pump_pause else "Einmaischtemperatur erreicht"
        elif 2610 <= code < 2810:
            phase = "Einmaischen"
            text = "Malz einfüllen!" if code < 2705 else "Malz eingefüllt?"
        elif 2810 <= code < 2910:
            phase = f"{rest + 1}. Rast" if rest is not None and 0 <= rest < 5 else "Rast"
            text = "Pumpenpause" if pump_pause else phase
        elif 2910 <= code < 2930:
            phase, text = "Maischen", "Rastende erreicht"
        elif 2930 <= code < 2960:
            phase, text = "Läutern", "Malzrohr entnehmen!"
        elif 2960 <= code < 3010:
            phase, text = "Hopfen kochen", "Start Hopfenkochen?"
        elif 3010 <= code < 3070:
            phase, text = "Hopfen kochen", "Aufheizen zum Kochen"
        elif 3070 <= code < 3080:
            text = phase = "Hopfen kochen"
        elif 3080 <= code < 3450:
            phase = "Hopfen kochen"
            text = f"Hopfen zugeben – {hop + 1}. Hopfengabe" if hop is not None and hop >= 0 else "Hopfen zugeben"
        elif 3450 <= code <= 3500:
            text = phase = "Brauvorgang beendet"
        elif 3500 < code <= 3600:
            text = phase = "Jetzt Whirlpool …"
        elif 3600 < code <= 3700:
            phase, text = "Brauvorgang beendet", "Prost!"
        elif code in (4006, 4007):
            text = phase = "Manueller Betrieb"
        elif code >= 8000:
            text = phase = "Einstellungen"
    if interrupt is not None and interrupt > 0:
        text = "Temperaturfehler" if interrupt > 1 else "Bitte Deckel entfernen." if cover else "Automatik angehalten"
    clock = field(1)
    clock_parts = clock.split(":")
    clock_valid = len(clock_parts) == 2 and all(p.isascii() and p.isdigit() for p in clock_parts) and len(clock_parts[0]) in (1, 2) and len(clock_parts[1]) == 2 and int(clock_parts[0]) < 24 and int(clock_parts[1]) < 60
    actuators = field(14)
    pump_flag = actuators[:1] if actuators[:1] in ("P", "p", "q") else None
    heater_flag = actuators[1:2] if actuators[1:2] in ("H", "h", "i") else None
    timed = code is not None and 2810 <= code < 2910
    target_seconds, elapsed_seconds = number(6), number(7)
    return {"display_clock": clock if clock_valid else None, "display_pump_flag": pump_flag, "display_heater_flag": heater_flag,
            "display_time_target_seconds": target_seconds if timed and target_seconds is not None and target_seconds >= 0 else None,
            "display_time_elapsed_seconds": elapsed_seconds if timed and elapsed_seconds is not None and elapsed_seconds >= 0 else None,
            "current_step": text, "display_phase": phase,
            "display_state_code": code, "display_interrupt": interrupt,
            "display_rest_number": rest + 1 if rest is not None and 0 <= rest < 5 else None,
            "display_hop_number": hop + 1 if hop is not None and hop >= 0 else None}
