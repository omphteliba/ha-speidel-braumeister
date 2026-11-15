"""Cloud clients must never be used by the local coordinator."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_brew_display import load_coordinator


@pytest.mark.parametrize('bridge', [None, {'temperature': 42, 'state_code': 2410, 'current_step': 'Heating'}])
async def test_local_mode_never_uses_cloud_even_when_bridge_is_missing(bridge):
    module = load_coordinator('protocol_tests', None)
    fail = AsyncMock(side_effect=AssertionError('Cloud request in local mode'))
    api = SimpleNamespace(get_latest_data=fail, get_timeseries=fail)
    obj = module.SpeidelBraumeisterDataCoordinator(None, api, 'TEST', 30, local_only=True)
    obj.web_auth = SimpleNamespace(get_device_info=fail, get_device_status=fail)
    obj._fetch_bridge = AsyncMock(return_value=bridge)
    obj._mqtt_data = {'temperature': 999}
    result = await obj._fetch_data()
    assert obj.update_interval == timedelta(seconds=5)
    assert result['data_source'] == 'bridge'
    assert result['connection_status'] == ('online' if bridge else 'offline')
    if bridge:
        assert result['temperature'] == 42
    else:
        assert result['temperature'] is None
    fail.assert_not_awaited()
