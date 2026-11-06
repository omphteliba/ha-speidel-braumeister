"""Heartbeat evidence and retained hazard state without any network requests."""

import pytest

from protocol_tests.connection_monitor import ConnectionMonitor


def sample(stamp=1000, **overrides):
    return {"connection_status": "online", "device_timestamp": stamp,
            "data_source": "bridge", "state_code": 4006,
            "pump": "on", "heating": "off", "heater_enabled": True,
            "process_status": "idle", **overrides}


def test_frozen_payload_expires_even_with_successful_polling_and_retains_regulation_risk():
    monitor = ConnectionMonitor()
    monitor.observe(sample(), 0)
    assert monitor.snapshot(0)["warning"] is None
    monitor.observe(sample(1030), 30)
    assert monitor.snapshot(149)["warning"] is False
    monitor.observe(sample(1030, heater_enabled=False), 150)
    result = monitor.snapshot(150)
    assert result["warning"] is True
    assert result["activity_at_risk"] is True
    assert result["last_known_pump"] == "on"
    assert result["last_known_heater_enabled"] is True
    monitor.observe(sample(1180, heater_enabled=False), 180)
    assert monitor.snapshot(180)["warning"] is False
    assert monitor.snapshot(180)["last_known_heater_enabled"] is False


def test_offline_defaults_cannot_replace_last_known_brew_with_idle():
    monitor = ConnectionMonitor()
    monitor.observe(sample(), 0)
    monitor.observe(sample(1030, process_status="running"), 30)
    monitor.observe({"connection_status": "offline", "process_status": "idle"}, 60)
    assert monitor.snapshot(150)["last_known_brewing"] is True
    assert monitor.snapshot(150)["activity_at_risk"] is True


def test_missing_activity_fields_do_not_clear_last_known_hazard():
    monitor = ConnectionMonitor()
    monitor.observe(sample(), 0)
    monitor.observe(sample(1030, process_status="running"), 30)
    monitor.observe(sample(1060, process_status="unknown", heater_enabled=None,
                           heating="unknown", pump="unknown"), 60)
    assert monitor.snapshot(180)["activity_at_risk"] is True
    assert monitor.snapshot(180)["last_known_brewing"] is True
    assert monitor.snapshot(180)["last_known_heater_enabled"] is True


@pytest.mark.parametrize("bad", [None, True, "1200", float("nan"), float("inf"), -1])
def test_invalid_samples_do_not_clear_alarm(bad):
    monitor = ConnectionMonitor()
    monitor.observe(sample(), 0)
    monitor.observe(sample(1030), 30)
    monitor.observe(sample(bad), 151)
    assert monitor.snapshot(151)["warning"] is True


def test_source_switch_and_clock_regression_need_new_advancing_evidence():
    monitor = ConnectionMonitor()
    monitor.observe(sample(), 0)
    monitor.observe(sample(1030), 30)
    monitor.observe(sample(1300, data_source="xhr"), 151)
    assert monitor.snapshot(151)["warning"] is True
    monitor.observe(sample(1301, data_source="xhr"), 152)
    assert monitor.snapshot(152)["warning"] is False
    monitor.observe(sample(10, data_source="xhr"), 280)
    assert monitor.snapshot(280)["warning"] is True
    monitor.observe(sample(11, data_source="xhr"), 281)
    assert monitor.snapshot(281)["warning"] is False


def test_cached_mqtt_and_no_initial_evidence_remain_unconfirmed_then_warn():
    monitor = ConnectionMonitor()
    monitor.observe(sample(data_source="mqtt"), 0)
    assert monitor.snapshot(119)["warning"] is None
    assert monitor.snapshot(120)["warning"] is True
    assert monitor.snapshot(120)["evidence"] == "unconfirmed"
    assert monitor.snapshot(120)["activity_at_risk"] is False


@pytest.mark.parametrize(("flags", "enabled"), [
    ("ph", False), ("Ph", False), ("pH", True), ("PH", True),
    ("pi", True), ("Pi", True), ("qi", True), ("qH", True), ("qh", False),
    ("", None), ("xH", None), ("PHx", None),
])
def test_heating_permission_including_regulation_and_pump_pause(dp, flags, enabled):
    fields = ["0", "12:00", "C", "4006", "420", "42", "0", "0", "0", "0",
              "0", "0", "0", "000", flags, "000"]
    parsed = dp.parse_bm_stat("v;TEST;1000;" + "X".join(fields))
    assert parsed["heater_enabled"] is enabled
