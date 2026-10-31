"""No live requests: exercise cooldown, retry headers and actual HTTP paths."""
import asyncio
from datetime import datetime, timezone
import importlib
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_adaptive_polling import PACKAGE, web, coordinator, payload
policy = importlib.import_module(f"{PACKAGE}.request_policy")


class Response:
    def __init__(self, status=200, headers=None, body=None):
        self.status = status
        self.headers = headers or {}
        self.body = body or payload()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def text(self): return self.body


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
        for value, expected in [('120', 120), (' 0 ', 0), ('Sat, 31 Oct 2026 00:02:00 GMT', 120),
                                ('Fri, 30 Oct 2026 00:00:00 GMT', 0), ('-1', None),
                                ('NaN', None), ('inf', None), ('1.5', None), ('', None), (None, None)]:
            with self.subTest(value=value):
                self.assertEqual(policy.retry_after_seconds(value, now), expected)

    def test_backoff_cap_and_positive_jitter(self):
        self.assertEqual([policy.error_delay(30, n) for n in range(1, 8)], [30, 60, 120, 240, 300, 300, 300])
        self.assertEqual(policy.error_delay(600, 8), 600)
        for base in [3, 5, 10, 30, 300]:
            for _ in range(20):
                self.assertTrue(base <= policy.jitter(base) <= base + min(base * .1, 5))


class RequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_429_503_cooldown_blocks_network_then_expires(self):
        for status in [429, 503, 500]:
            guard = policy.RequestPolicy()
            session = Session(status, {'Retry-After': '120'})
            for now in [100, 110, 219]:
                with patch.object(policy, 'monotonic', return_value=now):
                    with self.assertRaises(policy.RetryLater) as caught:
                        async with guard.request(session.get, 'test'): pass
                    self.assertEqual(caught.exception.deadline, 220)
            self.assertEqual(session.calls, 1)
            session.status = 200
            with patch.object(policy, 'monotonic', return_value=220):
                async with guard.request(session.get, 'test'): pass
            self.assertEqual(session.calls, 2)

    async def test_missing_or_invalid_header_uses_30_seconds(self):
        for value in [None, 'bad']:
            with patch.object(policy, 'monotonic', return_value=100):
                with self.assertRaises(policy.RetryLater) as caught:
                    async with policy.RequestPolicy().request(Session(headers={'Retry-After': value}).get, 'test'): pass
                self.assertEqual(caught.exception.deadline, 130)

    async def test_transport_error_and_cancellation(self):
        def timeout(*args, **kwargs): raise TimeoutError()
        with self.assertRaises(policy.PollingError):
            async with policy.RequestPolicy().request(timeout, 'test'): pass
        def cancel(*args, **kwargs): raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            async with policy.RequestPolicy().request(cancel, 'test'): pass

    async def test_all_web_paths_stop_on_overload(self):
        # Includes metadata and login, not just the fast status endpoint.
        for operation in ['login', 'status', 'metadata', 'device_recipes', 'account_recipes']:
            session = Session()
            client = web.SpeidelWebAuth('', '', session)
            client.ensure_logged_in = AsyncMock(return_value=True)
            client._metadata_due = client._recipes_due = float('inf')
            with self.subTest(operation=operation):
                with self.assertRaises(policy.RetryLater):
                    if operation == 'login': await client.login()
                    elif operation == 'status': await client.get_device_status('TEST.123')
                    elif operation == 'metadata': await client._fetch_device_info_json(['TEST', '123'])
                    elif operation == 'device_recipes': await client._fetch_device_recipes('TEST')
                    else: await client._fetch_account_recipes()
                self.assertEqual(session.calls, 1)


class BackoffTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mock = patch.object(coordinator, 'jitter', side_effect=lambda seconds: seconds)
        mock.start()
        self.addCleanup(mock.stop)
        self.obj = coordinator.SpeidelBraumeisterDataCoordinator(None, None, 'TEST')

    async def test_errors_back_off_manual_calls_do_not_extend_and_success_resets(self):
        obj = self.obj
        obj._fetch_data = AsyncMock(side_effect=policy.PollingError('failure'))
        now = 100
        for expected in [30, 60, 120, 240, 300, 300]:
            with patch.object(coordinator, 'monotonic', return_value=now):
                with self.assertRaises(RuntimeError): await obj._async_update_data()
            deadline = obj._retry_not_before
            self.assertEqual(deadline, now + expected)
            calls = obj._fetch_data.await_count
            with patch.object(coordinator, 'monotonic', return_value=now + 1):
                with self.assertRaises(RuntimeError): await obj._async_update_data()
            self.assertEqual(obj._fetch_data.await_count, calls)
            self.assertEqual(obj._retry_not_before, deadline)
            now = deadline
        obj._fetch_data.side_effect = None
        obj._fetch_data.return_value = {'connection_status': 'online', 'device_mode': 'manual'}
        with patch.object(coordinator, 'monotonic', return_value=now):
            await obj._async_update_data()
        self.assertEqual(obj._failure_count, 0)
        self.assertEqual(obj.update_interval.total_seconds(), 5)

    async def test_successful_offline_never_grows_to_five_minutes(self):
        obj = self.obj
        obj._fetch_data = AsyncMock(return_value={'connection_status': 'offline'})
        for _ in range(20):
            await obj._async_update_data()
            self.assertEqual(obj.update_interval.total_seconds(), 30)
            self.assertEqual(obj._failure_count, 0)

    async def test_server_deadline_longer_than_cap_no_fallback(self):
        obj = self.obj
        obj.web_auth = types.SimpleNamespace(get_device_status=AsyncMock(side_effect=policy.RetryLater(1000)))
        obj._api = types.SimpleNamespace(get_latest_data=AsyncMock())
        with patch.object(coordinator, 'monotonic', return_value=100):
            with self.assertRaises(RuntimeError): await obj._async_update_data()
        self.assertEqual(obj._retry_not_before, 1000)
        obj._api.get_latest_data.assert_not_awaited()

    async def test_cancellation_does_not_start_backoff(self):
        self.obj._fetch_data = AsyncMock(side_effect=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError): await self.obj._async_update_data()
        self.assertEqual(self.obj._failure_count, 0)

class FallbackClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_xhr_stops_on_429(self):
        legacy = importlib.import_module(f"{PACKAGE}.xhr_client")
        session = Session()
        client = legacy.SpeidelXHRClient('', '', session)
        client.ensure_logged_in = AsyncMock(return_value=True)
        with self.assertRaises(policy.RetryLater):
            await client.get_device_status('TEST.123')
        self.assertEqual(session.calls, 1)

    async def test_cloud_auth_and_get_stop_on_503(self):
        # Use actual API implementation, stubbing data models to avoid requiring
        # Pydantic/HA for these HTTP-policy tests (response parsing isn't reached).
        import sys
        from test_adaptive_polling import ROOT, module
        names = ['AuthResponse', 'DeviceStatusControl', 'Machine', 'MachineList',
                 'OnOffStatus', 'ProcessStatus', 'AccountRecipe', 'RecipeSlot', 'BrewingProcess']
        models = module('models', **{name: object for name in names},
                        ConnectionStatus=types.SimpleNamespace(OFFLINE='offline'),
                        DeviceDataResult=lambda **kw: types.SimpleNamespace(**kw))
        const = module('const', API_BASE_URL='https://example.invalid', WEB_API_BASE_URL='https://example.invalid')
        spec = importlib.util.spec_from_file_location(f'{PACKAGE}.real_api_test', ROOT / 'api.py')
        api = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {f'{PACKAGE}.models': models, f'{PACKAGE}.const': const}):
            spec.loader.exec_module(api)
        for operation in ['auth', 'get', 'web', 'fallback']:
            session = Session(503, {'Retry-After': '120'})
            client = api.SpeidelBraumeisterAPI('', '', session)
            client.ensure_authenticated = AsyncMock()
            with self.subTest(operation=operation):
                with self.assertRaises(policy.RetryLater):
                    if operation == 'auth': await client.authenticate()
                    elif operation == 'get': await client._request('GET', '/status')
                    elif operation == 'web': await client._get_device_status_web('TEST.123')
                    else:
                        client._get_xhr_client = lambda: types.SimpleNamespace(get_device_status=AsyncMock(side_effect=policy.RetryLater(1000)))
                        client._get_device_status_web = AsyncMock()
                        client._get_device_status_cloud = AsyncMock()
                        await client.get_latest_data('TEST')
                if operation == 'fallback':
                    client._get_device_status_web.assert_not_awaited()
                    client._get_device_status_cloud.assert_not_awaited()
                    self.assertEqual(session.calls, 0)
                else:
                    self.assertEqual(session.calls, 1)
