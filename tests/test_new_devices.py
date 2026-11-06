"""Cloud API v1.0 timeseries mapping and diagnostics for devices we cannot test ourselves."""
import importlib
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from conftest import ROOT, _load
from test_brew_display import load_coordinator

ct = _load("protocol_tests.cloud_timeseries",
           ROOT / "custom_components" / "speidel_braumeister" / "cloud_timeseries.py")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def series(ts="2026-11-06T11:59:30.000Z"):
    return {
        "process": [
            {"id": "proc-0001", "type": "brew", "status": "finished", "start": "2026-11-01T08:00:00Z"},
            {"id": "proc-0002", "type": "brew", "status": "running", "start": "2026-11-06T08:00:00Z",
             "metadata": {"recipeName": "West Coast IPA"}},
        ],
        "phase": [
            {"id": "phase-001", "type": "mash", "start": "2026-11-06T08:00:00Z", "end": "2026-11-06T10:00:00Z"},
            {"id": "phase-002", "type": "boil", "start": "2026-11-06T11:00:00Z"},
        ],
        "sensor": [
            {"id": "sens-0001", "type": "temperature", "ts": "2026-11-06T10:58:00Z", "values": {"value": 99.0}},
            {"id": "sens-0002", "type": "temperature", "ts": ts, "values": {"value": 100.5}},
        ],
        "actor": [
            {"id": "act-00001", "type": "pump", "ts": ts, "values": {"state": False}},
            {"id": "act-00002", "type": "heater", "ts": ts, "values": {"state": 1}},
        ],
    }


def test_latest_values_mapped():
    result = ct.from_timeseries(series(), NOW)
    assert result["process_status"] == "running"
    assert result["brew_name"] == "West Coast IPA"
    assert result["current_phase"] == "boil"
    assert result["temperature"] == 100.5
    assert (result["pump"], result["heating"]) == ("off", "on")
    assert result["connection_status"] == "online"
    assert result["data_source"] == "cloud_timeseries"


def test_old_readouts_are_not_current_state():
    result = ct.from_timeseries(series(ts="2026-11-06T11:00:00Z"), NOW)
    assert result["connection_status"] == "offline"
    assert not {"temperature", "pump", "heating"} & result.keys()


@pytest.mark.parametrize("answer", [None, [], {"collection": []}, "Not found", [{"type": "x"}]])
def test_empty_or_unknown_answers_give_nothing(answer):
    assert ct.from_timeseries({"process": answer, "phase": answer, "sensor": answer, "actor": answer}, NOW) == {}


def test_unknown_value_shapes_are_left_out():
    data = {"sensor": [{"type": "temperature", "ts": "2026-11-06T11:59:00Z", "values": {"a": 1, "b": 2}}],
            "actor": [{"type": "pump", "ts": "2026-11-06T11:59:00Z", "values": {"mode": "auto"}}]}
    result = ct.from_timeseries(data, NOW)
    assert "temperature" not in result and "pump" not in result


async def test_coordinator_uses_timeseries_without_other_sources():
    module = load_coordinator("protocol_tests", None)
    obj = module.SpeidelBraumeisterDataCoordinator(None, None, "TEST")
    obj._fetch_bridge = AsyncMock(return_value=None)
    obj._api = SimpleNamespace(get_timeseries=AsyncMock(return_value=series(
        ts=datetime.now(timezone.utc).isoformat())), payment_required=False)
    data = await obj._async_update_data()
    assert data["data_source"] == "cloud_timeseries"
    assert data["temperature"] == 100.5
    assert obj.cloud_series["sensor"]

    # Without usable data the endpoints are not asked again on every poll
    obj._api.get_timeseries = AsyncMock(return_value={"uuid": None, "status": {}})
    obj._cloud_retry_at = 0
    obj._api.get_latest_data = AsyncMock(side_effect=RuntimeError)
    await obj._async_update_data()
    await obj._async_update_data()
    assert obj._api.get_timeseries.await_count == 1


def load_diagnostics():
    def mod(name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        return module

    def redact(data, keys):
        if isinstance(data, dict):
            return {k: "**REDACTED**" if k in keys else redact(v, keys) for k, v in data.items()}
        if isinstance(data, list):
            return [redact(v, keys) for v in data]
        return data

    stubs = {
        "homeassistant.components.diagnostics": mod("diagnostics", async_redact_data=redact),
        "homeassistant.config_entries": mod("config_entries", ConfigEntry=object),
        "homeassistant.core": mod("core", HomeAssistant=object),
        "protocol_tests.const": mod("const", CONF_MACHINE_UUID="machine_uuid", CONF_PASSWORD="password",
                                    CONF_USERNAME="username", DOMAIN="speidel_braumeister"),
    }
    sys.modules.pop("protocol_tests.diagnostics", None)
    with patch.dict(sys.modules, stubs):
        return importlib.import_module("protocol_tests.diagnostics")


def test_diagnostics_hide_account_data_and_ids():
    diagnostics = load_diagnostics()
    coordinator = SimpleNamespace(
        data={"temperature": 100.5, "device_uuid": "0004A30B003D70F4", "firmware": "V1.1.27",
              "data_source": "bridge", "bm_stat": "V1;0004A30B003D70F4;1;0X10:00;sig;sig"},
        last_update_success=True,
        api=SimpleNamespace(has_subscription=False, payment_required=False),
        mqtt_client=None,
        cloud_series={"uuid": "323", "status": {"process (combined ID)": 404}, **series()},
    )
    entry = {"username": "brewer@example.com", "password": "secret", "machine_uuid": "0004A30B003D70F4.323"}
    result = diagnostics.build_diagnostics(coordinator, entry, "3.1.0")
    text = repr(result)
    for secret in ("brewer@example.com", "secret", "0004A30B003D70F4", "sig;sig"):
        assert secret not in text
    assert result["machine_id_format"] == "combined"
    assert result["firmware"] == "V1.1.27"
    assert result["cloud_api"]["timeseries"]["sensor"][1]["type"] == "temperature"
    assert result["cloud_api"]["timeseries"]["sensor"][1]["values"] == {"value": 100.5}


def test_recipe_selection_is_waiting_not_running(dp):
    status = "bm_stat=V1;1234567890ABCDEF;1;0X15:26XCX{}X-1000X 21.5X4200X2679X6X0X0X0X0XADUSXphX000X0X0X0;0;0"
    assert dp.parse_bm_stat(status.format(2015))["process_status"] == "waiting"
    assert dp.parse_bm_stat(status.format(2030))["process_status"] == "waiting"
    assert dp.parse_bm_stat(status.format(2300))["process_status"] == "running"
    assert dp.parse_bm_stat(status.format(101))["process_status"] == "idle"


def test_waiting_keeps_selected_recipe_through_cleaning():
    module = load_coordinator("protocol_tests", None)
    obj = module.SpeidelBraumeisterDataCoordinator(None, None, "TEST")
    cleaned = obj._clean_data({"state_code": 2015, "process_status": "waiting", "brew_name": "West Coast IPA",
                               "temperature": 21.5, "target_temperature": None, "remaining_time": 5})
    assert cleaned["process_status"] == "waiting"
    assert cleaned["brew_name"] == "West Coast IPA"
    assert cleaned["remaining_time"] is None
