"""Issue #6: elapsed rest/boil time, not RTC or total brew runtime."""
import importlib
import sys
import types
from enum import StrEnum
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from conftest import ROOT, device_protocol
from test_brew_display import load_coordinator


def entity_module(platform):
    class EntityCategory(StrEnum):
        DIAGNOSTIC = "diagnostic"
    def mod(name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        return module
    class Entity:
        def __init__(self, coordinator, key):
            self.coordinator = coordinator
    package = mod('issue_entities')
    package.__path__ = [str(ROOT / 'custom_components' / 'speidel_braumeister')]
    stubs = {
        'issue_entities': package,
        'issue_entities.coordinator': mod('coordinator', SpeidelBraumeisterDataCoordinator=object),
        'issue_entities.entity': mod('entity', SpeidelBraumeisterEntity=Entity),
        'homeassistant.config_entries': mod('config', ConfigEntry=object),
        'homeassistant.core': mod('core', HomeAssistant=object),
        'homeassistant.helpers.entity': mod('entity', EntityCategory=EntityCategory),
        'homeassistant.helpers.entity_platform': mod('platform', AddEntitiesCallback=object),
        'homeassistant.components.sensor': mod('sensor', SensorEntity=type('Sensor', (), {}), SensorEntityDescription=SimpleNamespace),
        'homeassistant.components.binary_sensor': mod('binary', BinarySensorEntity=type('Binary', (), {}), BinarySensorEntityDescription=SimpleNamespace),
    }
    # Isolate descriptions when this helper is also used in a combined patch test.
    for name in list(sys.modules):
        if name.startswith('issue_entities.'):
            del sys.modules[name]
    with patch.dict(sys.modules, stubs):
        return importlib.import_module('issue_entities.' + platform)


def payload(code, indicator='000', elapsed='120', duration='1200'):
    return f'FW;TEST;1000;0X10:00XCX{code}X1030X99.5X{duration}X{elapsed}X1X0X1X0X10XA00SXqHX{indicator}X0X0X0;0;0'


async def through_coordinator(raw, source):
    module = load_coordinator('protocol_tests', None)
    obj = module.SpeidelBraumeisterDataCoordinator(None, None, 'TEST')
    obj.hass = SimpleNamespace(config=SimpleNamespace(time_zone='Europe/Berlin'))
    auth = importlib.import_module('protocol_tests.web_auth').SpeidelWebAuth('', '')
    parsed = auth._parse_xhr_response(raw)
    bridge = device_protocol.from_bridge({'now': 100, 'devices': [
        {'device_id': 'TEST', 'bm_stat': raw, 'bm_stat_received': 100}
    ]}, 'TEST', 10)
    obj._fetch_bridge = AsyncMock(return_value=bridge if source == 'bridge' else None)
    obj._add_web_texts = AsyncMock()
    obj.web_auth = SimpleNamespace(get_device_status=AsyncMock(return_value=parsed))
    return await obj._async_update_data()


@pytest.mark.parametrize('source', ['xhr', 'bridge'])
@pytest.mark.parametrize('code', [2820, 3070, 3080])
async def test_device_timer_reaches_sensor(source, code):
    module = entity_module('sensor')
    description = next(d for d in module.SENSOR_TYPES if d.key == 'elapsed_time')
    assert description.native_unit_of_measurement == 's'
    assert description.device_class == 'duration'
    assert not hasattr(description, 'state_class')
    obj = SimpleNamespace(data=await through_coordinator(payload(code, elapsed='125'), source))
    entity = module.SpeidelBraumeisterSensor(obj, description)
    assert entity.native_value == 125
    obj.data = await through_coordinator(payload(101), source)
    assert entity.native_value is None


@pytest.mark.parametrize('code', [101, 2030, 2410, 2810, 2910, 3010, 3450, 4006, 9999])
def test_no_timer_outside_verified_timed_states(code):
    assert device_protocol.parse_bm_stat(payload(code))['elapsed_time'] is None


@pytest.mark.parametrize('elapsed', ['-1', '', '?', '1.5', '+1', '1e2', '１２'])
def test_invalid_device_timer_is_unknown(elapsed):
    result = device_protocol.parse_bm_stat(payload(2820, elapsed=elapsed))
    assert result['state_seconds'] is None
    assert result['elapsed_time'] is None
    assert result['remaining_seconds'] is None


def test_zero_overrun_and_phase_reset():
    for elapsed in (0, 125, 1250):
        assert device_protocol.parse_bm_stat(payload(3070, elapsed=str(elapsed)))['elapsed_time'] == elapsed
    assert device_protocol.parse_bm_stat(payload(2820, elapsed='0'))['elapsed_time'] == 0


async def test_hop_alarm_keeps_device_boil_timer():
    for code, elapsed, indicator in [(3070, 120, '000'), (3080, 130, '010'), (3070, 140, '000')]:
        result = await through_coordinator(payload(code, indicator, str(elapsed)), 'xhr')
        assert result['elapsed_time'] == elapsed
        assert result['alarm'] == ('hop_addition' if code == 3080 else None)


def test_offline_and_mqtt_clear_old_phase_timer():
    module = load_coordinator('protocol_tests', None)
    obj = module.SpeidelBraumeisterDataCoordinator(None, None, 'TEST')
    assert obj._get_offline_result()['elapsed_time'] is None
    obj.data = {'elapsed_time': 120, 'connection_status': 'online'}
    obj.async_set_updated_data = lambda data: setattr(obj, 'data', data)
    obj.update_from_mqtt({'temperature': 20})
    assert obj.data['elapsed_time'] is None
