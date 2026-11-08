"""Recipe upload: replays the cloud's observed $d=A / $rz sync against a loopback cloud."""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from test_bridge import DEVICE, DEVICE_HEADERS, make_bridge
from test_program_control import body

WEIZEN = {
    "name": "Weizen", "mash_in": 40,
    "rests": [[44, 20], [52, 20], [63, 35], [73, 35], [78, 10]],
    "boil_time": 90, "hops": [90, 15],
}
TEST = {"name": "test 10 minute", "mash_in": 40, "rests": [[40, 1]], "boil_time": 20, "hops": [10, 11, 11]}


def test_recipe_lines_match_captured_cloud_commands(bridge_module):
    # Both lines were sent by the real cloud (captures, anonymized names unchanged).
    assert bridge_module.recipe_line(0, WEIZEN) == "0X40X44X20X52X20X63X35X73X35X78X10X90X103X90X15X0X0X0X0.Weizen"
    assert bridge_module.recipe_line(2, TEST) == "2X40X40X1X0X0X0X0X0X0X0X0X20X103X10X11X11X0X0X0.test 10 minute"


def test_recipe_line_fahrenheit(bridge_module):
    # Matches the °F recipe list seen on a device: mash-in 104, boil 217.
    line = bridge_module.recipe_line(0, {"name": "F", "mash_in": 40, "rests": [[50, 10]], "boil_time": 60}, fahrenheit=True)
    assert line == "0X104X122X10X0X0X0X0X0X0X0X0X60X217X0X0X0X0X0X0.F"


@pytest.mark.parametrize("change", [
    {"name": ""}, {"name": "fifteen chars!!"}, {"name": "Bier;$k=4"}, {"name": "Bräu"}, {"name": " IPA"},
    {"mash_in": 19}, {"mash_in": 81}, {"mash_in": 40.5}, {"mash_in": True},
    {"rests": []}, {"rests": [[50, 10]] * 6}, {"rests": [[50]]}, {"rests": [[85, 10]]}, {"rests": [[50, 0]]},
    {"boil_time": 0}, {"boil_time": 181},
    {"hops": [91]}, {"hops": [0]}, {"hops": [10] * 7},
    {"extra": 1},
])
def test_recipe_line_rejects_invalid_values(bridge_module, change):
    with pytest.raises(ValueError):
        bridge_module.recipe_line(0, {**WEIZEN, **change})


async def test_recipe_upload_replays_cloud_sync(bridge_module):
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
            async def poll(count, state="101", flags="ph"):
                response = await device.post(
                    "/braumeister/connect", data=body(state, flags, count=count), headers=DEVICE_HEADERS)
                return await response.read()

            def upload(recipes):
                return api.post("/api/recipes", json={"device_id": DEVICE, "recipes": recipes})

            try:
                await poll("6")
                assert (await upload([WEIZEN])).status == 403  # off by default
                bridge.options["recipe_write_enabled"] = True
                assert (await upload([{**WEIZEN, "mash_in": 99}])).status == 400
                assert (await upload([WEIZEN] * 10)).status == 400
                await poll("6", "4006")
                assert (await upload([WEIZEN])).status == 409  # only from the main menu
                await poll("6", "101", "Ph")
                assert (await upload([WEIZEN])).status == 409  # pump must be off
                await poll("6")
                assert (await upload([WEIZEN, TEST])).status == 202
                assert (await upload([WEIZEN])).status == 409
                assert (await api.post("/api/control", json={"device_id": DEVICE, "action": "open_manual"})).status == 403

                # A cloud command passes unchanged and delays the upload.
                cloud_reply = b"Start\r\n$k=2\r\nOK\r\nDone\r\n"
                assert await poll("6") == cloud_reply
                cloud_reply = ack
                assert await poll("6") == b"Start\r\n$d=A\r\nOK\r\nDone\r\n"
                assert await poll("6") == ack  # waits for field 8 to drop
                assert await poll("0") == b"Start\r\n$rz=" + bridge_module.recipe_line(0, WEIZEN).encode() + b"\r\nOK\r\nDone\r\n"
                assert await poll("0") == ack
                assert await poll("1") == b"Start\r\n$rz=" + bridge_module.recipe_line(1, TEST).encode() + b"\r\nOK\r\nDone\r\n"
                assert bridge.recipe_job["result"] == "sending"
                assert await poll("2") == ack
                status = await (await api.get("/api/recipes")).json()
                assert status == {"device_id": DEVICE, "result": "confirmed", "recipes": 2, "written": 2}
                assert await poll("2") == ack
            finally:
                await bridge.close_session()


async def test_recipe_upload_resends_then_gives_up(bridge_module, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: clock[0])
    app = web.Application()

    async def reply(request):
        await request.read()
        return web.Response(body=bridge_module.LOCAL_ANSWER)

    app.router.add_post("/braumeister/connect", reply)
    async with TestServer(app) as cloud:
        bridge, device, api = await make_bridge(bridge_module, str(cloud.make_url("")))
        async with device, api:
            async def poll(count, state="101"):
                response = await device.post(
                    "/braumeister/connect", data=body(state, "ph", count=count), headers=DEVICE_HEADERS)
                return await response.read()

            try:
                bridge.options["recipe_write_enabled"] = True
                await poll("3")
                assert (await api.post("/api/recipes", json={"device_id": DEVICE, "recipes": [WEIZEN]})).status == 202
                for _ in range(bridge_module.RECIPE_ATTEMPTS):
                    assert await poll("3") == b"Start\r\n$d=A\r\nOK\r\nDone\r\n"
                    clock[0] += bridge_module.CONTROL_TIMEOUT
                assert await poll("3") == bridge_module.LOCAL_ANSWER
                assert bridge.recipe_job["result"] == "unconfirmed"
            finally:
                await bridge.close_session()


async def test_recipe_upload_stops_when_device_leaves_menu(bridge_module):
    app = web.Application()

    async def reply(request):
        await request.read()
        return web.Response(body=bridge_module.LOCAL_ANSWER)

    app.router.add_post("/braumeister/connect", reply)
    async with TestServer(app) as cloud:
        bridge, device, api = await make_bridge(bridge_module, str(cloud.make_url("")))
        async with device, api:
            async def poll(count, state="101"):
                response = await device.post(
                    "/braumeister/connect", data=body(state, "ph", count=count), headers=DEVICE_HEADERS)
                return await response.read()

            try:
                bridge.options["recipe_write_enabled"] = True
                await poll("3")
                assert (await api.post("/api/recipes", json={"device_id": DEVICE, "recipes": [WEIZEN]})).status == 202
                assert await poll("3") == b"Start\r\n$d=A\r\nOK\r\nDone\r\n"
                assert await poll("0", "2015") == bridge_module.LOCAL_ANSWER
                assert bridge.recipe_job["result"] == "state_changed"
            finally:
                await bridge.close_session()
