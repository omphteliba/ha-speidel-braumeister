"""Generic upload contract; no recipe application or live hardware required."""
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from test_bridge import DEVICE, DEVICE_HEADERS, make_bridge
from test_program_control import body
from test_recipe_upload import WEIZEN


@pytest.fixture
async def upload_api(bridge_module):
    async def reply(request):
        await request.read()
        return web.Response(body=bridge_module.LOCAL_ANSWER)

    cloud = web.Application()
    cloud.router.add_post('/braumeister/connect', reply)
    async with TestServer(cloud) as server:
        bridge, device, api = await make_bridge(bridge_module, str(server.make_url('')))
        async with device, api:
            try:
                bridge.options['recipe_write_enabled'] = True
                yield bridge, device, api
            finally:
                await bridge.close_session()


async def poll(device, count='3', state='101', flags='ph'):
    response = await device.post('/braumeister/connect', data=body(state, flags, count=count), headers=DEVICE_HEADERS)
    return await response.read()


async def test_readiness_and_recheck(upload_api, bridge_module):
    bridge, device, api = upload_api
    url = '/api/recipes/readiness?device_id=' + DEVICE
    status = await (await api.get(url)).json()
    assert status['connected'] is False
    assert status['main_menu'] is None
    assert status['pump_on'] is None
    for state, flags, ready in [('101', 'ph', True), ('101', 'Ph', False),
                                ('101', 'pH', False), ('101', 'pi', False), ('2015', 'ph', False)]:
        await poll(device, state=state, flags=flags)
        status = await (await api.get(url)).json()
        assert status['ready_for_upload'] is ready
    # An earlier successful readiness check never authorizes a later unsafe POST.
    assert (await api.post('/api/recipes', json={'device_id': DEVICE, 'recipes': [WEIZEN]})).status == 409
    await poll(device)
    bridge.devices[DEVICE]['bm_stat_received'] -= bridge_module.CONTROL_TIMEOUT + 1
    assert not (await (await api.get(url)).json())['ready_for_upload']
    bridge.options['recipe_write_enabled'] = False
    assert 'upload_disabled' in (await (await api.get(url)).json())['blocking_reasons']
    assert (await api.get(url, headers={'Origin': 'http://example.com'})).status == 403


async def test_job_identity_readback_and_retention(upload_api, bridge_module):
    bridge, device, api = upload_api
    await poll(device)
    submitted = await (await api.post('/api/recipes', json={'device_id': DEVICE, 'recipes': [WEIZEN]})).json()
    job_id = submitted['job_id']
    assert submitted['content_verification'] == 'not_available'
    await poll(device)
    await poll(device, '0')
    await poll(device, '1')
    url = '/api/recipes?job_id=' + job_id
    status = await (await api.get(url)).json()
    assert status['result'] == 'confirmed'
    assert status['written'] == 1
    assert status['content_verification'] == 'not_available'
    line = bridge_module.recipe_line(0, WEIZEN)
    bridge.record('/', f'rz=header;{DEVICE};timestamp;\r\n{line};signature\r\n'.encode(), '127.0.0.1')
    assert (await (await api.get(url)).json())['content_verification'] == 'matched'
    later = await (await api.post('/api/recipes', json={'device_id': DEVICE, 'recipes': [WEIZEN]})).json()
    assert later['job_id'] != job_id
    assert (await (await api.get(url)).json())['result'] == 'confirmed'
    assert (await api.get('/api/recipes?job_id=missing')).status == 404


async def test_final_ack_does_not_hide_unsafe_state(upload_api):
    bridge, device, api = upload_api
    await poll(device)
    await api.post('/api/recipes', json={'device_id': DEVICE, 'recipes': [WEIZEN]})
    await poll(device)
    await poll(device, '0')
    await poll(device, '1', flags='Ph')
    assert bridge.recipe_job['result'] == 'state_changed'


def test_stale_readback_not_accepted_and_mismatch(bridge_module):
    bridge = bridge_module.Bridge({**bridge_module.DEFAULTS, 'state_file': ''})
    line = bridge_module.recipe_line(0, WEIZEN)
    bridge.recipe_job = {'job_id': 'job', 'device_id': DEVICE, 'result': 'confirmed',
                         'steps': [b'$d=A', ('$rz=' + line).encode()], 'step': 2,
                         'confirmed_at': time.time() + 100}
    message = f'rz=header;{DEVICE};timestamp;\r\n{line};signature\r\n'.encode()
    bridge.record('/', message, '127.0.0.1')
    assert bridge.recipe_job_status(bridge.recipe_job)['content_verification'] == 'not_available'
    bridge.recipe_job['confirmed_at'] = 0
    bridge.record('/', message.replace(b'Weizen', b'Other'), '127.0.0.1')
    assert bridge.recipe_job_status(bridge.recipe_job)['content_verification'] == 'mismatch'
