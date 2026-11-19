"""Local screen messages without changing upstream recipe/alarm semantics."""
import importlib

import pytest

from conftest import device_protocol

brew_display = importlib.import_module('protocol_tests.brew_display').brew_display


def fields(code, pump='P', indicator='000', rest='1', hop='0'):
    return ['0', '17:42', 'C', str(code), '720', '72.5', '2700', '120', '1', '0',
            rest, hop, '100', 'A00S', pump + 'i', indicator]


@pytest.mark.parametrize(('code', 'expected'), [
    (101, 'Hauptmenü'), (2030, 'Wasser eingefüllt?'), (2300, 'Pumpe wird entlüftet'),
    (2410, 'Aufheizen'), (2510, 'Einmaischtemperatur erreicht'),
    (2610, 'Malz einfüllen!'), (2705, 'Malz eingefüllt?'), (2820, '2. Rast'),
    (2910, 'Rastende erreicht'), (2930, 'Malzrohr entnehmen!'),
    (2960, 'Start Hopfenkochen?'), (3010, 'Aufheizen zum Kochen'),
    (3070, 'Hopfen kochen'), (3080, 'Hopfen zugeben – 1. Hopfengabe'),
    (3450, 'Brauvorgang beendet'), (4006, 'Manueller Betrieb'),
    (2500, 'Statuscode 2500'), (7000, 'Statuscode 7000'),
])
def test_screen_messages(code, expected):
    assert brew_display(fields(code))['current_step'] == expected


@pytest.mark.parametrize(('code', 'pump', 'indicator', 'expected'), [
    (2820, 'q', '000', 'Pumpenpause'), (2510, 'q', '000', 'Pumpenabschaltung'),
    (2820, 'P', '100', 'Automatik angehalten'),
    (2820, 'P', '200', 'Temperaturfehler'),
    (2820, 'P', '2D0', 'Bitte Deckel entfernen.'),
    (3010, 'q', '0D0', 'Bitte Deckel entfernen.'),
    (3010, 'q', '000', 'Aufheizen zum Kochen'),
])
def test_screen_overrides(code, pump, indicator, expected):
    assert brew_display(fields(code, pump, indicator))['current_step'] == expected


def test_missing_fields_and_unknown_code():
    result = brew_display([])
    assert result['current_step'] == 'Status unbekannt'
    assert result['display_state_code'] is None
    assert brew_display(fields(2820, rest='?'))['current_step'] == 'Rast'


def test_bridge_keeps_hop_alarm_recipes_and_timing():
    payload = 'FW;TEST;1;' + 'X'.join(fields(3080, indicator='010')) + ';0;0'
    recipe = '0X60X63X20X72X45X78X10X0X0X0X0X60X100X60X15X0X0X0X0.Test Ale'
    state = {'now': 100, 'devices': [{'device_id': 'TEST', 'bm_stat': payload,
             'bm_stat_received': 100, 'rz': recipe}]}
    result = device_protocol.from_bridge(state, 'TEST', 10)
    assert result['alarm'] == 'hop_addition'
    assert result['current_step'] == 'Hopfen zugeben – 1. Hopfengabe'
    assert result['pump'] == 'on' and result['heating'] == 'off'
    assert result['display_clock'] == '17:42'
    assert result['display_pump_flag'] == 'P'
    assert result['display_heater_flag'] == 'i'
    assert result['display_button_labels'] == 'A00S'
    assert result['display_editor_flags'] == '010'
    assert result['display_time_target_seconds'] is None
    assert result['display_time_elapsed_seconds'] is None
    assert result['display_start_delay_seconds'] is None
    assert result['brew_name'] == 'Test Ale'
    assert result['device_recipe_details'][0]['boil_minutes'] == 60
    assert device_protocol.recipes_from_bridge(state, 'TEST')[0]['name'] == 'Test Ale'
    state['now'] = 200
    assert device_protocol.from_bridge(state, 'TEST', 10) is None

def load_coordinator(package, root):
    import importlib
    import sys
    import types
    from datetime import datetime, timezone
    from unittest.mock import patch
    def mod(name, **attrs):
        result = types.ModuleType(name)
        result.__dict__.update(attrs)
        return result
    class Base:
        def __class_getitem__(cls, key):
            return cls
        def __init__(self, *args, update_interval=None, **kwargs):
            self.update_interval = update_interval
            self.hass = None
            self.data = None
    stubs = {
        "homeassistant.util": mod("util", dt=mod("dt", now=lambda: datetime.now(timezone.utc))),
        "homeassistant.core": mod("core", HomeAssistant=object, callback=lambda fn: fn),
        "homeassistant.exceptions": mod("exceptions", ConfigEntryAuthFailed=type("AuthFailed", (Exception,), {})),
        "homeassistant.helpers.aiohttp_client": mod("aiohttp", async_get_clientsession=lambda hass: None),
        "homeassistant.helpers.update_coordinator": mod("coordinator", DataUpdateCoordinator=Base, UpdateFailed=RuntimeError),
        f"{package}.const": mod("const", BRIDGE_MAX_AGE=10, BRIDGE_STATUS_URL="http://localhost", DEFAULT_SCAN_INTERVAL=30, LOCAL_SCAN_INTERVAL=5),
        f"{package}.api": mod("api", SpeidelBraumeisterAPI=object,
            SpeidelAuthError=type("AuthError", (Exception,), {}),
            SpeidelApiError=type("ApiError", (Exception,), {}),
            SpeidelPaymentRequiredError=type("PaymentError", (Exception,), {})),
    }
    with patch.dict(sys.modules, stubs):
        return importlib.import_module(f"{package}.coordinator")

async def test_cloud_metadata_does_not_replace_local_step():
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    coordinator = load_coordinator("protocol_tests", None)
    obj = coordinator.SpeidelBraumeisterDataCoordinator(None, None, "TEST")
    obj.web_auth = SimpleNamespace(get_device_info=AsyncMock(return_value={
        "screen_title": "Test Ale – 1. Rast", "device_name": "Braumeister"}))
    result = {"current_step": "Pumpenpause", "process_status": "running"}
    await obj._add_web_texts(result)
    assert result["current_step"] == "Pumpenpause"
    assert result["brew_name"] == "Test Ale"
    assert result["device_name"] == "Braumeister"


@pytest.mark.parametrize(('clock', 'expected'), [
    ('0:00', '0:00'), ('23:59', '23:59'), ('24:00', None), ('12:60', None),
    ('1:2', None), ('123:00', None), ('１２:３０', None), ('', None),
])
def test_display_clock(clock, expected):
    data = fields(3010)
    data[1] = clock
    assert brew_display(data)['display_clock'] == expected


@pytest.mark.parametrize('actuators', ['PH', 'Pi', 'ph', 'pH', 'qi', 'qH'])
def test_raw_actuator_flags(actuators):
    data = fields(3010)
    data[14] = actuators
    result = brew_display(data)
    assert result['display_pump_flag'] == actuators[0]
    assert result['display_heater_flag'] == actuators[1]


@pytest.mark.parametrize('actuators', ['', 'P', 'PHx', 'QH', 'px'])
def test_invalid_actuator_flags(actuators):
    data = fields(3010)
    data[14] = actuators
    result = brew_display(data)
    assert result['display_pump_flag'] is None
    assert result['display_heater_flag'] is None


@pytest.mark.parametrize('flags', ['0D0', '0DT', '120', '000', '00T', '00Z'])
def test_preserve_editor_context(flags):
    data = fields(3010, indicator=flags)
    data[13] = 'ADUS'
    result = brew_display(data)
    assert result['display_editor_flags'] == flags
    assert result['display_button_labels'] == 'ADUS'


@pytest.mark.parametrize('code', [2810, 2820, 2909, 3010])
def test_display_timer_uses_live_values(code):
    data = fields(code)
    data[6:8] = ['720', '23']
    assert brew_display(data)['display_time_target_seconds'] == 720
    assert brew_display(data)['display_time_elapsed_seconds'] == 23
    data[6:8] = ['180', '0']
    assert brew_display(data)['display_time_target_seconds'] == 180
    assert brew_display(data)['display_time_elapsed_seconds'] == 0
    data[6:8] = ['bad', '-1']
    assert brew_display(data)['display_time_target_seconds'] is None
    assert brew_display(data)['display_time_elapsed_seconds'] is None


@pytest.mark.parametrize('code', [101, 2120, 2910, 2930, 3070, 3080])
def test_other_screens_do_not_reuse_display_timer(code):
    result = brew_display(fields(code))
    assert result['display_time_target_seconds'] is None
    assert result['display_time_elapsed_seconds'] is None


@pytest.mark.parametrize(('value', 'expected'), [
    ('3599', 3599), ('0', 0), ('2147483647', 2147483647),
    ('2147483648', None), ('-1', None), ('1.5', None), ('NaN', None), ('１２', None),
])
def test_display_countdown_requires_exact_context(value, expected):
    data = fields(2120) + ['0', value]
    assert brew_display(data)['display_start_delay_seconds'] == expected
    data[15] = '120'
    assert brew_display(data)['display_start_delay_seconds'] is None
    data[15] = '000'
    data[13] = 'ADUS'
    assert brew_display(data)['display_start_delay_seconds'] is None
    data[13] = 'A00S'
    data[3] = '101'
    assert brew_display(data)['display_start_delay_seconds'] is None


def test_missing_display_context_is_not_fabricated():
    result = brew_display([])
    assert result['display_button_labels'] == ''
    assert result['display_editor_flags'] == ''
    for key in ('display_clock', 'display_pump_flag', 'display_heater_flag',
                'display_time_target_seconds', 'display_time_elapsed_seconds',
                'display_start_delay_seconds'):
        assert result[key] is None
