"""Fork tests: DNS isolation, transparent forwarding and local/cloud scheduling."""
import gzip
import importlib
import types
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from test_adaptive_polling import coordinator, PACKAGE, payload
from test_bridge import make_bridge, BM_STAT, DEVICE_HEADERS

client = importlib.import_module(f'{PACKAGE}.bridge_client')


@pytest.mark.parametrize('address', ['127.0.0.1', '192.168.1.2', '10.1.2.3', '169.254.1.1', '::1', 'fd00::1', '0.0.0.0'])
async def test_cloud_resolver_rejects_local_addresses(bridge_module, address):
    resolver = object.__new__(bridge_module.PublicCloudResolver)
    resolver.delegate = types.SimpleNamespace(resolve=AsyncMock(return_value=[{'host': address}]))
    with pytest.raises(OSError):
        await resolver.resolve('api2.myspeidel.com', 80)


async def test_cloud_resolver_uses_explicit_dns(bridge_module):
    delegate = types.SimpleNamespace(resolve=AsyncMock(return_value=[{'host': '1.1.1.1'}]), close=AsyncMock())
    with patch.object(bridge_module, 'AsyncResolver', return_value=delegate) as factory:
        resolver = bridge_module.PublicCloudResolver(['9.9.9.9'])
    factory.assert_called_once_with(nameservers=['9.9.9.9'])
    assert await resolver.resolve('api2.myspeidel.com', 80) == [{'host': '1.1.1.1'}]
    await resolver.close()
    delegate.close.assert_awaited_once()


async def test_cloud_bytes_headers_and_no_redirect_following(bridge_module):
    received = []
    body = gzip.compress(b'Start\r\n$k=1\r\nOK\r\nDone\r\n')
    async def cloud_reply(request):
        received.append((request.method, request.path_qs, await request.read()))
        return web.Response(status=302, body=body, headers={'Content-Encoding': 'gzip', 'Location': '/unexpected', 'Retry-After': '60'})
    app = web.Application()
    app.router.add_route('*', '/{tail:.*}', cloud_reply)
    cloud = TestServer(app)
    await cloud.start_server()
    bridge, port80, api = await make_bridge(bridge_module, str(cloud.make_url('')))
    try:
        response = await port80.post('/braumeister/connect?x=1', data=BM_STAT, headers=DEVICE_HEADERS,
                                    allow_redirects=False, auto_decompress=False)
        assert response.status == 302
        assert 'Content-Encoding' not in response.headers
        assert response.headers['Retry-After'] == '60'
        assert await response.read() == gzip.decompress(body)
        assert received == [('POST', '/braumeister/connect?x=1', BM_STAT)]
    finally:
        await port80.close()
        await api.close()
        await cloud.close()
        await bridge.close_session()


class Reply:
    status = 200
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def json(self): return self.value


def bridge_status(age=1, ident='TEST', message=None):
    return {'now': 1, 'devices': [{'device_id': ident, 'bm_stat_received': 100-age,
            'bm_stat': message or payload(2820).replace('TEST_DEVICE', 'TEST')}]}


@pytest.mark.parametrize('age, valid', [(1, True), (10, True), (11, False), (-1, False)])
async def test_local_freshness_uses_host_clock(age, valid):
    session = types.SimpleNamespace(get=lambda *a, **kw: Reply(bridge_status(age)))
    with patch.object(client.time, 'time', return_value=100):
        data = await client.read_bridge(session, 'TEST.123')
    assert bool(data) is valid
    if data:
        assert data['data_source'] == 'bridge'
        assert data['alarm'] is False
        assert data['pump'] == 'off'
        assert data['current_step'] == 'Statuscode 2820'


async def test_other_device_and_malformed_payload_are_ignored():
    for value in [bridge_status(ident='OTHER'), bridge_status(message='invalid'), {}, {'devices': [None]}]:
        session = types.SimpleNamespace(get=lambda *a, **kw: Reply(value))
        with patch.object(client.time, 'time', return_value=100):
            assert await client.read_bridge(session, 'TEST.123') is None


def obj():
    instance = coordinator.SpeidelBraumeisterDataCoordinator(None, None, 'TEST')
    instance._fetch_bridge = AsyncMock(return_value=None)
    instance._fetch_data = AsyncMock(return_value={'connection_status': 'online', 'temperature': 22})
    return instance


async def test_local_data_works_during_cloud_cooldown_without_clearing_it():
    instance = obj()
    instance._retry_not_before = 1000
    instance._fetch_bridge.return_value = {'data_source': 'bridge', 'connection_status': 'online', 'temperature': 22,
                                         'state_code': 2820, 'process_status': 'running', 'remaining_time': 5}
    with patch.object(coordinator, 'monotonic', return_value=100):
        data = await instance._async_update_data()
    assert data['temperature'] == 22
    assert data['process_status'] == 'running'
    assert instance.update_interval.total_seconds() == 1
    assert instance._retry_not_before == 1000
    instance._fetch_data.assert_not_awaited()


async def test_bridge_loss_does_not_turn_cloud_into_one_second_polling():
    instance = obj()
    instance._bridge_seen = True
    with patch.object(coordinator, 'monotonic', return_value=100), patch.object(coordinator, 'jitter', side_effect=lambda x: x):
        instance.data = await instance._async_update_data()
    for now in range(101, 110):
        with patch.object(coordinator, 'monotonic', return_value=now):
            assert await instance._async_update_data() == instance.data
    instance._fetch_data.assert_awaited_once()
    with patch.object(coordinator, 'monotonic', return_value=110):
        await instance._async_update_data()
    assert instance._fetch_data.await_count == 2


async def test_stale_local_state_not_returned_during_cloud_cooldown():
    instance = obj()
    instance._bridge_seen = True
    instance.data = {'data_source': 'bridge', 'temperature': 22}
    instance._retry_not_before = 500
    with patch.object(coordinator, 'monotonic', return_value=100):
        with pytest.raises(RuntimeError): await instance._async_update_data()
    instance._fetch_data.assert_not_awaited()
    assert instance.update_interval.total_seconds() == 1
