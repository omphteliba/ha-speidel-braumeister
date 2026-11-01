"""Cloud DNS isolation and uncompressed command delivery; no external traffic."""
import socket
import zlib
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from test_bridge import BM_STAT, DEVICE_HEADERS, make_bridge


@pytest.mark.parametrize("address", ["127.0.0.1", "192.168.1.2", "10.0.0.1", "::1", "169.254.1.2"])
async def test_rewritten_cloud_address_rejected(bridge_module, address):
    resolver = bridge_module.PublicCloudResolver.__new__(bridge_module.PublicCloudResolver)
    resolver.delegate = AsyncMock()
    resolver.delegate.resolve.return_value = [{"host": address}]
    with pytest.raises(OSError, match="non-public"):
        await resolver.resolve("api2.myspeidel.com")


@pytest.mark.parametrize("dns_port", [0, 53])
async def test_cloud_resolver_independent_of_inbound_dns(bridge_module, monkeypatch, dns_port):
    delegate = AsyncMock()
    delegate.resolve.return_value = [{"host": "1.1.1.1"}]
    seen = []
    def resolver_factory(**kwargs):
        seen.append(kwargs)
        return delegate
    monkeypatch.setattr(bridge_module, "AsyncResolver", resolver_factory)
    obj = bridge_module.Bridge({**bridge_module.DEFAULTS, "dns_port": dns_port, "state_file": "", "cloud_dns": ["1.1.1.1", "1.0.0.1"]})
    await obj.start_session()
    try:
        assert bridge_module.DEFAULTS["dns_port"] == 53
        assert obj.session is not obj.cloud_session
        assert seen == [{"nameservers": ["1.1.1.1", "1.0.0.1"]}]
        assert await obj.cloud_resolver.resolve("api2.myspeidel.com", 80) == [{"host": "1.1.1.1"}]
        delegate.resolve.assert_awaited_once_with("api2.myspeidel.com", 80, socket.AF_INET)
    finally:
        await obj.close_session()
    delegate.close.assert_awaited_once()


@pytest.mark.parametrize("raw", [False, True])
async def test_deflate_command_reaches_device(bridge_module, raw):
    answer = b"Start\r\n$k=4\r\nOK\r\nDone\r\n"
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS if raw else zlib.MAX_WBITS)
    compressed = compressor.compress(answer) + compressor.flush()
    async def handler(request):
        assert await request.read() == BM_STAT
        assert request.headers["Accept-Encoding"] == "identity"
        return web.Response(body=compressed, headers={"Content-Encoding": "deflate"})
    app = web.Application()
    app.router.add_post("/braumeister/connect", handler)
    cloud = TestServer(app)
    await cloud.start_server()
    bridge, port80, api = await make_bridge(bridge_module, str(cloud.make_url("")))
    try:
        response = await port80.post("/braumeister/connect", data=BM_STAT, headers=DEVICE_HEADERS)
        assert await response.read() == answer
        assert "Content-Encoding" not in response.headers
    finally:
        await port80.close()
        await api.close()
        await cloud.close()
        await bridge.close_session()


@pytest.mark.parametrize("dns_port", [0, 53])
@pytest.mark.parametrize("address", ["1.1.1.1", "192.168.1.2"])
async def test_default_host_resolver_keeps_loop_protection(bridge_module, monkeypatch, dns_port, address):
    delegate = AsyncMock()
    delegate.resolve.return_value = [{"host": address}]
    host_factory = Mock(return_value=delegate)
    explicit_factory = Mock(side_effect=AssertionError("No explicit DNS requested"))
    monkeypatch.setattr(bridge_module, "DefaultResolver", host_factory)
    monkeypatch.setattr(bridge_module, "AsyncResolver", explicit_factory)
    assert bridge_module.DEFAULTS["cloud_dns"] == []
    obj = bridge_module.Bridge({**bridge_module.DEFAULTS, "dns_port": dns_port, "state_file": ""})
    await obj.start_session()
    try:
        host_factory.assert_called_once_with()
        explicit_factory.assert_not_called()
        if address == "192.168.1.2":
            with pytest.raises(OSError, match="cloud_dns"):
                await obj.cloud_resolver.resolve("api2.myspeidel.com", 80)
        else:
            assert await obj.cloud_resolver.resolve("api2.myspeidel.com", 80) == [{"host": address}]
        delegate.resolve.assert_awaited_once_with("api2.myspeidel.com", 80, socket.AF_INET)
    finally:
        await obj.close_session()
    delegate.close.assert_awaited_once()
