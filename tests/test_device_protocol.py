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
        (2610, "running", "mash_in_temperature_reached"),
        (2820, "running", None),
        (2910, "running", "rest_end_reached"),
        (2960, "running", "rest_end_reached"),
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
    [(2820, "440", 44.0), (2820, "-1000", None), (2820, "-10000", None), (2960, "0", None), (101, "400", None)],
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
