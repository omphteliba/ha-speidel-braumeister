"""Wire-level regression for compressed cloud commands on legacy modules."""
import gzip
import zlib

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from test_bridge import make_bridge, BM_STAT, DEVICE_HEADERS

COMMAND = b'Start\r\n$k=1\r\nOK\r\nDone\r\n'


@pytest.mark.parametrize('encoding', ['', 'identity', 'gzip', 'deflate', 'raw-deflate', 'gzip, deflate'])
async def test_device_receives_plain_commands(bridge_module, encoding):
    body = COMMAND
    if encoding in ('gzip', 'gzip, deflate'):
        body = gzip.compress(body)
    if encoding in ('deflate', 'gzip, deflate'):
        body = zlib.compress(body)
    if encoding == 'raw-deflate':
        body = zlib.compress(body)[2:-4]
    seen = []

    async def reply(request):
        seen.append(request.headers.get('Accept-Encoding'))
        assert await request.read() == BM_STAT
        headers = {'ETag': '"compressed"'}
        if encoding:
            headers['Content-Encoding'] = 'deflate' if encoding == 'raw-deflate' else encoding
        return web.Response(body=body, headers=headers)

    app = web.Application()
    app.router.add_post('/device', reply)
    cloud = TestServer(app)
    await cloud.start_server()
    bridge, port80, api = await make_bridge(bridge_module, str(cloud.make_url('')))
    try:
        # Override even an explicitly supplied encoding preference.
        headers = dict(DEVICE_HEADERS, **{'Accept-Encoding': 'gzip, deflate'})
        response = await port80.post('/device', data=BM_STAT, headers=headers, auto_decompress=False)
        assert response.status == 200
        assert await response.read() == COMMAND
        assert seen == ['identity']
        assert 'Content-Encoding' not in response.headers
        assert 'Content-Length' not in response.headers
        if encoding:
            assert 'ETag' not in response.headers
        assert response.headers['Transfer-Encoding'] == 'chunked'
        device = next(iter(bridge.devices.values()))
        assert device['last_response'] == COMMAND.decode('ascii')
        assert device['last_response_source'] == 'cloud'
    finally:
        await port80.close()
        await api.close()
        await cloud.close()
        await bridge.close_session()


@pytest.mark.parametrize('encoding, body', [('gzip', b'broken gzip'), ('br', b'unsupported')])
async def test_invalid_compression_uses_local_fallback(bridge_module, encoding, body):
    async def reply(request):
        return web.Response(body=body, headers={'Content-Encoding': encoding})
    app = web.Application()
    app.router.add_post('/device', reply)
    cloud = TestServer(app)
    await cloud.start_server()
    bridge, port80, api = await make_bridge(bridge_module, str(cloud.make_url('')))
    try:
        response = await port80.post('/device', data=BM_STAT, headers=DEVICE_HEADERS, auto_decompress=False)
        assert await response.read() == bridge_module.LOCAL_ANSWER
        assert 'Content-Encoding' not in response.headers
        assert next(iter(bridge.devices.values()))['last_response_source'] == 'local'
    finally:
        await port80.close()
        await api.close()
        await cloud.close()
        await bridge.close_session()
