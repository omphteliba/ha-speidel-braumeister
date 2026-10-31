"""Braumeister Bridge: receive the Braumeister's cloud traffic locally.

The Braumeister (firmware 1.1.27) POSTs its status to http://api2.myspeidel.com
about once per second. This app

* answers DNS queries for that hostname with the Home Assistant host's IP and
  forwards every other query to an upstream DNS server,
* listens on port 80, keeps the latest message per device and forwards the
  request to the real Speidel cloud (falling back to a local "OK" answer),
* passes every other request on port 80 to another local service, e.g.
  emulated_hue moved to port 8300,
* serves the latest messages as JSON on 127.0.0.1 for the integration.

See docs/DEVICE_PROTOCOL.md in the repository for the protocol.
"""

from __future__ import annotations

import asyncio
import json
import ipaddress
import logging
import os
import socket
import struct
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

from aiohttp import ClientSession, ClientTimeout, TCPConnector, AsyncResolver, web
from aiohttp.abc import AbstractResolver

_LOGGER = logging.getLogger("braumeister_bridge")

OPTIONS_FILE = Path(os.environ.get("BRIDGE_OPTIONS", "/data/options.json"))
DEFAULTS: dict[str, Any] = {
    "bridge_ip": "",
    "cloud_host": "api2.myspeidel.com",
    "forward_to_cloud": True,
    "upstream_dns": "",
    "dns_port": 0,
    "cloud_dns": ["1.1.1.1", "1.0.0.1"],
    "http_port": 80,
    "passthrough_url": "",
    "api_port": 8642,
    "api_host": "127.0.0.1",
    "log_level": "info",
    # Where device requests are forwarded; empty = http://<cloud_host> (for tests)
    "cloud_url": "",
}

LOCAL_ANSWER = b"Start\r\nOK\r\nDone\r\n"
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


def load_options(path: Path = OPTIONS_FILE) -> dict[str, Any]:
    options = dict(DEFAULTS)
    if path.exists():
        options.update({k: v for k, v in json.loads(path.read_text()).items() if v is not None})
    return options


def detect_host_ip() -> str:
    """IP of the interface that routes to the internet (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]


def detect_upstream_dns() -> str:
    for line in Path("/etc/resolv.conf").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            return parts[1]
    return "1.1.1.1"


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------

def parse_question(packet: bytes) -> tuple[str, int, int] | None:
    """Return (name, qtype, end offset of the question) of the first question."""
    if len(packet) < 12 or struct.unpack(">H", packet[4:6])[0] < 1:
        return None
    labels, pos = [], 12
    while pos < len(packet):
        length = packet[pos]
        if length == 0:
            pos += 1
            break
        if length & 0xC0:  # compression is not used in questions
            return None
        labels.append(packet[pos + 1:pos + 1 + length].decode("ascii", "replace"))
        pos += 1 + length
    if pos + 4 > len(packet):
        return None
    qtype = struct.unpack(">H", packet[pos:pos + 2])[0]
    return ".".join(labels).lower(), qtype, pos + 4


def build_answer(query: bytes, question_end: int, qtype: int, ip: str, ttl: int = 60) -> bytes:
    """Answer the query with one A record (or no record for other types)."""
    flags = 0x8180 | (struct.unpack(">H", query[2:4])[0] & 0x0100)  # keep RD
    answers = 1 if qtype == 1 else 0
    header = query[:2] + struct.pack(">HHHHH", flags, 1, answers, 0, 0)
    body = query[12:question_end]
    if answers:
        body += b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, ttl, 4) + socket.inet_aton(ip)
    return header + body


class DnsProtocol(asyncio.DatagramProtocol):
    def __init__(self, cloud_host: str, bridge_ip: str, upstream: str, upstream_port: int = 53) -> None:
        self.cloud_host = cloud_host.lower()
        self.bridge_ip = bridge_ip
        self.upstream = upstream
        self.upstream_port = upstream_port
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        question = parse_question(data)
        if question and question[0] == self.cloud_host:
            _LOGGER.info("DNS %s from %s -> %s", question[0], addr[0], self.bridge_ip)
            self.transport.sendto(build_answer(data, question[2], question[1], self.bridge_ip), addr)
            return
        asyncio.ensure_future(self._forward(data, addr))

    async def _forward(self, data: bytes, addr: tuple[str, int]) -> None:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()

        class Relay(asyncio.DatagramProtocol):
            def datagram_received(self, reply: bytes, _addr: tuple[str, int]) -> None:
                if not future.done():
                    future.set_result(reply)

        transport, _ = await loop.create_datagram_endpoint(Relay, remote_addr=(self.upstream, self.upstream_port))
        try:
            transport.sendto(data)
            self.transport.sendto(await asyncio.wait_for(future, 3), addr)
        except asyncio.TimeoutError:
            _LOGGER.debug("Upstream DNS timeout for %s", addr[0])
        finally:
            transport.close()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class PublicCloudResolver(AbstractResolver):
    """Resolve cloud names outside AdGuard and reject local/loopback answers."""

    def __init__(self, nameservers):
        if not nameservers:
            raise ValueError("cloud_dns must specify a resolver without DNS rewrites")
        self.delegate = AsyncResolver(nameservers=nameservers)

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await self.delegate.resolve(host, port, family)
        if not records or any(not ipaddress.ip_address(r["host"]).is_global for r in records):
            raise OSError("Cloud DNS returned a non-public address; forwarding blocked")
        return records

    async def close(self):
        await self.delegate.close()


class Bridge:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.cloud_host = options["cloud_host"].lower()
        self.devices: dict[str, dict[str, Any]] = {}
        self.session: ClientSession | None = None
        self.cloud_session: ClientSession | None = None
        self.cloud_resolver = None

    async def start_session(self, _app: web.Application | None = None) -> None:
        self.session = ClientSession(timeout=ClientTimeout(total=8), auto_decompress=False)
        # cloud_url is an internal loopback-test override, not an app option.
        if self.options["forward_to_cloud"] and not self.options["cloud_url"]:
            self.cloud_resolver = PublicCloudResolver(self.options["cloud_dns"])
            self.cloud_session = ClientSession(
                connector=TCPConnector(resolver=self.cloud_resolver, family=socket.AF_INET, ttl_dns_cache=60),
                timeout=ClientTimeout(total=8), auto_decompress=False,
            )

    async def close_session(self, _app: web.Application | None = None) -> None:
        if self.cloud_session:
            await self.cloud_session.close()
        if self.cloud_resolver:
            await self.cloud_resolver.close()
        if self.session:
            await self.session.close()

    # -- port 80 ------------------------------------------------------------

    async def handle_port80(self, request: web.Request) -> web.StreamResponse:
        host = request.headers.get("Host", "").split(":")[0].lower()
        if host == self.cloud_host:
            return await self.handle_device(request)
        if self.options["passthrough_url"]:
            return await self.passthrough(request)
        return web.Response(status=404, text="Not found")

    async def handle_device(self, request: web.Request) -> web.StreamResponse:
        body = await request.read()
        self.record(request.path, body, request.remote)

        status, headers, answer, source = 200, {"Content-Type": "text/plain; charset=UTF-8"}, LOCAL_ANSWER, "local"
        if self.options["forward_to_cloud"]:
            try:
                status, headers, answer = await self.forward_to_cloud(request, body)
                source = "cloud"
            except Exception as err:  # cloud down or unreachable: answer locally
                _LOGGER.warning("Cloud forward failed (%s), answering locally", err)

        device = self.device_for(body)
        if device:
            device["last_response"] = answer.decode("latin-1", "replace")
            device["last_response_source"] = source

        response = web.StreamResponse(status=status, headers=headers)
        response.enable_chunked_encoding()  # the real server answers chunked
        response.force_close()
        await response.prepare(request)
        await response.write(answer)
        await response.write_eof()
        return response

    async def forward_to_cloud(self, request: web.Request, body: bytes) -> tuple[int, dict[str, str], bytes]:
        # Dedicated resolver bypasses the host/AdGuard rewrite.
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        base = self.options["cloud_url"] or f"http://{self.options['cloud_host']}"
        url = base.rstrip("/") + request.path_qs
        headers["Host"] = self.options["cloud_host"]
        async with (self.cloud_session or self.session).request(
            request.method, url, data=body, headers=headers, allow_redirects=False
        ) as resp:
            answer = await resp.read()
            out = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}
            return resp.status, out, answer

    async def passthrough(self, request: web.Request) -> web.StreamResponse:
        url = self.options["passthrough_url"].rstrip("/") + request.path_qs
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["Host"] = request.headers.get("Host", "")
        try:
            async with self.session.request(
                request.method, url, data=await request.read(), headers=headers, allow_redirects=False
            ) as resp:
                body = await resp.read()
                out = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}
                return web.Response(status=resp.status, body=body, headers=out)
        except Exception as err:
            _LOGGER.warning("Passthrough to %s failed: %s", url, err)
            return web.Response(status=502, text="Bad gateway")

    # -- device state -------------------------------------------------------

    @staticmethod
    def split_message(body: bytes) -> tuple[str, str] | None:
        text = unquote_plus(body.decode("latin-1", "replace")).strip()
        if "=" not in text:
            return None
        kind, payload = text.split("=", 1)
        return kind, payload

    def device_for(self, body: bytes) -> dict[str, Any] | None:
        message = self.split_message(body)
        if not message:
            return None
        parts = message[1].split(";")
        return self.devices.get(parts[1]) if len(parts) > 1 else None

    def record(self, path: str, body: bytes, remote: str | None) -> None:
        message = self.split_message(body)
        if not message:
            _LOGGER.debug("Unrecognized request to %s from %s", path, remote)
            return
        kind, payload = message
        parts = payload.split(";")
        if len(parts) < 2:
            return
        device_id = parts[1]
        device = self.devices.setdefault(device_id, {"device_id": device_id})
        device[kind] = payload
        device[f"{kind}_received"] = time.time()
        device["remote"] = remote
        _LOGGER.debug("%s from %s (%s)", kind, device_id, remote)
        if kind == "bm_stat" and len(parts) > 3:
            self.log_state_change(device, parts[3])

    @staticmethod
    def log_state_change(device: dict[str, Any], status: str) -> None:
        """Log every change of state code, actuator flags or alarm indicator (fields 3, 14, 15).

        The device sends about once per second; this keeps short events such as a
        hop-addition beep visible in the log even though the integration polls less often.
        """
        fields = status.split("X")
        if len(fields) < 16:
            return
        key = (fields[3], fields[14], fields[15])
        if device.get("last_state") != key:
            _LOGGER.info(
                "state %s flags %s indicator %s (temp %s, target %s, step %s/%s s, rest %s, hop %s)",
                fields[3], fields[14], fields[15], fields[5].strip(), fields[4], fields[7], fields[6],
                fields[10], fields[11],
            )
            device["last_state"] = key

    # -- local API ----------------------------------------------------------

    async def api_status(self, request: web.Request) -> web.Response:
        device_id = request.query.get("device")
        devices = list(self.devices.values())
        if device_id:
            devices = [d for d in devices if d["device_id"].lower() == device_id.lower()]
        return web.json_response({"now": time.time(), "devices": devices})

    async def api_health(self, _request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "devices": len(self.devices)})


def build_apps(bridge: Bridge) -> tuple[web.Application, web.Application]:
    """The port-80 app and the local status API app."""
    port80 = web.Application()
    port80.router.add_route("*", "/{tail:.*}", bridge.handle_port80)
    api = web.Application()
    api.router.add_get("/api/status", bridge.api_status)
    api.router.add_get("/api/health", bridge.api_health)
    return port80, api


async def main() -> None:
    options = load_options()
    logging.basicConfig(
        level=getattr(logging, str(options["log_level"]).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    bridge_ip = options["bridge_ip"] or detect_host_ip()
    upstream = options["upstream_dns"] or detect_upstream_dns()
    bridge = Bridge(options)
    await bridge.start_session()

    loop = asyncio.get_running_loop()
    if options["dns_port"]:
        await loop.create_datagram_endpoint(
            lambda: DnsProtocol(options["cloud_host"], bridge_ip, upstream),
            local_addr=("0.0.0.0", int(options["dns_port"])),
        )
        _LOGGER.info("DNS on port %s: %s -> %s, other names -> %s",
                     options["dns_port"], options["cloud_host"], bridge_ip, upstream)

    port80, api = build_apps(bridge)
    runners = []
    for app, host, port in ((port80, "0.0.0.0", options["http_port"]),
                            (api, options["api_host"], options["api_port"])):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, host, int(port)).start()
        runners.append(runner)
    _LOGGER.info("HTTP on port %s (passthrough: %s), API on %s:%s",
                 options["http_port"], options["passthrough_url"] or "off",
                 options["api_host"], options["api_port"])

    try:
        await asyncio.Event().wait()
    finally:
        for runner in runners:
            await runner.cleanup()
        await bridge.close_session()


if __name__ == "__main__":
    asyncio.run(main())
