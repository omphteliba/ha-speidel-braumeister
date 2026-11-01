"""Offline tests of actual HTTP clients and their shared retry policy."""

import asyncio
from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

PACKAGE = "_retry_tests"
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "speidel_braumeister"
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg
policy = importlib.import_module(f"{PACKAGE}.request_policy")
web = importlib.import_module(f"{PACKAGE}.web_auth")


def module(name, **attrs):
    obj = types.ModuleType(name)
    obj.__dict__.update(attrs)
    return obj


def payload():
    return ""


class Response:
    def __init__(self, status=200, headers=None, body=None):
        self.status = status
        self.headers = headers or {}
        self.body = body or payload()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def text(self):
        return self.body


class Session:
    def __init__(self, status=429, headers=None):
        self.calls = 0
        self.status = status
        self.headers = headers

    def get(self, *args, **kwargs):
        self.calls += 1
        return Response(self.status, self.headers)

    post = get


class HeaderTests(unittest.TestCase):
    def test_seconds_dates_and_invalid_headers(self):
        now = datetime(2026, 10, 31, tzinfo=timezone.utc)
        for value, expected in [
            ("120", 120),
            (" 0 ", 0),
            ("Sat, 31 Oct 2026 00:02:00 GMT", 120),
            ("Fri, 30 Oct 2026 00:00:00 GMT", 0),
            ("-1", None),
            ("NaN", None),
            ("inf", None),
            ("1.5", None),
            ("", None),
            (None, None),
        ]:
            with self.subTest(value=value):
                self.assertEqual(policy.retry_after_seconds(value, now), expected)

    def test_backoff_cap(self):
        self.assertEqual([policy.error_delay(30, n) for n in range(1, 8)], [30, 60, 120, 240, 300, 300, 300])
        self.assertEqual(policy.error_delay(600, 8), 600)


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_429_503_cooldown_blocks_network_then_expires(self):
        for status in [429, 503, 500]:
            guard = policy.RequestPolicy()
            session = Session(status, {"Retry-After": "120"})
            for now in [100, 110, 219]:
                with patch.object(policy, "monotonic", return_value=now):
                    with self.assertRaises(policy.RetryLater) as caught:
                        async with guard.request(session.get, "test"):
                            pass
                    self.assertEqual(caught.exception.deadline, 220)
            self.assertEqual(session.calls, 1)
            session.status = 200
            with patch.object(policy, "monotonic", return_value=220):
                async with guard.request(session.get, "test"):
                    pass
            self.assertEqual(session.calls, 2)

    async def test_missing_or_invalid_header_uses_30_seconds(self):
        for value in [None, "bad"]:
            with patch.object(policy, "monotonic", return_value=100):
                with self.assertRaises(policy.RetryLater) as caught:
                    async with policy.RequestPolicy().request(Session(headers={"Retry-After": value}).get, "test"):
                        pass
                self.assertEqual(caught.exception.deadline, 130)

    async def test_transport_error_and_cancellation(self):
        def timeout(*args, **kwargs):
            raise TimeoutError()

        with self.assertRaises(policy.PollingError):
            async with policy.RequestPolicy().request(timeout, "test"):
                pass

        def cancel(*args, **kwargs):
            raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            async with policy.RequestPolicy().request(cancel, "test"):
                pass

    async def test_all_web_paths_stop_on_overload(self):
        # Includes metadata and login, not just the fast status endpoint.
        for operation in ["login", "status", "metadata", "device_recipes", "account_recipes"]:
            session = Session()
            client = web.SpeidelWebAuth("", "", session)
            client.ensure_logged_in = AsyncMock(return_value=True)
            client._metadata_due = client._recipes_due = float("inf")
            with self.subTest(operation=operation):
                with self.assertRaises(policy.RetryLater):
                    if operation == "login":
                        await client.login()
                    elif operation == "status":
                        await client.get_device_status("TEST.123")
                    elif operation == "metadata":
                        await client._fetch_device_info_json(["TEST", "123"])
                    elif operation == "device_recipes":
                        await client._fetch_device_recipes("TEST")
                    else:
                        await client._fetch_account_recipes()
                self.assertEqual(session.calls, 1)


class FallbackClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_xhr_stops_on_429(self):
        legacy = importlib.import_module(f"{PACKAGE}.xhr_client")
        session = Session()
        client = legacy.SpeidelXHRClient("", "", session)
        client.ensure_logged_in = AsyncMock(return_value=True)
        with self.assertRaises(policy.RetryLater):
            await client.get_device_status("TEST.123")
        self.assertEqual(session.calls, 1)

    async def test_cloud_auth_and_get_stop_on_503(self):
        # Use actual API implementation, stubbing data models to avoid requiring
        # Pydantic/HA for these HTTP-policy tests (response parsing isn't reached).
        import sys

        names = [
            "AuthResponse",
            "DeviceStatusControl",
            "Machine",
            "MachineList",
            "OnOffStatus",
            "ProcessStatus",
            "AccountRecipe",
            "RecipeSlot",
            "BrewingProcess",
        ]
        models = module(
            "models",
            **{name: object for name in names},
            ConnectionStatus=types.SimpleNamespace(OFFLINE="offline"),
            DeviceDataResult=lambda **kw: types.SimpleNamespace(**kw),
        )
        const = module("const", API_BASE_URL="https://example.invalid", WEB_API_BASE_URL="https://example.invalid")
        spec = importlib.util.spec_from_file_location(f"{PACKAGE}.real_api_test", ROOT / "api.py")
        api = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {f"{PACKAGE}.models": models, f"{PACKAGE}.const": const}):
            spec.loader.exec_module(api)
        for operation in ["auth", "get", "web", "fallback"]:
            session = Session(503, {"Retry-After": "120"})
            client = api.SpeidelBraumeisterAPI("", "", session)
            client.ensure_authenticated = AsyncMock()
            with self.subTest(operation=operation):
                with self.assertRaises(policy.RetryLater):
                    if operation == "auth":
                        await client.authenticate()
                    elif operation == "get":
                        await client._request("GET", "/status")
                    elif operation == "web":
                        await client._get_device_status_web("TEST.123")
                    else:
                        client._get_xhr_client = lambda: types.SimpleNamespace(
                            get_device_status=AsyncMock(side_effect=policy.RetryLater(1000))
                        )
                        client._get_device_status_web = AsyncMock()
                        client._get_device_status_cloud = AsyncMock()
                        await client.get_latest_data("TEST")
                if operation == "fallback":
                    client._get_device_status_web.assert_not_awaited()
                    client._get_device_status_cloud.assert_not_awaited()
                    self.assertEqual(session.calls, 0)
                else:
                    self.assertEqual(session.calls, 1)


def load_coordinator(package, root):
    import importlib
    import sys
    import types
    from unittest.mock import patch

    def mod(name, **attrs):
        result = types.ModuleType(name)
        result.__dict__.update(attrs)
        return result

    class Base:
        def __class_getitem__(cls, key):
            return cls

        def __init__(self, *args, update_interval=None, **kwargs):
            self.update_interval = update_interval
            self.hass = None
            self.data = None

    stubs = {
        "homeassistant.core": mod("core", HomeAssistant=object, callback=lambda fn: fn),
        "homeassistant.helpers.aiohttp_client": mod("aiohttp", async_get_clientsession=lambda hass: None),
        "homeassistant.helpers.update_coordinator": mod(
            "coordinator", DataUpdateCoordinator=Base, UpdateFailed=RuntimeError
        ),
        f"{package}.const": mod(
            "const", BRIDGE_MAX_AGE=10, BRIDGE_STATUS_URL="http://localhost", DEFAULT_SCAN_INTERVAL=30
        ),
        f"{package}.api": mod(
            "api",
            SpeidelBraumeisterAPI=object,
            SpeidelAuthError=type("AuthError", (Exception,), {}),
            SpeidelApiError=type("ApiError", (Exception,), {}),
            SpeidelPaymentRequiredError=type("PaymentError", (Exception,), {}),
        ),
    }
    with patch.dict(sys.modules, stubs):
        return importlib.import_module(f"{package}.coordinator")


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_fallback_after_retry_later(self):
        coordinator = load_coordinator(PACKAGE, ROOT)
        api = types.SimpleNamespace(get_latest_data=AsyncMock())
        obj = coordinator.SpeidelBraumeisterDataCoordinator(None, api, "TEST")
        obj._fetch_bridge = AsyncMock(return_value=None)
        obj.web_auth = types.SimpleNamespace(get_device_status=AsyncMock(side_effect=policy.RetryLater(1000)))
        with self.assertRaises(RuntimeError):
            await obj._async_update_data()
        api.get_latest_data.assert_not_awaited()
        self.assertEqual(obj.update_interval.total_seconds(), 30)

    async def test_bridge_stays_live_during_cloud_cooldown(self):
        coordinator = load_coordinator(PACKAGE, ROOT)
        obj = coordinator.SpeidelBraumeisterDataCoordinator(None, None, "TEST")
        obj._fetch_bridge = AsyncMock(
            return_value={
                "temperature": 63.0,
                "target_temperature": 63.0,
                "current_step": "1. Rast",
                "process_status": "running",
                "device_mode": "automatic",
            }
        )
        obj.web_auth = types.SimpleNamespace(get_device_info=AsyncMock(side_effect=policy.RetryLater(1000)))
        result = await obj._async_update_data()
        self.assertEqual(result["data_source"], "bridge")
        self.assertEqual(result["temperature"], 63.0)
        self.assertEqual(obj.update_interval.total_seconds(), 30)
