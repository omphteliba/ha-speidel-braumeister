"""Observed editor transitions, guarded commands and truthful acknowledgments."""
import pytest

from test_bridge import BM_STAT, DEVICE, DEVICE_HEADERS, make_bridge


def message(screen, labels, indicator="000", target="380", delay="0", flags="ph"):
    f = BM_STAT.split(b"X")
    for index, value in ((3, screen), (4, target), (13, labels), (14, flags), (15, indicator), (17, delay)):
        f[index] = str(value).encode()
    return b"X".join(f)


@pytest.mark.parametrize("action,before,after,key,result", [
    ("confirm_water_filled", (2030,"ADUS"), (2300,"A000","000","380","0","Ph"), 4, "confirmed"),
    ("cancel_water_prompt", (2030,"ADUS"), (101,"EMSR"), 1, "confirmed"),
    ("start_now", (2120,"A00S","000","380","3531"), (2300,"A000","000","380","0","Ph"), 4, "confirmed"),
    ("open_temperature_editor", (4006,"APHT"), (4007,"ADUS","00T"), 4, "confirmed"),
    ("temperature_up", (4007,"ADUS","00T"), (4007,"ADUS","00T","390"), 3, "confirmed"),
    ("temperature_up", (4007,"ADUS","00T","1000"), (4007,"ADUS","00T","1010"), 3, "confirmed"),
    ("temperature_up", (4007,"ADUS","00T","1020"), (4007,"ADUS","00T","1030"), 3, "confirmed"),
    ("temperature_down", (4007,"ADUS","00T","1030"), (4007,"ADUS","00T","1020"), 2, "confirmed"),
    ("confirm_temperature", (4007,"ADUS","00T","1030"), (4006,"APHT","000","1030"), 4, "confirmed"),
    ("temperature_down", (4007,"ADUS","00T","390"), (4007,"ADUS","00T"), 2, "confirmed"),
    ("confirm_temperature", (4007,"ADUS","00T"), (4006,"APHT"), 4, "confirmed"),
    ("cancel_temperature", (4007,"ADUS","00T","390"), (101,"EMSR","00T","-1000"), 1, "confirmed"),
    ("start_delay_up", (2030,"ADUS"), (2111,"ADUS"), 3, "confirmed"),
    ("start_delay_up", (2111,"ADUS"), (2111,"ADUS"), 3, "unconfirmed"),
    ("start_delay_down", (2111,"ADUS"), (2111,"ADUS"), 2, "unconfirmed"),
    ("confirm_start_delay", (2111,"ADUS"), (2300,"A000","000","380","0","Ph"), 4, "confirmed"),
    ("confirm_start_delay", (2111,"ADUS"), (2120,"A00S","000","380","3599"), 4, "confirmed"),
    ("cancel_water_prompt", (2111,"ADUS"), (101,"EMSR"), 1, "confirmed"),
    ("cancel_start_delay", (2120,"A00S","000","380","3397"), (101,"EMSR"), 1, "confirmed"),
])
async def test_mapping_exchange(bridge_module, action, before, after, key, result):
    bridge, device, api = await make_bridge(bridge_module, "http://127.0.0.1:9")
    bridge.options.update(control_enabled=True, forward_to_cloud=False)
    async with device, api:
        async def poll(args):
            resp = await device.post('/braumeister/connect', data=message(*args), headers=DEVICE_HEADERS)
            return await resp.read()
        async def queue():
            return await api.post('/api/control', json={'device_id':DEVICE, 'action':action})
        try:
            await poll(before)
            if action in ('confirm_start_delay', 'start_now', 'confirm_water_filled'):
                assert (await queue()).status == 403
                bridge.options['program_control_enabled'] = True
                assert (await queue()).status == 403
                bridge.options['allow_remote_heating'] = True
            assert (await queue()).status == 202
            assert await poll(before) == f'Start\r\n$k={key}\r\nOK\r\nDone\r\n'.encode()
            assert bridge.local_command['result'] == 'sent'
            # A wrong target must not be acknowledged for temperature changes.
            if action in ('temperature_up','temperature_down'):
                assert await poll(before) == bridge_module.LOCAL_ANSWER
                assert bridge.local_command['result'] == 'sent'
            assert await poll(after) == bridge_module.LOCAL_ANSWER
            assert bridge.local_command['result'] == result
            assert await poll(after) == bridge_module.LOCAL_ANSWER  # Never replay a sent key.
        finally:
            await bridge.close_session()


@pytest.mark.parametrize('action,args', [
    ('start_now',(2030,'ADUS')), ('start_now',(2111,'ADUS')),
    ('start_now',(2120,'A00S','000','380','0')),
    ('start_now',(2120,'A00S','000','380','-1')),
    ('start_now',(2120,'A00S','120','380','3531')),
    ('start_now',(2120,'A00S','000','380','3531','Ph')),
    ('start_delay_down',(2030,'ADUS')), ('confirm_water_filled',(2111,'ADUS')),
    ('confirm_start_delay',(2120,'A00S')), ('temperature_up',(101,'EMSR','00T')),
    ('temperature_up',(4007,'ADUS','000')), ('temperature_up',(4007,'ADUS','00T','380','0','PH')),
    ('start_delay_up',(2111,'A000')), ('cancel_start_delay',(2120,'A00S','120')),
])
def test_reject_unobserved_or_unsafe_context(bridge_module, action, args):
    payload = bridge_module.Bridge.split_message(message(*args))[1]
    assert bridge_module.mapping_rule(action, payload) is None


async def test_source_change_and_permission_revocation(bridge_module):
    bridge, device, api = await make_bridge(bridge_module, 'http://127.0.0.1:9')
    bridge.options.update(control_enabled=True, forward_to_cloud=False, program_control_enabled=True, allow_remote_heating=True)
    async with device, api:
        try:
            async def poll(args):
                return await (await device.post('/braumeister/connect',data=message(*args),headers=DEVICE_HEADERS)).read()
            for action, before, changed in [
                ('start_now',(2120,'A00S','000','380','3531'),(2120,'A00S','000','380','0')),
                ('temperature_up',(4007,'ADUS','00T'),(4007,'ADUS','00T','390')),
                ('start_delay_up',(2111,'ADUS'),(2111,'A000')),
                ('confirm_start_delay',(2111,'ADUS'),(2111,'ADUS')),
                ('start_now',(2120,'A00S','000','380','3531'),(2120,'A00S','000','380','3530')),
            ]:
                bridge.options['allow_remote_heating'] = True
                await poll(before)
                assert (await api.post('/api/control',json={'device_id':DEVICE,'action':action})).status == 202
                if action == 'confirm_start_delay' or (action == 'start_now' and changed[-1] == '3530'):
                    bridge.options['allow_remote_heating'] = False
                assert await poll(changed) == bridge_module.LOCAL_ANSWER
                assert bridge.local_command['result'] == 'state_changed'
        finally:
            await bridge.close_session()


@pytest.mark.parametrize('option', ['program_control_enabled', 'allow_remote_heating'])
@pytest.mark.parametrize('action,before', [
    ('confirm_water_filled', (2030, 'ADUS')),
    ('confirm_start_delay', (2111, 'ADUS')),
    ('start_now', (2120, 'A00S', '000', '380', '3500')),
])
async def test_mapping_start_permissions_rechecked(bridge_module, option, action, before):
    bridge, device, api = await make_bridge(bridge_module, '')
    bridge.options.update(control_enabled=True, forward_to_cloud=False,
                          program_control_enabled=True, allow_remote_heating=True)
    async with device, api:
        try:
            await device.post('/braumeister/connect', data=message(*before), headers=DEVICE_HEADERS)
            response = await api.post('/api/control', json={'device_id': DEVICE, 'action': action})
            assert response.status == 202
            bridge.options[option] = False
            response = await device.post('/braumeister/connect', data=message(*before), headers=DEVICE_HEADERS)
            assert await response.read() == bridge_module.LOCAL_ANSWER
            assert bridge.local_command['result'] == 'state_changed'
        finally:
            await bridge.close_session()


@pytest.mark.parametrize('action,target', [
    ('temperature_up', '1030'), ('temperature_up', '1040'), ('temperature_down', '0'),
    ('temperature_up', '-10'), ('temperature_up', '385'),
    ('temperature_down', 'NaN'),
])
def test_manual_temperature_bounds(bridge_module, action, target):
    payload = bridge_module.Bridge.split_message(message(4007, 'ADUS', '00T', target))[1]
    assert bridge_module.mapping_rule(action, payload) is None


def test_manual_temperature_fahrenheit_is_not_inferred(bridge_module):
    raw = message(4007, 'ADUS', '00T').split(b'X')
    raw[2] = b'F'
    payload = bridge_module.Bridge.split_message(b'X'.join(raw))[1]
    assert bridge_module.mapping_rule('temperature_up', payload) is None
    assert bridge_module.mapping_rule('temperature_down', payload) is None


async def test_wrong_countdown_result_does_not_confirm(bridge_module):
    bridge, device, api = await make_bridge(bridge_module, '')
    bridge.options.update(control_enabled=True, forward_to_cloud=False,
                          program_control_enabled=True, allow_remote_heating=True)
    async with device, api:
        try:
            async def poll(*args):
                response = await device.post('/braumeister/connect', data=message(*args), headers=DEVICE_HEADERS)
                return await response.read()
            await poll(2111, 'ADUS')
            assert (await api.post('/api/control', json={'device_id': DEVICE, 'action': 'confirm_start_delay'})).status == 202
            await poll(2111, 'ADUS')
            for wrong in [(2120, 'A000'), (2120, 'A00S', '120'),
                          (2300, 'A000', '000', '380', '0', 'ph'),
                          (2300, 'A000', '000', '380', '1', 'Ph')]:
                assert await poll(*wrong) == bridge_module.LOCAL_ANSWER
                assert bridge.local_command['result'] == 'sent'
            await poll(2120, 'A00S', '000', '380', '3599')
            assert bridge.local_command['result'] == 'confirmed'
        finally:
            await bridge.close_session()
