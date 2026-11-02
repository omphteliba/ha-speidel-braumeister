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
        "homeassistant.helpers.aiohttp_client": mod("aiohttp", async_get_clientsession=lambda hass: None),
        "homeassistant.helpers.update_coordinator": mod("coordinator", DataUpdateCoordinator=Base, UpdateFailed=RuntimeError),
        f"{package}.const": mod("const", BRIDGE_MAX_AGE=10, BRIDGE_STATUS_URL="http://localhost", DEFAULT_SCAN_INTERVAL=30),
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
