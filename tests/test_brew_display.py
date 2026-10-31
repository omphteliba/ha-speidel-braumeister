"""Captured portal screen ranges and overrides, without live device commands."""
import importlib
import pytest
from test_adaptive_polling import PACKAGE

brew_display = importlib.import_module(f'{PACKAGE}.brew_display').brew_display


def fields(code, flags='000', pump='ph', rest='0', hop='0'):
    return ['0', '12:00', 'C', str(code), '600', '22.0', '1200', '30', '4', '0', rest, hop, '0', 'EMSR', pump, flags]


@pytest.mark.parametrize('code,text', [
    (101,'Hauptmenü'), (2000,'Rezept auswählen'), (2020,'Rezept auswählen'),
    (2030,'Wasser eingefüllt?'), (2199,'Wasser eingefüllt?'),
    (2200,'Pumpe wird entlüftet'), (2399,'Pumpe wird entlüftet'),
    (2400,'Aufheizen'), (2499,'Aufheizen'), (2500,'Statuscode 2500'),
    (2510,'Einmaischtemperatur erreicht'), (2610,'Malz einfüllen!'),
    (2704,'Malz einfüllen!'), (2705,'Malz eingefüllt?'),
    (2810,'1. Rast'), (2820,'1. Rast'), (2910,'Rastende erreicht'),
    (2930,'Malzrohr entnehmen!'), (2960,'Start Hopfenkochen?'),
    (3010,'Aufheizen zum Kochen'), (3070,'Hopfen kochen'),
    (3080,'Hopfen zugeben – 1. Hopfengabe'), (3449,'Hopfen zugeben – 1. Hopfengabe'),
    (3450,'Brauvorgang beendet'), (3500,'Brauvorgang beendet'),
    (3501,'Jetzt Whirlpool …'), (3600,'Jetzt Whirlpool …'), (3601,'Prost!'),
    (4006,'Manueller Betrieb'), (4007,'Manueller Betrieb'), (8101,'Einstellungen'),
    (5000,'Statuscode 5000'),
])
def test_portal_ranges(code, text):
    assert brew_display(fields(code))['current_step'] == text


@pytest.mark.parametrize('flags,text', [('100','Automatik angehalten'), ('200','Temperaturfehler'), ('0D0','Bitte Deckel entfernen.'), ('2D0','Bitte Deckel entfernen.')])
def test_interrupt_overrides_hop_dialog(flags, text):
    result = brew_display(fields(3080, flags=flags))
    assert result['current_step'] == text
    assert result['display_phase'] == 'Hopfen kochen'


def test_pump_pause_and_one_based_indices():
    assert brew_display(fields(2510, pump='qh'))['current_step'] == 'Pumpenabschaltung'
    assert brew_display(fields(2820, pump='qh'))['current_step'] == 'Pumpenpause'
    assert brew_display(fields(2820, rest='2'))['current_step'] == '3. Rast'
    assert brew_display(fields(3080, hop='2'))['current_step'] == 'Hopfen zugeben – 3. Hopfengabe'
    assert brew_display(fields(2820, rest='99'))['current_step'] == 'Rast'


def test_truncated_and_invalid_state_do_not_invent_screen():
    assert brew_display([])['current_step'] == 'Status unbekannt'
    assert brew_display(fields('bad'))['display_state_code'] is None


def test_rest_timers_and_original_flags():
    data = brew_display(fields(2820, pump='qi'))
    assert data['display_time_target_seconds'] == 1200
    assert data['display_time_elapsed_seconds'] == 30
    assert data['display_pump_flag'] == 'q'
    assert data['display_heater_flag'] == 'i'
    assert data['display_clock'] == '12:00'
    assert brew_display(fields(2030))['display_time_elapsed_seconds'] is None


def test_invalid_display_values():
    raw = fields(2820, pump='??')
    raw[1], raw[6], raw[7] = '25:99', '-1', 'invalid'
    data = brew_display(raw)
    for key in ('display_clock', 'display_pump_flag', 'display_heater_flag',
                'display_time_target_seconds', 'display_time_elapsed_seconds'):
        assert data[key] is None


def test_sensor_step_is_text_and_metadata_is_attributes():
    # Compile only the entity class with minimal bases; no HA runtime required.
    import ast
    from pathlib import Path
    source = Path(__file__).parents[1] / 'custom_components/speidel_braumeister/sensor.py'
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    cls.bases = []
    namespace = {'Any': object, 'SpeidelBraumeisterDataCoordinator': object,
                 'SensorEntityDescription': object}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), 'exec'), namespace)
    sensor = object.__new__(namespace[cls.name])
    from types import SimpleNamespace
    sensor.coordinator = SimpleNamespace(data=brew_display(fields(2820, pump='Pi')))
    sensor.entity_description = SimpleNamespace(key='current_step')
    assert sensor.native_value == '1. Rast'
    assert sensor.extra_state_attributes['display_heater_flag'] == 'i'
    assert sensor.extra_state_attributes['display_time_elapsed_seconds'] == 30
