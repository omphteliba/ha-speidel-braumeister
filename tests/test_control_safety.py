import time

from aiohttp import web
from aiohttp.test_utils import TestServer

from test_bridge import BM_STAT, DEVICE, DEVICE_HEADERS, make_bridge


async def test_local_control_through_device_poll(bridge_module):
    ack = bridge_module.LOCAL_ANSWER
    cloud_answer = ack

    async def reply(request):
        await request.read()
        return web.Response(body=cloud_answer)

    cloud_app = web.Application()
    cloud_app.router.add_post("/braumeister/connect", reply)
    async with TestServer(cloud_app) as cloud:
        bridge, device, api = await make_bridge(bridge_module, str(cloud.make_url("")))
        async with device, api:
            try:
                async def poll(state, slot=0, count=4):
                    body = BM_STAT.replace(b"X2820X", f"X{state}X".encode()).replace(b"XPiX", b"XphX")
                    fields = body.split(b"X")
                    fields[8] = str(count).encode()
                    fields[9] = str(slot).encode()
                    body = b"X".join(fields)
                    response = await device.post("/braumeister/connect", data=body, headers=DEVICE_HEADERS)
                    return await response.read()

                async def enqueue(action):
                    return await api.post("/api/control", json={"device_id": DEVICE, "action": action})

                async def result():
                    return (await (await api.get("/api/control")).json())["result"]

                assert await poll(101) == ack
                assert (await enqueue("open_settings")).status == 403
                bridge.options["control_enabled"] = True
                bridge.devices[DEVICE]["bm_stat_received"] = time.time() - 60
                assert (await enqueue("open_settings")).status == 409
                assert await poll(101) == ack
                assert (await enqueue("open_settings")).status == 202
                assert (await enqueue("open_settings")).status == 409

                cloud_answer = b"Start\r\n$k=2\r\nOK\r\nDone\r\n"
                assert await poll(101) == cloud_answer
                assert await result() == "queued"
                cloud_answer = ack
                assert await poll(101) == b"Start\r\n$k=1\r\nOK\r\nDone\r\n"
                assert await result() == "sent"
                assert await poll(101) == ack
                assert await result() == "sent"
                assert await poll(8101) == ack
                assert await result() == "confirmed"

                assert (await enqueue("close_settings")).status == 202
                assert await poll(2030) == ack
                assert await result() == "state_changed"
                for action in (
                    "select_recipe", "confirm_water_filled", "confirm_malt_pipe_removed",
                    "start_manual_heating", "$k=4",
                ):
                    assert (await enqueue(action)).status == 400

                for action, before, after, key in (
                    ("open_manual", 101, 4006, 2),
                    ("close_manual", 4006, 101, 1),
                    ("open_recipe_list", 101, 6010, 4),
                    ("close_recipe_list", 6010, 101, 1),
                    ("open_recipe_selection", 101, 2015, 3),
                    ("cancel_recipe_selection", 2015, 101, 1),
                ):
                    assert await poll(before) == ack
                    assert (await enqueue(action)).status == 202
                    assert await poll(before) == f"Start\r\n$k={key}\r\nOK\r\nDone\r\n".encode()
                    assert await poll(after) == ack
                    assert await result() == "confirmed"

                assert await poll(2015, count=0) == ack
                assert (await enqueue("recipe_up")).status == 409
                for count in range(1, 6):
                    for action, before, after, key in (
                        ("recipe_up", 0, count - 1, 3),
                        ("recipe_down", count - 1, 0, 2),
                    ):
                        assert await poll(2015, before, count) == ack
                        assert (await enqueue(action)).status == 202
                        assert await poll(2015, before, count) == f"Start\r\n$k={key}\r\nOK\r\nDone\r\n".encode()
                        assert await result() == "sent"
                        assert await poll(2015, after, count) == ack
                        assert await result() == "confirmed"
                assert (await enqueue("recipe_up")).status == 202
                assert await poll(2015, count=4) == ack
                assert await result() == "state_changed"

                async def unavailable(*args):
                    raise OSError("Cloud unavailable")

                bridge.forward_to_cloud = unavailable
                for forwarding in (False, True):
                    bridge.options["forward_to_cloud"] = forwarding
                    assert await poll(101) == ack
                    assert (await enqueue("open_settings")).status == 202
                    assert await poll(101) == b"Start\r\n$k=1\r\nOK\r\nDone\r\n"
                    assert await poll(8101) == ack
                    assert await result() == "confirmed"
            finally:
                await bridge.close_session()
