"""Synthetic program exchanges against a loopback cloud; no real device/cloud."""

import pytest
import time
from aiohttp import web
from aiohttp.test_utils import TestServer

from test_bridge import BM_STAT, DEVICE, DEVICE_HEADERS, make_bridge


def body(state, flags="ph", indicator="000", slot="0", count="5"):
    fields = BM_STAT.split(b"X")
    for index, value in ((3, state), (8, count), (9, slot), (14, flags), (15, indicator)):
        fields[index] = str(value).encode()
    return b"X".join(fields)


@pytest.mark.parametrize(("action", "before", "flags", "indicator", "after", "target_flags", "target_indicator", "key"), [
    ("select_recipe", "2015", "ph", "000", "2030", "ph", "000", 4),
    ("request_program_pause", "2300", "Ph", "000", "2300", "ph", "120", 1),
    ("request_program_pause", "2410", "PH", "000", "2410", "ph", "120", 1),
    ("abort_program", "2300", "ph", "120", "101", "ph", "000", 1),
    ("abort_program", "2410", "ph", "120", "101", "ph", "000", 1),
    ("resume_program", "2300", "ph", "120", "2300", "Ph", "000", 4),
    ("acknowledge_rest_end", "2910", "Pi", "010", "2930", "pi", "000", 4),
    ("acknowledge_rest_end", "2910", "Pi", "010", "2930", "pH", "000", 4),
    ("acknowledge_rest_end", "2910", "PH", "010", "2930", "pH", "000", 4),
    ("acknowledge_rest_end", "2910", "PH", "010", "2930", "pi", "000", 4),
    ("confirm_malt_pipe_removed", "2930", "pi", "000", "2960", "pi", "000", 4),
    ("confirm_malt_pipe_removed", "2930", "pH", "000", "2960", "pH", "000", 4),
    ("start_boil", "2960", "pi", "000", "3010", "PH", "000", 4),
    ("start_boil", "2960", "pH", "000", "3010", "PH", "000", 4),
    ("resume_program", "2820", "ph", "120", "2820", "PH", "000", 4),
    ("request_program_pause", "3010", "PH", "000", "3010", "ph", "120", 1),
    ("request_program_pause", "3010", "qH", "000", "3010", "ph", "120", 1),
    ("request_program_pause", "3010", "qH", "0D0", "3010", "ph", "120", 1),
    ("resume_program", "3010", "ph", "120", "3010", "PH", "000", 4),
    ("resume_program", "3010", "ph", "120", "3010", "qH", "000", 4),
    ("abort_program", "3010", "ph", "120", "101", "ph", "000", 1),
    ("confirm_lid_removed", "3010", "qH", "0D0", "3010", "qH", "000", 4),
    ("confirm_lid_removed", "3010", "qH", "0DT", "3010", "qH", "00T", 4),
    ("request_program_pause", "3080", "qH", "010", "3080", "ph", "120", 1),
    ("resume_program", "3080", "ph", "120", "3080", "qH", "010", 4),
    ("acknowledge_hop_addition", "3080", "qH", "010", "3070", "qH", "000", 4),
    ("request_program_pause", "3450", "ph", "010", "3450", "ph", "120", 1),
    ("resume_program", "3450", "ph", "120", "3450", "ph", "010", 4),
    ("acknowledge_brew_complete", "3450", "ph", "010", "3510", "ph", "000", 4),
    ("confirm_whirlpool", "3510", "ph", "000", "3610", "ph", "000", 4),
    ("finish_brewing", "3610", "ph", "000", "101", "ph", "000", 4),
])
async def test_exact_program_exchange_and_indicator_confirmation(
        bridge_module, action, before, flags, indicator, after, target_flags, target_indicator, key):
    ack = bridge_module.LOCAL_ANSWER
    cloud_reply = ack

    async def reply(request):
        await request.read()
        return web.Response(body=cloud_reply)

    app = web.Application()
    app.router.add_post("/braumeister/connect", reply)
    async with TestServer(app) as cloud:
        bridge, device, api = await make_bridge(bridge_module, str(cloud.make_url("")))
        async with device, api:
            bridge.options.update(control_enabled=True)

            async def poll(state, f, i):
                response = await device.post("/braumeister/connect", data=body(state, f, i), headers=DEVICE_HEADERS)
                return await response.read()

            async def queue():
                return await api.post("/api/control", json={"device_id": DEVICE, "action": action})

            try:
                await poll(before, flags, indicator)
                bridge.devices[DEVICE]["rz"] = "FW;TEST;1;4\r\n0X1\r\n1X1\r\n2X1\r\n3X1;0;0"
                if action in ("resume_program", "start_boil"):
                    assert (await queue()).status == 403
                    bridge.options["program_control_enabled"] = True
                    assert (await queue()).status == 403
                    bridge.options["allow_remote_heating"] = True
                assert (await queue()).status == 202
                assert (await queue()).status == 409
                # A cloud command is forwarded unchanged; never append a second key.
                cloud_reply = b"Start\r\n$k=2\r\nOK\r\nDone\r\n"
                assert await poll(before, flags, indicator) == cloud_reply
                assert bridge.local_command["result"] == "queued"
                cloud_reply = ack
                assert await poll(before, flags, indicator) == f"Start\r\n$k={key}\r\nOK\r\nDone\r\n".encode()
                assert bridge.local_command["result"] == "sent"
                assert await poll(before, flags, indicator) == ack
                assert bridge.local_command["result"] == "sent"
                if action in bridge_module.PROGRAM_KEYS:
                    # A matching screen alone must never confirm the command.
                    await poll(after, "invalid", target_indicator)
                    assert bridge.local_command["result"] == "sent"
                    # Matching code/actuators alone is insufficient.
                    wrong_indicator = "000" if target_indicator == "120" else "120"
                    await poll(after, target_flags, wrong_indicator)
                    assert bridge.local_command["result"] == "sent"
                await poll(after, target_flags, target_indicator)
                assert bridge.local_command["result"] == "confirmed"
                assert await poll(after, target_flags, target_indicator) == ack
            finally:
                await bridge.close_session()


@pytest.mark.parametrize(("action", "screen", "flags", "indicator"), [
    ("resume_program", "2410", "ph", "120"),
    ("resume_program", "2300", "ph", "000"),
    ("resume_program", "2300", "PH", "120"),
    ("abort_program", "2410", "ph", "000"),
    ("abort_program", "2030", "ph", "120"),
    ("request_program_pause", "2310", "ph", "000"),
    ("request_program_pause", "2410", "ph", "120"),
    ("request_program_pause", "2410", "PH", "220"),
    ("select_recipe", "2015", "ph", "120"),
    ("acknowledge_rest_end", "2910", "qi", "010"),
    ("acknowledge_rest_end", "2910", "Pi", "120"),
    ("confirm_malt_pipe_removed", "2930", "qi", "000"),
    ("start_boil", "2960", "pi", "120"),
    ("start_boil", "3010", "qH", "000"),
    ("request_program_pause", "3010", "qH", "0DT"),
    ("request_program_pause", "3010", "qH", "00T"),
    ("request_program_pause", "3010", "qH", "00Z"),
    ("abort_program", "3010", "qH", "0D0"),
    ("abort_program", "3080", "ph", "120"),
    ("abort_program", "3450", "ph", "120"),
    ("request_program_pause", "2910", "Pi", "010"),
    ("confirm_lid_removed", "3010", "qH", "000"),
    ("acknowledge_hop_addition", "3080", "ph", "120"),
    ("acknowledge_brew_complete", "3450", "ph", "120"),
    ("confirm_whirlpool", "3610", "ph", "000"),
    ("finish_brewing", "3510", "ph", "000"),
])
def test_program_transition_refuses_unverified_context(bridge_module, action, screen, flags, indicator):
    assert bridge_module.program_transition(action, screen, flags, indicator) is None


@pytest.mark.parametrize(("action", "source", "changed"), [
    ("acknowledge_rest_end", ("2910", "Pi", "010"), ("2910", "qi", "010")),
    ("acknowledge_rest_end", ("2910", "Pi", "010"), ("2930", "pi", "000")),
    ("confirm_lid_removed", ("3010", "qH", "0D0"), ("3010", "qH", "0DT")),
    ("request_program_pause", ("3010", "qH", "000"), ("3010", "ph", "120")),
    ("abort_program", ("3010", "ph", "120"), ("3010", "qH", "000")),
    ("start_boil", ("2960", "pi", "000"), ("3010", "PH", "000")),
    ("acknowledge_hop_addition", ("3080", "qH", "010"), ("3080", "ph", "120")),
    ("acknowledge_brew_complete", ("3450", "ph", "010"), ("3450", "ph", "120")),
    ("confirm_whirlpool", ("3510", "ph", "000"), ("3610", "ph", "000")),
    ("finish_brewing", ("3610", "ph", "000"), ("101", "ph", "000")),
])
async def test_later_program_rechecks_source_before_dispatch(bridge_module, action, source, changed):
    async def reply(request):
        await request.read()
        return web.Response(body=bridge_module.LOCAL_ANSWER)

    app = web.Application()
    app.router.add_post("/braumeister/connect", reply)
    async with TestServer(app) as cloud:
        bridge, device, api = await make_bridge(bridge_module, str(cloud.make_url("")))
        async with device, api:
            bridge.options.update(control_enabled=True, program_control_enabled=True, allow_remote_heating=True)
            try:
                await device.post("/braumeister/connect", data=body(*source), headers=DEVICE_HEADERS)
                assert (await api.post("/api/control", json={"device_id": DEVICE, "action": action})).status == 202
                response = await device.post("/braumeister/connect", data=body(*changed), headers=DEVICE_HEADERS)
                assert await response.read() == bridge_module.LOCAL_ANSWER
                assert bridge.local_command["result"] == "state_changed"
            finally:
                await bridge.close_session()


@pytest.mark.parametrize(("action", "source"), [
    ("start_boil", ("2960", "pi", "000")),
    ("resume_program", ("3010", "ph", "120")),
])
@pytest.mark.parametrize("option", ["program_control_enabled", "allow_remote_heating"])
async def test_later_heating_actions_recheck_revoked_permission(bridge_module, action, source, option):
    async def reply(request):
        await request.read()
        return web.Response(body=bridge_module.LOCAL_ANSWER)

    app = web.Application()
    app.router.add_post("/braumeister/connect", reply)
    async with TestServer(app) as cloud:
        bridge, device, api = await make_bridge(bridge_module, str(cloud.make_url("")))
        async with device, api:
            bridge.options.update(control_enabled=True, program_control_enabled=True, allow_remote_heating=True)
            try:
                await device.post("/braumeister/connect", data=body(*source), headers=DEVICE_HEADERS)
                assert (await api.post("/api/control", json={"device_id": DEVICE, "action": action})).status == 202
                bridge.options[option] = False
                response = await device.post("/braumeister/connect", data=body(*source), headers=DEVICE_HEADERS)
                assert await response.read() == bridge_module.LOCAL_ANSWER
                assert bridge.local_command["result"] == "state_changed"
            finally:
                await bridge.close_session()


async def test_rest_end_api_rejects_qi_and_stale_status(bridge_module):
    bridge, device, api = await make_bridge(bridge_module, "")
    async with device, api:
        bridge.options.update(control_enabled=True, forward_to_cloud=False)
        try:
            for flags, age in (("qi", 0), ("Pi", bridge_module.CONTROL_TIMEOUT + 1)):
                await device.post("/braumeister/connect", data=body("2910", flags, "010"), headers=DEVICE_HEADERS)
                bridge.devices[DEVICE]["bm_stat_received"] = time.time() - age
                response = await api.post("/api/control", json={"device_id": DEVICE, "action": "acknowledge_rest_end"})
                assert response.status == 409
                assert bridge.local_command is None
        finally:
            await bridge.close_session()


async def test_program_dispatch_rechecks_indicator_and_resume_permissions(bridge_module):
    async def reply(request):
        await request.read()
        return web.Response(body=bridge_module.LOCAL_ANSWER)

    app = web.Application()
    app.router.add_post("/braumeister/connect", reply)
    async with TestServer(app) as cloud:
        bridge, device, api = await make_bridge(bridge_module, str(cloud.make_url("")))
        async with device, api:
            bridge.options.update(control_enabled=True, program_control_enabled=True, allow_remote_heating=True)
            try:
                async def poll(indicator):
                    response = await device.post("/braumeister/connect", data=body("2300", "ph", indicator), headers=DEVICE_HEADERS)
                    return await response.read()

                await poll("000")
                assert (await api.post("/api/control", json={"device_id": DEVICE, "action": "request_program_pause"})).status == 202
                # A physical key changed the dialog after enqueueing: do not turn
                # the queued first Cancel into a final-abort second Cancel.
                assert await poll("120") == bridge_module.LOCAL_ANSWER
                assert bridge.local_command["result"] == "state_changed"
                assert (await api.post("/api/control", json={"device_id": DEVICE, "action": "resume_program"})).status == 202
                bridge.options["allow_remote_heating"] = False
                assert await poll("120") == bridge_module.LOCAL_ANSWER
                assert bridge.local_command["result"] == "state_changed"
            finally:
                await bridge.close_session()

@pytest.mark.parametrize('count', range(1, 10))
async def test_select_recipe_uses_live_count_and_rechecks_before_dispatch(bridge_module, count):
    ack = bridge_module.LOCAL_ANSWER

    async def reply(request):
        await request.read()
        return web.Response(body=ack)

    app = web.Application()
    app.router.add_post('/braumeister/connect', reply)
    async with TestServer(app) as cloud:
        bridge, device, api = await make_bridge(bridge_module, str(cloud.make_url('')))
        async with device, api:
            try:
                bridge.options['control_enabled'] = True

                async def poll(n, slot):
                    response = await device.post('/braumeister/connect',
                        data=body('2015', slot=str(slot), count=str(n)), headers=DEVICE_HEADERS)
                    return await response.read()

                async def queue():
                    return await api.post('/api/control', json={'device_id': DEVICE, 'action': 'select_recipe'})

                await poll(count, count)
                assert (await queue()).status == 409
                await poll(count, count - 1)
                assert (await queue()).status == 202
                assert await poll(count, count - 1) == b'Start\r\n$k=4\r\nOK\r\nDone\r\n'
                bridge.local_command = None
                await poll(count, 0)
                assert (await queue()).status == 202
                assert await poll(1 if count != 1 else 2, 0) == ack
                assert bridge.local_command['result'] == 'state_changed'
            finally:
                await bridge.close_session()
