"""Offline regression tests; no network or Home Assistant installation needed."""
import asyncio
import importlib
from pathlib import Path
import sys
import types
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

PACKAGE = "_adaptive_tests"
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "speidel_braumeister"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg
policy = importlib.import_module(f"{PACKAGE}.polling")
web = importlib.import_module(f"{PACKAGE}.web_auth")

# Import the real coordinator methods with minimal HA/API boundary doubles.
class CoordinatorBase:
    def __class_getitem__(cls, _):
        return cls
    def __init__(self, *args, update_interval=None, **kwargs):
        self.update_interval = update_interval
        self.data = None
    def async_set_updated_data(self, data):
        self.data = data


def module(name, **attrs):
    obj = types.ModuleType(name)
    obj.__dict__.update(attrs)
    return obj


stubs = {
    "homeassistant.core": module("homeassistant.core", HomeAssistant=object, callback=lambda fn: fn),
    "homeassistant.helpers.update_coordinator": module("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=CoordinatorBase, UpdateFailed=RuntimeError),
    f"{PACKAGE}.const": module("const", DEFAULT_SCAN_INTERVAL=30, DOMAIN="test", BINARY_SENSOR_TYPES=[]),
    f"{PACKAGE}.api": module("api", SpeidelBraumeisterAPI=object, SpeidelAuthError=type("AuthError", (Exception,), {}), SpeidelApiError=type("ApiError", (Exception,), {}), SpeidelPaymentRequiredError=type("PaymentError", (Exception,), {})),
}
with patch.dict(sys.modules, stubs):
    coordinator = importlib.import_module(f"{PACKAGE}.coordinator")


def payload(code=101, indicators="ph", flags="000"):
    fields = ["0", "12:00", "C", str(code), "380", "21.0", "1200", "1004", "1", "0", "0", "0", "0", "EMSR", indicators, flags, "0", "0"]
    return "firmware;TEST_DEVICE;0;" + "X".join(fields) + ";test;test"


class PolicyTests(unittest.TestCase):
    def test_defaults_options_and_invalid_values(self):
        get = policy.configured_interval
        self.assertEqual(get({}, {}, "scan_interval", 30), 30)
        self.assertEqual(get({"scan_interval": 60}, {}, "scan_interval", 30), 60)
        self.assertEqual(get({"scan_interval": 60}, {"scan_interval": 30}, "scan_interval", 30), 30)
        self.assertEqual(get({}, {"active": 3}, "active", 5), 3)
        for value, expected in [(0, 3), (9999, 3600), (None, 5), ("bad", 5)]:
            self.assertEqual(get({}, {"active": value}, "active", 5), expected)

    def test_offline_overrides_all_stale_activity(self):
        for connection in ("offline", "unknown", None):
            self.assertEqual(policy.polling_state({"connection_status": connection, "brew_status_code": 3070, "alarm": True, "heating": "on"}), "offline")

    def test_device_codes_override_stale_timers_and_mode(self):
        for code in (101, 2000, 2020, 3450, 3600, 6001):
            with self.subTest(code=code):
                self.assertEqual(policy.polling_state({"connection_status": "online", "brew_status_code": code, "process_status": "running", "device_mode": "automatic", "remaining_time": 20}), "online")
        for code in (2021, 2200, 2510, 2810, 3070, 3080, 3449, 4006, 4007):
            self.assertEqual(policy.polling_state({"connection_status": "online", "brew_status_code": code, "pump": "off", "heating": "off"}), "active")

    def test_actors_alarms_and_cloud_fallback(self):
        for extras in ({"pump": "on"}, {"heating": "Ein"}, {"alarm": True}, {"process_status": "paused"}, {"device_mode": "manual"}):
            self.assertEqual(policy.polling_state({"connection_status": "online", **extras}), "active")
        self.assertEqual(policy.polling_state({"connection_status": "online", "brew_name": "Old recipe", "remaining_time": 20}), "online")

    def test_fast_alarm_flags_and_hop_dialog(self):
        client = web.SpeidelWebAuth("", "")
        for code, flags, expected in [(101, "000", False), (2400, "010", True), (2400, "020", True), (2400, "0D0", True), (3080, "000", True), (3449, "000", True), (3450, "000", False), (3080, "100", False), (3070, "000", False), (3070, "0?0", None), (3070, "", None)]:
            with self.subTest(code=code, flags=flags):
                data = client._parse_xhr_response(payload(code, flags=flags))
                self.assertIs(data["alarm"], expected)
                self.assertEqual(data["brew_status_code"], code)
        self.assertEqual(policy.display_flags([]), {"brew_status_code": None, "alarm": None})


class Response:
    status = 200
    def __init__(self, text): self.value = text
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def text(self): return self.value


class Session:
    def __init__(self): self.urls = []
    def get(self, url, **kwargs):
        self.urls.append(url)
        return Response(payload(3070))


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_throttling_empty_recipes_and_ttl(self):
        session = Session()
        client = web.SpeidelWebAuth("", "", session)
        client.ensure_logged_in = AsyncMock(return_value=True)
        client._fetch_device_info_json = AsyncMock(return_value={})
        client._fetch_device_recipes = AsyncMock()
        client._fetch_account_recipes = AsyncMock()
        for now in (1, 4, 7, 10, 31, 301):
            with patch.object(web, "monotonic", return_value=now):
                result = await client.get_device_status("TEST")
                self.assertEqual(result["temperature"], 21)
        self.assertEqual(len(session.urls), 6)
        self.assertEqual(client._fetch_device_info_json.await_count, 3)
        self.assertEqual(client._fetch_device_recipes.await_count, 2)
        self.assertEqual(client._fetch_account_recipes.await_count, 2)

    async def test_empty_failed_refresh_attempts_are_throttled(self):
        client = web.SpeidelWebAuth("", "", Session())
        client.ensure_logged_in = AsyncMock(return_value=True)
        # Production fetch helpers swallow connection errors and return empty.
        client._fetch_device_info_json = AsyncMock(return_value={})
        client._fetch_device_recipes = AsyncMock(return_value=None)
        client._fetch_account_recipes = AsyncMock(return_value=None)
        with patch.object(web, "monotonic", return_value=10):
            for _ in range(3): await client.get_device_status("TEST")
        self.assertEqual(client._fetch_device_info_json.await_count, 1)
        self.assertEqual(client._fetch_account_recipes.await_count, 1)


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    def make(self, active=5):
        obj = coordinator.SpeidelBraumeisterDataCoordinator(None, types.SimpleNamespace(), "TEST", active_interval=active)
        obj.web_auth = types.SimpleNamespace(get_device_status=AsyncMock())
        return obj

    async def test_real_fetch_state_transitions_and_alarm_propagation(self):
        obj = self.make()
        client = web.SpeidelWebAuth("", "")
        for data, seconds in [({}, 30), (client._parse_xhr_response(payload()), 10), (client._parse_xhr_response(payload(2510)), 5), (client._parse_xhr_response(payload(3080)), 5), (client._parse_xhr_response(payload()), 10), ({}, 30)]:
            obj.web_auth.get_device_status.return_value = data
            result = await obj._async_update_data()
            self.assertEqual(obj.update_interval, timedelta(seconds=seconds))
            if data: self.assertIs(result["alarm"], data["alarm"])

    async def test_three_second_setting_and_failures(self):
        obj = self.make(active=3)
        obj._fetch_data = AsyncMock(return_value={"connection_status": "online", "brew_status_code": 3070})
        await obj._async_update_data()
        self.assertEqual(obj.update_interval.total_seconds(), 3)
        obj._fetch_data.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError): await obj._async_update_data()
        self.assertEqual(obj.update_interval.total_seconds(), 30)

    async def test_mqtt_freshness_and_xhr_fallback(self):
        obj = self.make()
        with patch.object(coordinator, "monotonic", return_value=100):
            obj.update_from_mqtt({"temperature": 22, "pump": "on"})
        with patch.object(coordinator, "monotonic", return_value=110):
            result = await obj._async_update_data()
        self.assertEqual(result["temperature"], 22)
        obj.web_auth.get_device_status.assert_not_awaited()
        obj.web_auth.get_device_status.return_value = web.SpeidelWebAuth("", "")._parse_xhr_response(payload())
        with patch.object(coordinator, "monotonic", return_value=131):
            result = await obj._async_update_data()
        obj.web_auth.get_device_status.assert_awaited_once()
        self.assertEqual(result["temperature"], 21)
        self.assertEqual(result["pump"], "off")
        self.assertEqual(obj.update_interval.total_seconds(), 10)

    async def test_intervals_are_ordered(self):
        obj = coordinator.SpeidelBraumeisterDataCoordinator(None, None, "TEST", 30, 60, 100)
        self.assertEqual(obj._poll_intervals, {"offline": 30, "online": 30, "active": 30})


class AlarmEntityTests(unittest.TestCase):
    def test_entity_uses_fast_alarm_and_preserves_unknown(self):
        # Execute the actual property's code; isolate only the HA entity base.
        import ast
        tree = ast.parse((ROOT / "binary_sensor.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "is_on")
        fn.decorator_list = []
        scope = {"ALARM_PHASES": ["Einmaischen Temp. erreicht", "Rastende erreicht"]}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "binary_sensor.py", "exec"), scope)
        obj = types.SimpleNamespace(coordinator=types.SimpleNamespace(data=None), entity_description=types.SimpleNamespace(key="alarm"))
        for data, expected in [
            ({"connection_status": "online", "alarm": True}, True),
            ({"connection_status": "online", "alarm": False, "current_phase": "Rastende erreicht"}, False),
            ({"connection_status": "online", "alarm": None}, None),
            ({"connection_status": "offline", "alarm": True}, None),
            ({"connection_status": "online", "current_phase": "Rastende erreicht"}, True),
        ]:
            obj.coordinator.data = data
            self.assertIs(scope["is_on"](obj), expected)


if __name__ == "__main__":
    unittest.main()
