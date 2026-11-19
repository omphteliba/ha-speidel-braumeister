"""Display context reaches the actual current-step sensor without changing status."""
from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorEntityDescription

from custom_components.speidel_braumeister.brew_display import brew_display
from custom_components.speidel_braumeister.sensor import SpeidelBraumeisterSensor


@pytest.mark.parametrize(('code', 'flags'), [(3010, '0D0'), (3010, '120'), (2120, '000')])
def test_current_step_exposes_display_context(code, flags):
    fields = ['0', '17:42', 'C', str(code), '960', '94.5', '600', '23',
              '1', '0', '0', '0', '100', 'A00S', 'qH', flags, '0', '3599']
    data = brew_display(fields)
    data.update(remaining_seconds=577, start_delay_seconds=3599, heating='on', pump='off')
    coordinator = MagicMock(data=data, machine_uuid='TEST')
    sensor = SpeidelBraumeisterSensor(coordinator, SensorEntityDescription(key='current_step'))
    assert sensor.native_value == data['current_step']
    keys = {'display_clock', 'display_pump_flag', 'display_heater_flag',
            'display_time_target_seconds', 'display_time_elapsed_seconds',
            'display_button_labels', 'display_editor_flags', 'display_start_delay_seconds'}
    assert keys <= sensor.extra_state_attributes.keys()
    assert all(sensor.extra_state_attributes[key] == data[key] for key in keys)
    status = SpeidelBraumeisterSensor(coordinator, SensorEntityDescription(key='process_status'))
    assert status.extra_state_attributes == {
        'remaining_seconds': 577, 'start_delay_seconds': 3599, 'heating': 'on', 'pump': 'off',
    }
    coordinator.data = {}
    assert sensor.extra_state_attributes is None
