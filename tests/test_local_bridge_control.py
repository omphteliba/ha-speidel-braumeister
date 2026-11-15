"""Bridge control remains local when forwarding is disabled."""
from unittest.mock import AsyncMock

from test_bridge import BM_STAT, DEVICE, DEVICE_HEADERS, make_bridge


async def test_no_cloud_forwarding_for_local_status_and_confirmed_menu(bridge_module):
    bridge, device, api = await make_bridge(bridge_module, 'http://127.0.0.1:1')
    bridge.options['forward_to_cloud'] = False
    bridge.options['control_enabled'] = True
    bridge.forward_to_cloud = AsyncMock(side_effect=AssertionError('Cloud forwarding'))
    async with device, api:
        try:
            async def poll(screen):
                body = BM_STAT.replace(b'X2820X', f'X{screen}X'.encode()).replace(b'XPiX', b'XphX')
                response = await device.post('/braumeister/connect', data=body, headers=DEVICE_HEADERS)
                return await response.read()

            assert await poll(101) == bridge_module.LOCAL_ANSWER
            assert bridge.devices[DEVICE]['last_response_source'] == 'local'
            response = await api.post('/api/control', json={'device_id': DEVICE, 'action': 'open_settings'})
            assert response.status == 202
            assert b'$k=1' in await poll(101)
            await poll(8101)
            result = await (await api.get('/api/control')).json()
            assert result['result'] == 'confirmed'
            bridge.forward_to_cloud.assert_not_awaited()
        finally:
            await bridge.close_session()
