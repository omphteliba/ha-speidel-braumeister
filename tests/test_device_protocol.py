"""Tests for the bm_stat parser, based on real (anonymized) device messages."""

import json

import pytest

from conftest import FIXTURES

ENVELOPE = "V1.1.27 Sep 12 2018;1234567890ABCDEF;1793380000;{};00000000;00000000"


def status(fields: str) -> str:
    return ENVELOPE.format(fields)


def test_all_samples_parse(dp, samples):
    assert len(samples) >= 25
    for sample in samples:
        result = dp.parse_bm_stat(sample)
        assert result["device_uuid"] == "1234567890ABCDEF"
        assert result["firmware"] == "V1.1.27 Sep 12 2018"
        assert isinstance(result["temperature"], float)
        assert result["state_code"] is not None
        assert result["process_status"] in ("idle", "running", "finished")


@pytest.mark.parametrize(
    ("state", "process_status", "alarm"),
    [
        (101, "idle", None),
        (4006, "idle", None),
        (6010, "idle", None),
        (2030, "running", None),
        (2410, "running", None),
        (2510, "running", "mash_in_temperature_reached"),
        (2610, "running", None),  # waiting for malt, no beep in the samples
        (2820, "running", None),
        (2910, "running", "rest_end_reached"),
        (2960, "running", None),  # waiting after rest end, no beep
        (3070, "running", None),
        (3450, "finished", "brew_finished"),
    ],
)
def test_states_from_samples(dp, samples, state, process_status, alarm):
    matching = [r for r in map(dp.parse_bm_stat, samples) if r["state_code"] == state]
    assert matching, f"no sample for state {state}"
    for result in matching:
        assert result["process_status"] == process_status
        assert result["alarm"] == alarm


def test_remove_lid_alarm_from_indicator(dp, samples):
    lid = [r for r in map(dp.parse_bm_stat, samples) if r["state_code"] == 3010 and r["alarm"]]
    assert lid and all(r["alarm"] == "remove_lid" for r in lid)


@pytest.mark.parametrize(
    ("flags", "pump", "heating"),
    [("ph", "off", "off"), ("Ph", "on", "off"), ("pH", "off", "on"), ("PH", "on", "on"),
     ("qH", "off", "on"), ("Pi", "on", "off"), ("qi", "off", "off"), ("PHx", "unknown", "unknown")],
)
def test_actuator_flags(dp, flags, pump, heating):
    result = dp.parse_bm_stat(status(f"0X21:00XCX4006X380X 30.0X4800X5X5X0X0X0X0XAPHTX{flags}X000X0X0X0"))
    assert (result["pump"], result["heating"]) == (pump, heating)


def test_remaining_time_while_boiling(dp):
    # 20 min boil (1200 s), 1184 s elapsed -> 16 s left, rounded up to 1 min
    result = dp.parse_bm_stat(status("0X08:37XCX3070X1030X 101.5X1200X1184X5X2X5X-1X314XA00SXqHX000X0X0X0"))
    assert result["remaining_seconds"] == 16
    assert result["remaining_time"] == 1


def test_no_remaining_time_outside_timed_steps(dp):
    result = dp.parse_bm_stat(status("0X08:03XCX3010X1030X 88.0X1200X0X5X2X5X0X216XA00SXqHX000X0X0X0"))
    assert result["remaining_time"] is None


@pytest.mark.parametrize(
    ("state", "target_raw", "expected"),
    [(2820, "440", 44.0), (2820, "-1000", None), (2820, "-10000", None), (2960, "0", 0.0), (101, "400", None)],
)
def test_target_temperature(dp, state, target_raw, expected):
    result = dp.parse_bm_stat(status(f"0X21:00XCX{state}X{target_raw}X 40.0X60X5X5X2X0X0X0XA00SXPHX000X0X0X0"))
    assert result["target_temperature"] == expected


def test_recipe_slot_only_during_program(dp):
    running = dp.parse_bm_stat(status("0X07:37XCX2820X400X 40.5X60X16X5X2X0X0X55XA00SXPiX000X0X0X0"))
    manual = dp.parse_bm_stat(status("0X18:12XCX4006X380X 24.5X4800X0X1X4X0X0X0XAPHTXphX000X0X0X0"))
    assert running["recipe_slot"] == 2
    assert manual["recipe_slot"] is None


def test_url_encoded_with_prefix(dp):
    raw = status("0X18:12XCX101X-1000X 24.5X4800X82X1X0X0X0X0XEMSRXphX000X0X0X0")
    encoded = "bm_stat=" + raw.replace(" ", "%20")
    assert dp.parse_bm_stat(encoded) == dp.parse_bm_stat(raw)


def test_malformed(dp):
    assert dp.parse_bm_stat("garbage") == {}
    assert dp.parse_bm_stat("") == {}


def test_parse_rz(dp):
    payload = (
        "V1.1.27 Sep 12 2018;1234567890ABCDEF;1793380000;5\r\n"
        "0X40X44X20X52X20X63X35X73X35X78X10X90X103X90X15X0X0X0X0.Weizen\r\n"
        "2X40X40X1X0X0X0X0X0X0X0X0X20X103X10X11X11X0X0X0.test 10 minute;00000000;00000000"
    )
    assert dp.parse_rz(payload) == {0: "Weizen", 2: "test 10 minute"}


def test_from_bridge(dp):
    bm = status("0X07:37XCX2820X400X 40.5X60X16X5X2X0X0X55XA00SXPiX000X0X0X0")
    rz = "x;1234567890ABCDEF;1;5\r\n2X40X40X1X0X0X0X0X0X0X0X0X20X103X10X11X11X0X0X0.test 10 minute;0;0"
    payload = {"now": 1000.0, "devices": [
        {"device_id": "1234567890ABCDEF", "bm_stat": bm, "bm_stat_received": 990.0, "rz": rz},
    ]}
    result = dp.from_bridge(payload, "1234567890abcdef", max_age=30)
    assert result["state_code"] == 2820
    assert result["brew_name"] == "test 10 minute"
    assert dp.from_bridge({**payload, "now": 2000.0}, "1234567890ABCDEF", max_age=30) is None
    assert dp.from_bridge(payload, "FFFF", max_age=30) is None


def test_recipe_fixture_matches_raw_line():
    recipe = json.loads((FIXTURES / "recipe_test_10_minute.json").read_text(encoding="utf-8"))
    head, name = recipe["raw"].split(".", 1)
    values = [int(v) for v in head.split("X")]
    assert values[0] == recipe["slot"]
    assert values[1] == recipe["mash_in_temperature_c"]
    rests = [{"temperature_c": values[i], "minutes": values[i + 1]} for i in range(2, 12, 2) if values[i] or values[i + 1]]
    assert rests == recipe["rests"]
    assert values[12] == recipe["boil_minutes"]
    assert values[13] == recipe["boil_temperature_c"]
    assert [v for v in values[14:20] if v] == recipe["hop_additions_minutes_before_end"]
    assert name == recipe["name"] and len(name) <= 14


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ("test 10 minuten – 1. Rast", "test 10 minuten"),
        ("test 10 minuten - Rastende erreicht", "test 10 minuten"),
        ("Weizen – Einmaischen Temp. erreicht", "Weizen"),
        ("Automatik – test 10 minuten starten", None),
        ("Hauptmenü", None),
        (None, None),
    ],
)
def test_brew_name_from_step(dp, step, expected):
    assert dp.brew_name_from_step(step) == expected


@pytest.mark.parametrize(
    ("state", "indicator", "expected"),
    [
        (2910, "010", "rest_end_reached"),
        (2930, "000", None),
        (3010, "0D0", "remove_lid"),
        (3070, "020", "alarm"),
        (3080, "010", "hop_addition"),
        (2510, "010", "mash_in_temperature_reached"),
    ],
)
def test_alarm_follows_beep(dp, state, indicator, expected):
    result = dp.parse_bm_stat(status(f"0X10:04XCX{state}X0X 69.0X0X81X4X0X5X0X67XA00SXpiX{indicator}X0X0X0"))
    assert result["alarm"] == expected


@pytest.mark.parametrize(
    ("state", "raw", "expected"),
    [(2820, "60", 19), (2910, "67", 22), (3450, "318", 100), (101, "0", None)],
)
def test_progress_like_web_interface(dp, state, raw, expected):
    # Values from a live brew next to the MySpeidel web interface (19 %, 22 %)
    result = dp.parse_bm_stat(status(f"0X10:04XCX{state}X0X 69.0X0X81X4X0X5X0X{raw}XA00SXpiX000X0X0X0"))
    assert result["progress"] == expected


RZ = (
    "V1.1.27 Sep 12 2018;1234567890ABCDEF;1793380000;5\r\n"
    "0X40X44X20X52X20X63X35X73X35X78X10X90X103X90X15X0X0X0X0.Weizen\r\n"
    "2X40X40X1X40X0X40X0X40X0X40X0X20X103X10X15X11X0X0X0.test 10 minute;00000000;00000000"
)


def test_parse_recipes_from_rz(dp):
    recipes = dp.parse_recipes(RZ)
    assert [r["slot"] for r in recipes] == [0, 2]
    assert recipes[0] == {
        "slot": 0, "name": "Weizen", "mash_in_temperature": 40,
        "rests": [{"temperature": 44, "minutes": 20}, {"temperature": 52, "minutes": 20},
                  {"temperature": 63, "minutes": 35}, {"temperature": 73, "minutes": 35},
                  {"temperature": 78, "minutes": 10}],
        "boil_minutes": 90, "boil_temperature": 103, "hop_additions": [90, 15],
    }
    # Unused rests are reported as "40X0" by the device: 0 minutes = no rest
    assert recipes[1]["rests"] == [{"temperature": 40, "minutes": 1}]
    assert recipes[1]["hop_additions"] == [10, 15, 11]


def test_parse_recipe_line_matches_fixture(dp):
    recipe = json.loads((FIXTURES / "recipe_test_10_minute.json").read_text(encoding="utf-8"))
    parsed = dp.parse_recipe_line(recipe["raw"])
    assert parsed["boil_minutes"] == recipe["boil_minutes"]
    assert parsed["hop_additions"] == recipe["hop_additions_minutes_before_end"]
    assert dp.parse_recipe_line("V1.1.27 Sep 12 2018;1234567890ABCDEF;1;5") is None


def test_recipes_from_bridge_without_fresh_status(dp):
    status = {"now": 99999.0, "devices": [{"device_id": "1234567890ABCDEF", "rz": RZ, "rz_received": 1.0}]}
    assert [r["name"] for r in dp.recipes_from_bridge(status, "1234567890abcdef")] == ["Weizen", "test 10 minute"]
    assert dp.recipes_from_bridge(status, "FFFF") is None


def test_fahrenheit_converted_to_celsius(dp):
    # Seen live after switching the device to °F: 33.0 °C -> 91.5, target 40 °C -> 1040
    result = dp.parse_bm_stat(status("0X11:33XFX2030X1040X 91.5X300X7441X5X0X0X0X0XADUSXphX000X0X0X0"))
    assert result["device_temperature_unit"] == "°F"
    assert result["temperature"] == 33.1
    assert result["target_temperature"] == 40.0


def test_fahrenheit_boil_stays_plausible(dp):
    # 103 °C = 217.4 °F: must arrive as about 103 °C, not as an implausible 217
    result = dp.parse_bm_stat(status("0X11:33XFX3070X2174X 215.6X300X10X5X2X5X0X256XA00SXqHX000X0X0X0"))
    assert result["temperature"] == 102.0
    assert result["target_temperature"] == 103.0


def test_celsius_unchanged(dp):
    result = dp.parse_bm_stat(status("0X11:33XCX2030X400X 33.0X300X7441X5X0X0X0X0XADUSXphX000X0X0X0"))
    assert (result["temperature"], result["target_temperature"], result["device_temperature_unit"]) == (33.0, 40.0, "°C")


RZ_FAHRENHEIT = (
    "V1.1.27 Sep 12 2018;1234567890ABCDEF;1793380000;4\r\n"
    "0X104X104X1X0X0X0X0X0X0X0X0X5X217X3X2X1X0X0X0.test 10 minute\r\n"
    "1X104X111X20X125X20X145X35X163X35X172X10X90X217X90X15X0X0X0X0.Weizen;00000000;00000000"
)
BM_FAHRENHEIT = status("0X11:33XFX2610X1040X 105.0X300X256X4X0X0X0X14XA00SXphX000X0X0X0")


def test_fahrenheit_recipes_converted(dp):
    # Seen live after switching the device to °F: the recipe list arrives in °F too
    recipes = dp.parse_recipes(RZ_FAHRENHEIT, fahrenheit=True)
    weizen = recipes[1]
    assert weizen["mash_in_temperature"] == 40
    assert [r["temperature"] for r in weizen["rests"]] == [44, 52, 63, 73, 78]
    assert weizen["boil_temperature"] == 103
    assert recipes[0]["boil_temperature"] == 103
    assert dp.parse_recipes(RZ_FAHRENHEIT)[1]["mash_in_temperature"] == 104  # unit unknown: raw


def test_bridge_recipes_use_device_unit(dp):
    status_payload = {"now": 1000.0, "devices": [{"device_id": "1234567890ABCDEF", "bm_stat": BM_FAHRENHEIT,
                                                 "bm_stat_received": 999.0, "rz": RZ_FAHRENHEIT}]}
    assert dp.from_bridge(status_payload, "1234567890ABCDEF", 30)["device_recipe_details"][1]["mash_in_temperature"] == 40
    assert dp.recipes_from_bridge(status_payload, "1234567890ABCDEF")[1]["boil_temperature"] == 103
