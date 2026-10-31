"""Tests for the Braumeister Bridge app (no traffic leaves the machine)."""

import asyncio
import socket
import struct

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

DEVICE = "1234567890ABCDEF"
BM_STAT = (
    f"bm_stat=V1.1.27%20Sep%2012%202018;{DEVICE};1793380000;"
    "0X07:37XCX2820X400X%2040.5X60X16X5X2X0X0X55XA00SXPiX000X0X0X0;00000000;00000000\r\n "
).encode()
DEVICE_HEADERS = {
    "Host": "api2.myspeidel.com",
    "Authorization": "Basic dGVzdDp0ZXN0",
    "Content-Type": "application/x-www-form-urlencoded",
}


def dns_query(name: str, qtype: int = 1) -> bytes:
    labels = b"".join(bytes([len(p)]) + p.encode() for p in name.split("."))
    return struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + labels + b"\0" + struct.pack(">HH", qtype, 1)


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


def test_dns_answers_cloud_host(bridge_module):
    protocol = bridge_module.DnsProtocol("api2.myspeidel.com", "192.0.2.10", "192.0.2.1")
    protocol.transport = FakeTransport()
    protocol.datagram_received(dns_query("API2.myspeidel.com"), ("192.0.2.50", 5353))
    answer, addr = protocol.transport.sent[0]
    assert addr == ("192.0.2.50", 5353)
    assert answer[:2] == b"\x12\x34"
    assert struct.unpack(">H", answer[6:8])[0] == 1
    assert answer[-4:] == socket.inet_aton("192.0.2.10")


def test_dns_no_ipv6_for_cloud_host(bridge_module):
    protocol = bridge_module.DnsProtocol("api2.myspeidel.com", "192.0.2.10", "192.0.2.1")
    protocol.transport = FakeTransport()
    protocol.datagram_received(dns_query("api2.myspeidel.com", qtype=28), ("192.0.2.50", 5353))
    assert struct.unpack(">H", protocol.transport.sent[0][0][6:8])[0] == 0


async def test_dns_forwards_other_names(bridge_module):
    loop = asyncio.get_running_loop()
    upstream_seen = []

    class Upstream(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            upstream_seen.append(data)
            self.transport.sendto(data[:2] + b"upstream-answer", addr)

    upstream, _ = await loop.create_datagram_endpoint(Upstream, local_addr=("127.0.0.1", 0))
    port = upstream.get_extra_info("sockname")[1]
    protocol = bridge_module.DnsProtocol("api2.myspeidel.com", "192.0.2.10", "127.0.0.1", port)
    protocol.transport = FakeTransport()
    query = dns_query("example.com")
    protocol.datagram_received(query, ("192.0.2.50", 5353))
    for _ in range(50):
        if protocol.transport.sent:
            break
        await asyncio.sleep(0.02)
    upstream.close()
    assert upstream_seen == [query]
    assert protocol.transport.sent[0][0] == b"\x12\x34upstream-answer"


async def make_bridge(bridge_module, cloud_url, passthrough_url=""):
    options = {**bridge_module.DEFAULTS, "cloud_url": cloud_url, "passthrough_url": passthrough_url}
    bridge = bridge_module.Bridge(options)
    await bridge.start_session()
    port80, api = bridge_module.build_apps(bridge)
    port80_client = TestClient(TestServer(port80))
    api_client = TestClient(TestServer(api))
    await port80_client.start_server()
    await api_client.start_server()
    return bridge, port80_client, api_client


async def test_device_message_forwarded_and_stored(bridge_module):
    received = []

    async def fake_cloud(request):
        received.append((dict(request.headers), await request.read()))
        return web.Response(text="Start\r\n$k=1\r\nOK\r\nDone\r\n")

    cloud_app = web.Application()
    cloud_app.router.add_post("/braumeister/connect", fake_cloud)
    cloud = TestServer(cloud_app)
    await cloud.start_server()
    bridge, port80, api = await make_bridge(bridge_module, str(cloud.make_url("")))
    try:
        resp = await port80.post("/braumeister/connect", data=BM_STAT, headers=DEVICE_HEADERS)
        assert resp.status == 200
        assert await resp.text() == "Start\r\n$k=1\r\nOK\r\nDone\r\n"
        headers, body = received[0]
        assert body == BM_STAT
        assert headers["Host"] == "api2.myspeidel.com"
        assert headers["Authorization"] == "Basic dGVzdDp0ZXN0"

        status = await (await api.get("/api/status", params={"device": DEVICE})).json()
        device = status["devices"][0]
        assert device["device_id"] == DEVICE
        assert "2820" in device["bm_stat"]
        assert device["last_response_source"] == "cloud"
    finally:
        await port80.close()
        await api.close()
        await cloud.close()
        await bridge.close_session()


async def test_local_answer_when_cloud_down(bridge_module):
    bridge, port80, api = await make_bridge(bridge_module, "http://127.0.0.1:9")
    try:
        resp = await port80.post("/braumeister/connect", data=BM_STAT, headers=DEVICE_HEADERS)
        assert resp.status == 200
        assert await resp.text() == "Start\r\nOK\r\nDone\r\n"
    finally:
        await port80.close()
        await api.close()
        await bridge.close_session()


async def test_other_hosts_passed_through(bridge_module):
    async def fake_hue(request):
        return web.Response(text=f"hue {request.path} {request.headers.get('Host')}")

    hue_app = web.Application()
    hue_app.router.add_get("/description.xml", fake_hue)
    hue = TestServer(hue_app)
    await hue.start_server()
    bridge, port80, api = await make_bridge(bridge_module, "http://127.0.0.1:9", str(hue.make_url("")))
    try:
        resp = await port80.get("/description.xml", headers={"Host": "192.0.2.10"})
        assert await resp.text() == "hue /description.xml 192.0.2.10"
    finally:
        await port80.close()
        await api.close()
        await hue.close()
        await bridge.close_session()


async def test_no_passthrough_configured(bridge_module):
    bridge, port80, api = await make_bridge(bridge_module, "http://127.0.0.1:9")
    try:
        resp = await port80.get("/description.xml", headers={"Host": "192.0.2.10"})
        assert resp.status == 404
    finally:
        await port80.close()
        await api.close()
        await bridge.close_session()


def test_state_changes_logged_once(bridge_module, caplog):
    device = {}
    status = "0X10:04XCX3070X1030X 101.5X1200X100X4X0X5X0X256XA00SXqHX{}X0X0X0"
    with caplog.at_level("INFO", logger="braumeister_bridge"):
        bridge_module.Bridge.log_state_change(device, status.format("000"))
        bridge_module.Bridge.log_state_change(device, status.format("000"))
        bridge_module.Bridge.log_state_change(device, status.format("020"))
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 2
    assert "indicator 020" in lines[1]


async def test_long_recipe_command_passed_through(bridge_module, caplog):
    answer = (
        "Start\r\n$rz=0X40X40X1X0X0X0X0X0X0X0X0X10X103X5X2X0X0X0X0.test 10 minuten\r\nOK\r\nDone\r\n"
    )

    async def fake_cloud(request):
        await request.read()
        resp = web.StreamResponse(headers={"Content-Type": "text/plain; charset=UTF-8"})
        resp.enable_chunked_encoding()
        await resp.prepare(request)
        await resp.write(answer.encode())
        await resp.write_eof()
        return resp

    cloud_app = web.Application()
    cloud_app.router.add_post("/braumeister/connect", fake_cloud)
    cloud = TestServer(cloud_app)
    await cloud.start_server()
    bridge, port80, api = await make_bridge(bridge_module, str(cloud.make_url("")))
    try:
        with caplog.at_level("INFO", logger="braumeister_bridge"):
            resp = await port80.post("/braumeister/connect", data=BM_STAT, headers=DEVICE_HEADERS)
        assert await resp.read() == answer.encode()
        assert any("$rz=0X40" in r.getMessage() for r in caplog.records)
    finally:
        await port80.close()
        await api.close()
        await cloud.close()
        await bridge.close_session()


async def test_cloud_answer_never_compressed(bridge_module):
    """Regression: aiohttp asked for gzip and the compressed bytes reached the device."""
    import gzip as gz

    seen = []

    async def fake_cloud(request):
        seen.append(request.headers.get("Accept-Encoding"))
        await request.read()
        body = b"Start\r\n$k=2\r\nOK\r\nDone\r\n"
        if "gzip" in (request.headers.get("Accept-Encoding") or ""):
            return web.Response(body=gz.compress(body), headers={"Content-Encoding": "gzip"})
        return web.Response(body=body)

    async def always_gzip(request):
        await request.read()
        return web.Response(body=gz.compress(b"Start\r\n$k=4\r\nOK\r\nDone\r\n"), headers={"Content-Encoding": "gzip"})

    for handler, expected in ((fake_cloud, b"$k=2"), (always_gzip, b"$k=4")):
        cloud_app = web.Application()
        cloud_app.router.add_post("/braumeister/connect", handler)
        cloud = TestServer(cloud_app)
        await cloud.start_server()
        bridge, port80, api = await make_bridge(bridge_module, str(cloud.make_url("")))
        try:
            resp = await port80.post("/braumeister/connect", data=BM_STAT, headers=DEVICE_HEADERS)
            assert expected in await resp.read()
        finally:
            await port80.close()
            await api.close()
            await cloud.close()
            await bridge.close_session()
    assert seen == ["identity"]
