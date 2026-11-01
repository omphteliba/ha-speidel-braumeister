"""Issue #5: device alarms must reach the entity and clear on acknowledgement."""
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
@pytest.mark.parametrize(('code', 'indicator', 'alarm'), [
    (2510, '010', 'mash_in_temperature_reached'),
    (2910, '010', 'rest_end_reached'),
    (3010, '0D0', 'remove_lid'),
    (3080, '010', 'hop_addition'),
    (3450, '010', 'brew_finished'),
    (3070, '020', 'alarm'),
])
async def test_alarm_pipeline_and_acknowledgement(source, code, indicator, alarm):
    module = entity_module('binary_sensor')
    obj = SimpleNamespace(data=await through_coordinator(payload(code, indicator), source))
    entity = module.SpeidelBraumeisterBinarySensor(obj, SimpleNamespace(key='alarm'))
    assert entity.is_on is True
    assert entity.extra_state_attributes == {'alarm_type': alarm, 'state_code': code}
    obj.data = await through_coordinator(payload(code, '000'), source)
    obj.data['current_phase'] = 'Rastende erreicht'  # stale portal text must not re-arm
    assert entity.is_on is False
    assert entity.extra_state_attributes['alarm_type'] is None


@pytest.mark.parametrize(('data', 'expected'), [
    ({'alarm': 'remove_lid'}, True),
    ({'alarm': 'hop_addition', 'state_code': None}, True),
    ({'alarm': None, 'current_phase': 'Rastende erreicht'}, False),
    ({'current_phase': 'Rastende erreicht'}, True),
    ({'current_phase': 'Hauptmenü'}, False),
])
def test_decoded_alarm_precedes_legacy_phase_fallback(data, expected):
    module = entity_module('binary_sensor')
    entity = module.SpeidelBraumeisterBinarySensor(SimpleNamespace(data=data), SimpleNamespace(key='alarm'))
    assert entity.is_on is expected
