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
import gzip
import ipaddress
import zlib
import json
import logging
import os
import re
import socket
import stat
import struct
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

from aiohttp import AsyncResolver, ClientSession, ClientTimeout, TCPConnector, web
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver

_LOGGER = logging.getLogger("braumeister_bridge")

OPTIONS_FILE = Path(os.environ.get("BRIDGE_OPTIONS", "/data/options.json"))
DIAGNOSTICS_FILE = Path("/data/diagnostics-summary.jsonl")
DIAGNOSTICS_LIMIT = 1024 * 1024
DEFAULTS: dict[str, Any] = {
    "bridge_ip": "",
    "cloud_host": "api2.myspeidel.com",
    "forward_to_cloud": True,
    "upstream_dns": "",
    "dns_port": 53,
    "cloud_dns": [],
    "http_port": 80,
    "passthrough_url": "",
    "api_port": 8642,
    "api_host": "127.0.0.1",
    "log_level": "info",
    "diagnostics_enabled": False,
    "control_enabled": False,
    "manual_pump_enabled": False,
    "allow_remote_heating": False,
    "program_control_enabled": False,
    "recipe_write_enabled": False,
    # Where device requests are forwarded; empty = http://<cloud_host> (for tests)
    "cloud_url": "",
    # Recipe lists are kept here so they survive restarts (empty = do not store)
    "state_file": "/data/recipes.json",
}

LOCAL_ANSWER = b"Start\r\nOK\r\nDone\r\n"
CONTROL_TIMEOUT = 5
LOCAL_ACTIONS = {
    "open_settings": ("101", "8101", b"$k=1"),
    "close_settings": ("8101", "101", b"$k=1"),
    "open_manual": ("101", "4006", b"$k=2"),
    "close_manual": ("4006", "101", b"$k=1"),
    "pump_on": ("4006", "4006", b"$k=2"),
    "pump_off": ("4006", "4006", b"$k=2"),
    "heater_on": ("4006", "4006", b"$k=3"),
    "heater_off": ("4006", "4006", b"$k=3"),
    "open_recipe_list": ("101", "6010", b"$k=4"),
    "close_recipe_list": ("6010", "101", b"$k=1"),
    "open_recipe_selection": ("101", "2015", b"$k=3"),
    "cancel_recipe_selection": ("2015", "101", b"$k=1"),
    "recipe_down": ("2015", "2015", b"$k=2"),
    "recipe_up": ("2015", "2015", b"$k=3"),
    "select_recipe": ("2015", "2030", b"$k=4"),
}
PROGRAM_KEYS = {"request_program_pause": b"$k=1", "abort_program": b"$k=1", "resume_program": b"$k=4"}


def program_transition(action, screen, flags, indicator):
    """Only individually evidenced stages; a pause is not a final abort."""
    if action == "request_program_pause" and indicator == "000":
        permitted = {"2300": {"ph", "Ph"}, "2410": {"ph", "Ph", "pH", "PH", "pi", "Pi", "qh", "qH", "qi"}}
        if flags in permitted.get(screen, set()):
            return screen, ("ph",), "120"
    if action == "abort_program" and screen in ("2300", "2410") and (flags, indicator) == ("ph", "120"):
        return "101", ("ph",), "000"
    if action == "resume_program" and (screen, flags, indicator) == ("2300", "ph", "120"):
        return "2300", ("Ph",), "000"
    return None


def control_transition(command):
    if command["action"] in PROGRAM_KEYS:
        return command["source_screen"], command["target_screen"], PROGRAM_KEYS[command["action"]]
    return LOCAL_ACTIONS[command["action"]]


ACTUATOR_FLAGS = {
    "pump_on": {"ph": ("Ph",), "pH": ("PH",), "pi": ("Pi",)},
    "pump_off": {"Ph": ("ph",), "PH": ("pH",), "Pi": ("pi",)},
    "heater_on": {"ph": ("pH", "pi"), "Ph": ("PH", "Pi")},
    "heater_off": {"pH": ("ph",), "PH": ("Ph",), "Pi": ("Ph",), "pi": ("ph",)},
}
ACTUATOR_OPTIONS = {
    "pump_on": "manual_pump_enabled",
    "pump_off": "manual_pump_enabled",
    "heater_on": "allow_remote_heating",
}
RECIPE_MOVES = {"recipe_down": 1, "recipe_up": -1}

# Recipe upload replays the cloud's observed sync: "$d=A" (field 8 drops to 0), then one
# "$rz=<slot line>" per slot (field 8 counts up by one each), resent until confirmed.
RECIPE_SLOTS = 9
RECIPE_ATTEMPTS = 3
RECIPE_NAME_LENGTH = 14  # longer names are cut on transfer, as My Speidel does
RECIPE_NAME = re.compile(r"[ -:<-~]+")  # printable ASCII without ";" (ends a line in rz)
# Same shape as the integration's recipe attributes, so a list can be read, edited and written back
RECIPE_KEYS = {"name", "mash_in_temperature", "rests", "boil_minutes"}
RECIPE_OPTIONAL = {"hop_additions", "slot", "boil_temperature"}
BOIL_TEMPERATURE = 103  # default; recipes on the device also had 100 and 102


def _bounded(value: Any, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{what} must be a whole number from {low} to {high}")
    return value


def recipe_line(slot: int, recipe: Any, fahrenheit: bool = False) -> str:
    """Build one slot line (20 X-separated numbers, '.', name) from a validated recipe.

    Temperatures are given in °C and converted when the device is set to °F. A given
    "slot" is ignored (recipes are written in list order); boil_temperature defaults to 103.
    """
    if not isinstance(recipe, dict) or not RECIPE_KEYS <= set(recipe) <= RECIPE_KEYS | RECIPE_OPTIONAL:
        raise ValueError("needs name, mash_in_temperature, rests and boil_minutes (hop_additions optional)")
    name = recipe["name"].strip() if isinstance(recipe["name"], str) else ""
    if not RECIPE_NAME.fullmatch(name):
        raise ValueError("name: printable ASCII without ';' (no umlauts yet)")
    name = name[:RECIPE_NAME_LENGTH].rstrip()

    def temp(celsius: int) -> int:
        return round(celsius * 9 / 5 + 32) if fahrenheit else celsius

    numbers = [slot, temp(_bounded(recipe["mash_in_temperature"], 20, 80, "mash_in_temperature"))]
    rests = recipe["rests"]
    if not isinstance(rests, list) or not 1 <= len(rests) <= 5:
        raise ValueError("rests: a list of 1 to 5 rests")
    for rest in rests:
        if not isinstance(rest, dict) or set(rest) != {"temperature", "minutes"}:
            raise ValueError("Each rest needs temperature and minutes")
        numbers += [temp(_bounded(rest["temperature"], 20, 80, "Rest temperature")),
                    _bounded(rest["minutes"], 1, 180, "Rest minutes")]
    numbers += [0, 0] * (5 - len(rests))
    boil = _bounded(recipe["boil_minutes"], 1, 180, "boil_minutes")
    boil_temperature = _bounded(recipe.get("boil_temperature", BOIL_TEMPERATURE), 95, 105, "boil_temperature")
    numbers += [boil, temp(boil_temperature)]
    hops = recipe.get("hop_additions", [])
    if not isinstance(hops, list) or len(hops) > 6:
        raise ValueError("hop_additions: up to 6, in minutes before the end of the boil")
    hops = [_bounded(hop, 1, boil, "Hop addition") for hop in hops]  # order as given, like the cloud
    numbers += hops + [0] * (6 - len(hops))
    return "X".join(str(number) for number in numbers) + "." + name


HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


def append_diagnostic(path: Path, line: bytes) -> bool:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        with os.fdopen(os.open(path, flags, 0o600), "ab") as output:
            info = os.fstat(output.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size + len(line) > DIAGNOSTICS_LIMIT:
                return False
            output.write(line)
    except OSError:
        return False
    return True


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
    """Use host or explicitly chosen DNS and reject non-public cloud answers."""

    def __init__(self, nameservers):
        self.delegate = (
            AsyncResolver(nameservers=nameservers) if nameservers else DefaultResolver()
        )

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await self.delegate.resolve(host, port, family)
        if not records or any(not ipaddress.ip_address(r["host"]).is_global for r in records):
            raise OSError("Cloud DNS returned a non-public address; forwarding blocked to prevent a loop. Configure cloud_dns with a reachable resolver without the local rewrite")
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
        self.diagnostic_write: asyncio.Task | None = None
        self.diagnostic_missed = 0
        self.local_command: dict[str, Any] | None = None
        self.recipe_job: dict[str, Any] | None = None
        self.state_file = Path(options["state_file"]) if options.get("state_file") else None
        self.load_recipes()

    def pending_control(self) -> dict[str, Any] | None:
        command = self.local_command
        if command and command["result"] in ("queued", "sent") and time.monotonic() >= command["deadline"]:
            command["result"] = "expired" if command["result"] == "queued" else "unconfirmed"
        return command

    def pending_recipe_job(self) -> dict[str, Any] | None:
        job = self.recipe_job
        if job and job["result"] in ("queued", "sending") and time.monotonic() >= job["deadline"]:
            job["result"] = "unconfirmed"
            _LOGGER.warning("Recipe upload to %s timed out after %d of %d steps",
                            job["device_id"], job["step"], len(job["steps"]))
        return job

    def recipe_step(self, device: dict[str, Any], payload: str, can_send: bool) -> bytes | None:
        """Advance the recipe upload on a device poll; return the command to send, if any."""
        job = self.pending_recipe_job()
        if not job or job["result"] not in ("queued", "sending") or job["device_id"] != device["device_id"]:
            return None
        screen, flags, _slot, count = self.control_screen(payload)
        step = job["step"]
        if job["sent_at"] is not None and count == str(job["counts"][step]):
            step = job["step"] = step + 1
            job.update(sent_at=None, attempts=0)
            if step == len(job["steps"]):
                job["result"] = "confirmed"
                _LOGGER.info("Recipe upload to %s confirmed (%d recipes)", job["device_id"], step - 1)
                return None
        if (screen, flags) != ("101", "ph"):
            job["result"] = "state_changed"
            _LOGGER.warning("Recipe upload to %s stopped after %d of %d steps: device left the main menu",
                            job["device_id"], step, len(job["steps"]))
            return None
        now = time.monotonic()
        if job["sent_at"] is not None and now - job["sent_at"] < CONTROL_TIMEOUT:
            return None  # wait for the device to report the new recipe count
        if job["attempts"] >= RECIPE_ATTEMPTS:
            job["result"] = "unconfirmed"
            _LOGGER.warning("Recipe upload to %s unconfirmed at step %d of %d",
                            job["device_id"], step + 1, len(job["steps"]))
            return None
        if not can_send:
            return None
        job.update(attempts=job["attempts"] + 1, sent_at=now, result="sending")
        return job["steps"][step]

    def load_recipes(self) -> None:
        """Restore the last recipe list (rz) of every device."""
        if not self.state_file or not self.state_file.exists():
            return
        try:
            stored = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            _LOGGER.warning("Could not read %s: %s", self.state_file, err)
            return
        for device_id, data in stored.items():
            self.devices[device_id] = {
                "device_id": device_id, "rz": data["rz"], "rz_received": data["rz_received"],
                "rz_saved": data["rz"],  # already on disk: no rewrite on the first rz after a restart
            }
        _LOGGER.info("Restored recipe lists of %d device(s)", len(stored))

    def save_recipes(self) -> None:
        if not self.state_file:
            return
        stored = {d: {"rz": v["rz"], "rz_received": v["rz_received"]} for d, v in self.devices.items() if v.get("rz")}
        try:
            self.state_file.write_text(json.dumps(stored), encoding="utf-8")
        except OSError as err:
            _LOGGER.warning("Could not write %s: %s", self.state_file, err)

    async def start_session(self, _app: web.Application | None = None) -> None:
        # cloud_url is an internal loopback-test override, not an app option.
        if self.options["forward_to_cloud"] and not self.options["cloud_url"]:
            self.cloud_resolver = PublicCloudResolver(self.options["cloud_dns"])
            self.cloud_session = ClientSession(
                connector=TCPConnector(resolver=self.cloud_resolver, family=socket.AF_INET, ttl_dns_cache=60),
                timeout=ClientTimeout(total=8), auto_decompress=False,
            )
        self.session = ClientSession(timeout=ClientTimeout(total=8), auto_decompress=False)

    async def close_session(self, _app: web.Application | None = None) -> None:
        if self.diagnostic_write is not None:
            await self.diagnostic_write
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
        received = time.monotonic()
        self.record(request.path, body, request.remote)
        device = self.device_for(body)
        sample = device.get("bm_stat_received") if device else None
        control = self.options.get("control_enabled") is True
        writing = self.options.get("recipe_write_enabled") is True
        message = self.split_message(body) if control or writing else None
        poll = request.method == "POST" and request.path == "/braumeister/connect" and message and message[0] == "bm_stat"
        command = self.pending_control() if poll and device and control else None
        if command and command["device_id"] != device["device_id"]:
            command = None
        if command and command["result"] == "sent":
            screen, flags, slot, count = self.control_screen(message[1])
            if screen == control_transition(command)[1] and flags in command["target_flags"] and (
                command["target_slot"] is None
                or (command["target_slot"], command["recipe_count"]) == (slot, count)
            ) and (command.get("target_indicator") is None
                   or self.control_indicator(message[1]) == command["target_indicator"]):
                command["result"] = "confirmed"

        status, headers, answer, source = 200, {"Content-Type": "text/plain; charset=UTF-8"}, LOCAL_ANSWER, "local"
        if self.options["forward_to_cloud"]:
            started = time.monotonic()
            try:
                status, headers, answer = await self.forward_to_cloud(request, body)
                source = "cloud"
            except Exception as err:  # cloud down or unreachable: answer locally
                _LOGGER.warning("Cloud forward failed (%s), answering locally", err)
            _LOGGER.debug(
                "%s %s -> %s %s in %.0f ms: %r",
                request.method, request.path, source, status,
                (time.monotonic() - started) * 1000, answer[:200],
            )

        sending = None
        if (command and self.pending_control() is command and command["result"] == "queued"
                and self.options.get("control_enabled") is True
                and device.get("bm_stat_received") == sample
                and time.monotonic() - received < CONTROL_TIMEOUT):
            before, _, key = control_transition(command)
            screen, flags, slot, count = self.control_screen(message[1])
            action = command["action"]
            if action in ACTUATOR_OPTIONS and self.options.get(ACTUATOR_OPTIONS[action]) is not True:
                command["result"] = "state_changed"
            elif action == "resume_program" and not self.program_resume_allowed():
                command["result"] = "state_changed"
            elif (screen, flags) != (before, command["source_flags"]) or (
                command["source_slot"] is not None
                and (command["source_slot"], command["recipe_count"]) != (slot, count)
            ) or (command.get("source_indicator") is not None
                      and self.control_indicator(message[1]) != command["source_indicator"]):
                command["result"] = "state_changed"
            elif status == 200 and answer == LOCAL_ANSWER:
                answer = b"Start\r\n" + key + b"\r\nOK\r\nDone\r\n"
                source = "local_control"
                command["result"] = "sending"
                sending = command
        if poll and device and writing and sending is None:
            step = self.recipe_step(device, message[1], status == 200 and answer == LOCAL_ANSWER)
            if step:
                answer = b"Start\r\n" + step + b"\r\nOK\r\nDone\r\n"
                source = "local_recipe"
        if device:
            device["last_response"] = answer.decode("latin-1", "replace")
            device["last_response_source"] = source
        # Commands from the cloud ($k key press, $rz recipe, $d delete, ...)
        commands = [line for line in answer.decode("latin-1", "replace").splitlines() if line.startswith("$")]
        if commands:
            _LOGGER.info("%s command(s) to %s (HTTP %s): %s", source, request.remote, status, " | ".join(commands))

        response = web.StreamResponse(status=status, headers=headers)
        response.enable_chunked_encoding()  # the real server answers chunked
        response.force_close()
        try:
            await response.prepare(request)
            await response.write(answer)
            await response.write_eof()
        except BaseException:
            if sending:
                sending["result"] = "unconfirmed"
            raise
        if sending:
            sending.update(result="sent", deadline=time.monotonic() + CONTROL_TIMEOUT)
        if self.options.get("diagnostics_enabled"):
            self.record_diagnostic(body, commands, status, source)
        return response

    def record_diagnostic(self, body: bytes, commands: list[str], status: int, source: str) -> None:
        if self.diagnostic_write is not None and not self.diagnostic_write.done():
            self.diagnostic_missed += 1
            return
        entry = {
            "time": time.time(), "status": status, "source": source,
            "keys": [int(command[-1]) for command in commands[:8] if re.fullmatch(r"\$k=[1-4]", command)],
            "command_count": len(commands),
        }
        message = self.split_message(body)
        if message and message[0] == "bm_stat":
            parts = message[1].split(";", 4)
            fields = parts[3].split("X", 15) if len(parts) >= 4 else []
            if len(fields) >= 15 and re.fullmatch(r"[0-9]{1,4}", fields[3]):
                entry["state"] = int(fields[3])
                if re.fullmatch(r"[pPq][hHi]", fields[14]):
                    entry["actuators"] = fields[14]
        self.diagnostic_write = asyncio.create_task(self.write_diagnostic(entry))

    async def write_diagnostic(self, entry: dict[str, Any]) -> None:
        line = (json.dumps(entry) + "\n").encode("ascii")
        if not await asyncio.to_thread(append_diagnostic, DIAGNOSTICS_FILE, line):
            self.diagnostic_missed += 1

    async def forward_to_cloud(self, request: web.Request, body: bytes) -> tuple[int, dict[str, str], bytes]:
        # Guarded cloud resolution blocks rewrites back to this bridge.
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        base = self.options["cloud_url"] or f"http://{self.options['cloud_host']}"
        url = base.rstrip("/") + request.path_qs
        headers["Host"] = self.options["cloud_host"]
        # The device cannot decode compressed answers and never asks for them, but
        # aiohttp would add "Accept-Encoding: gzip" on its own. Ask for plain text.
        headers["Accept-Encoding"] = "identity"
        async with (self.cloud_session or self.session).request(
            request.method, url, data=body, headers=headers, allow_redirects=False
        ) as resp:
            answer = await resp.read()
            encoding = resp.headers.get("Content-Encoding", "").strip().lower()
            if encoding in ("gzip", "x-gzip"):
                answer = gzip.decompress(answer)  # compressed anyway: unpack for the device
            elif encoding == "deflate":
                try:
                    answer = zlib.decompress(answer)
                except zlib.error:
                    answer = zlib.decompress(answer, -zlib.MAX_WBITS)
            elif encoding not in ("", "identity"):
                raise ValueError("Unsupported cloud content encoding")
            out = {"Content-Type": resp.headers.get("Content-Type", "text/plain; charset=UTF-8")}
            return resp.status, out, answer

    async def passthrough(self, request: web.Request) -> web.StreamResponse:
        url = self.options["passthrough_url"].rstrip("/") + request.path_qs
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["Host"] = request.headers.get("Host", "")
        if not any(k.lower() == "accept-encoding" for k in headers):
            headers["Accept-Encoding"] = "identity"  # don't let aiohttp add gzip on its own
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
        changed = device.get(kind) != payload
        device[kind] = payload
        device[f"{kind}_received"] = time.time()
        device["remote"] = remote
        _LOGGER.debug("%s from %s (%s)", kind, device_id, remote)
        if kind == "bm_stat" and len(parts) > 3:
            self.log_state_change(device, parts[3])
            # Keep the last message with an alarm indicator (field 15). A hop-addition
            # alarm confirmed within seconds would otherwise fall between two polls.
            fields = parts[3].split("X")
            if len(fields) > 15 and fields[15][1:2] not in ("", "0"):
                device["alarm_bm_stat"] = payload
                device["alarm_bm_stat_received"] = device["bm_stat_received"]
        # The recipe list changes only on a sync; the rest of the message (timestamp, signature) every time
        if kind == "rz" and changed and self._recipes_part(payload) != self._recipes_part(device.get("rz_saved", "")):
            device["rz_saved"] = payload
            self.save_recipes()
            _LOGGER.info("Recipe list of %s changed, saved", device_id)

    @staticmethod
    def _recipes_part(payload: str) -> str:
        """The recipe lines of an rz payload, without header, timestamp and signature."""
        lines = payload.replace("\r\n", "\n").split("\n")[1:]
        return "\n".join(line.split(";")[0] for line in lines)

    @staticmethod
    def log_state_change(device: dict[str, Any], status: str) -> None:
        """Log every change of state code, actuator flags or alarm indicator (fields 3, 14, 15).

        The device sends about once per second; this keeps short events such as a
        hop-addition beep visible in the log even though the integration polls less often.
        """
        fields = status.split("X")
        if len(fields) < 16:
            return
        key = (fields[0], fields[2], fields[3], fields[14], fields[15])
        if device.get("last_state") != key:
            _LOGGER.info(
                "state %s flags %s indicator %s (temp %s%s, target %s, step %s/%s s, rest %s, hop %s, language %s)",
                fields[3], fields[14], fields[15], fields[5].strip(), fields[2], fields[4], fields[7], fields[6],
                fields[10], fields[11], fields[0],
            )
            device["last_state"] = key

    # -- local API ----------------------------------------------------------

    def program_resume_allowed(self):
        return (self.options.get("program_control_enabled") is True
                and self.options.get("allow_remote_heating") is True)

    @staticmethod
    def control_indicator(payload):
        parts = payload.split(";", 4)
        fields = parts[3].split("X") if len(parts) >= 4 else []
        return fields[15] if len(fields) >= 16 else ""

    @staticmethod
    def control_screen(payload: str) -> tuple[str, str, str, str]:
        parts = payload.split(";", 4)
        fields = parts[3].split("X", 15) if len(parts) >= 4 else []
        return (fields[3], fields[14], fields[9], fields[8]) if len(fields) >= 15 else ("", "", "", "")

    async def api_control(self, request: web.Request) -> web.Response:
        if self.options.get("control_enabled") is not True:
            raise web.HTTPForbidden(text="Local control is disabled")
        if request.remote not in ("127.0.0.1", "::1") or "Origin" in request.headers:
            raise web.HTTPForbidden(text="Local API clients only")
        if request.method == "GET":
            command = self.pending_control()
            return web.json_response({
                key: command[key] for key in ("device_id", "action", "result")
            } if command else {})
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType()
        try:
            data = json.loads(await request.content.readexactly(request.content_length)) if (
                request.content_length is not None and 0 < request.content_length <= 1024
            ) else None
        except (ValueError, asyncio.IncompleteReadError):
            raise web.HTTPBadRequest(text="Invalid JSON") from None
        if not isinstance(data, dict) or set(data) != {"device_id", "action"}:
            raise web.HTTPBadRequest(text="Expected device_id and action")
        device_id, action = data["device_id"], data["action"]
        if not isinstance(device_id, str) or not isinstance(action, str):
            raise web.HTTPBadRequest(text="Expected string fields")
        device = self.devices.get(device_id, {})
        age = time.time() - device.get("bm_stat_received", 0)
        if not 0 <= age < CONTROL_TIMEOUT:
            raise web.HTTPConflict(text="Fresh device status required")
        screen, flags, slot, count = self.control_screen(device.get("bm_stat", ""))
        if action not in LOCAL_ACTIONS and action not in PROGRAM_KEYS:
            raise web.HTTPBadRequest(text="Unsupported action")
        if action in ACTUATOR_OPTIONS and self.options.get(ACTUATOR_OPTIONS[action]) is not True:
            raise web.HTTPForbidden(text="Manual actuator control is disabled")
        source_indicator = target_indicator = target_screen = None
        if action in PROGRAM_KEYS:
            if action == "resume_program" and not self.program_resume_allowed():
                raise web.HTTPForbidden(text="Program resume requires program_control_enabled and allow_remote_heating")
            source_indicator = self.control_indicator(device.get("bm_stat", ""))
            transition = program_transition(action, screen, flags, source_indicator)
            if transition is None:
                raise web.HTTPConflict(text="Device screen, actuator state or pause indicator does not match")
            target_screen, target_flags, target_indicator = transition
        else:
            target_flags = ACTUATOR_FLAGS.get(action, {"ph": ("ph",)}).get(flags)
            if screen != LOCAL_ACTIONS[action][0] or target_flags is None:
                raise web.HTTPConflict(text="Device screen or actuator state does not match")
            if action == "select_recipe":
                source_indicator = target_indicator = "000"
                if self.control_indicator(device.get("bm_stat", "")) != source_indicator:
                    raise web.HTTPConflict(text="Recipe selection must not be interrupted")
        source_slot = target_slot = None
        if action in RECIPE_MOVES or action == "select_recipe":
            if (
                # The device holds up to nine recipes (field 8 counts them)
                count not in ("1", "2", "3", "4", "5", "6", "7", "8", "9")
                or slot not in ("0", "1", "2", "3", "4", "5", "6", "7", "8")
                or int(slot) >= int(count)
            ):
                raise web.HTTPConflict(text="A valid recipe count and current slot are required")
            source_slot = slot
            if action in RECIPE_MOVES:
                target_slot = str((int(slot) + RECIPE_MOVES[action]) % int(count))
        command = self.pending_control()
        if command and command["result"] in ("queued", "sending", "sent"):
            raise web.HTTPConflict(text="A local command is already pending")
        job = self.pending_recipe_job()
        if job and job["result"] in ("queued", "sending"):
            raise web.HTTPConflict(text="A recipe upload is in progress")
        now = time.monotonic()
        self.local_command = {
            "device_id": device_id, "action": action, "result": "queued",
            "source_slot": source_slot, "target_slot": target_slot,
            "recipe_count": count,
            "source_flags": flags, "target_flags": target_flags,
            "source_screen": screen, "target_screen": target_screen,
            "source_indicator": source_indicator, "target_indicator": target_indicator,
            "deadline": now + CONTROL_TIMEOUT,
        }
        return web.json_response({"result": "queued"}, status=202)

    async def api_recipes(self, request: web.Request) -> web.Response:
        """Replace all recipes on a device (GET: outcome of the last upload)."""
        if self.options.get("recipe_write_enabled") is not True:
            raise web.HTTPForbidden(text="Recipe upload is disabled")
        if request.remote not in ("127.0.0.1", "::1") or "Origin" in request.headers:
            raise web.HTTPForbidden(text="Local API clients only")
        if request.method == "GET":
            job = self.pending_recipe_job()
            return web.json_response({
                "device_id": job["device_id"], "result": job["result"],
                "recipes": len(job["steps"]) - 1, "written": max(job["step"] - 1, 0),
            } if job else {})
        if request.content_type != "application/json":
            raise web.HTTPUnsupportedMediaType()
        try:
            data = json.loads(await request.content.readexactly(request.content_length)) if (
                request.content_length is not None and 0 < request.content_length <= 8192
            ) else None
        except (ValueError, asyncio.IncompleteReadError):
            raise web.HTTPBadRequest(text="Invalid JSON") from None
        if not isinstance(data, dict) or set(data) != {"device_id", "recipes"}:
            raise web.HTTPBadRequest(text="Expected device_id and recipes")
        device_id, recipes = data["device_id"], data["recipes"]
        if not isinstance(device_id, str) or not isinstance(recipes, list) or not 1 <= len(recipes) <= RECIPE_SLOTS:
            raise web.HTTPBadRequest(text=f"Expected a device_id and 1 to {RECIPE_SLOTS} recipes")
        device = next((d for d in self.devices.values() if d["device_id"].lower() == device_id.lower()), {})
        device_id = device.get("device_id", device_id)
        age = time.time() - device.get("bm_stat_received", 0)
        if not 0 <= age < CONTROL_TIMEOUT:
            raise web.HTTPConflict(text="Fresh device status required")
        payload = device.get("bm_stat", "")
        parts = payload.split(";", 4)
        fields = parts[3].split("X") if len(parts) >= 4 else []
        if len(fields) < 16 or fields[2] not in ("C", "F"):
            raise web.HTTPConflict(text="Device status not readable")
        try:
            lines = [recipe_line(slot, recipe, fields[2] == "F") for slot, recipe in enumerate(recipes)]
        except ValueError as err:
            raise web.HTTPBadRequest(text=f"Recipe {err}") from None
        if self.control_screen(payload)[:2] != ("101", "ph"):
            raise web.HTTPConflict(text="The device must show the main menu with pump and heater off")
        command = self.pending_control()
        job = self.pending_recipe_job()
        if (command and command["result"] in ("queued", "sending", "sent")) or (
                job and job["result"] in ("queued", "sending")):
            raise web.HTTPConflict(text="A local command or recipe upload is already pending")
        steps = [b"$d=A"] + [b"$rz=" + line.encode("ascii") for line in lines]
        self.recipe_job = {
            "device_id": device_id, "result": "queued", "steps": steps,
            "counts": list(range(len(steps))), "step": 0, "sent_at": None, "attempts": 0,
            "deadline": time.monotonic() + 30 + 10 * len(steps),
        }
        _LOGGER.info("Recipe upload to %s queued (%d recipes)", device_id, len(lines))
        return web.json_response({"result": "queued"}, status=202)

    async def api_status(self, request: web.Request) -> web.Response:
        device_id = request.query.get("device")
        devices = list(self.devices.values())
        if device_id:
            devices = [d for d in devices if d["device_id"].lower() == device_id.lower()]
        return web.json_response({"now": time.time(), "devices": devices})

    async def api_health(self, _request: web.Request) -> web.Response:
        health = {"ok": True, "devices": len(self.devices)}
        if self.options.get("diagnostics_enabled"):
            health["diagnostics_missed"] = self.diagnostic_missed
        return web.json_response(health)


def build_apps(bridge: Bridge) -> tuple[web.Application, web.Application]:
    """The port-80 app and the local status API app."""
    port80 = web.Application()
    port80.router.add_route("*", "/{tail:.*}", bridge.handle_port80)
    api = web.Application()
    api.router.add_get("/api/status", bridge.api_status)
    api.router.add_get("/api/health", bridge.api_health)
    api.router.add_get("/api/control", bridge.api_control)
    api.router.add_post("/api/control", bridge.api_control)
    api.router.add_get("/api/recipes", bridge.api_recipes)
    api.router.add_post("/api/recipes", bridge.api_recipes)
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
