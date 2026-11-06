"""Sensor lifecycle with HA API stubs: timer, failure visibility, and cleanup."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def sensor_context():
    def module(**values):
        result = ModuleType("stub")
        result.__dict__.update(values)
        return result

    class Entity:
        def __init__(self, coordinator, key):
            self.coordinator = coordinator
            self.hass = object()
            self.removers = []
            self.writes = 0

        async def async_added_to_hass(self):
            pass

        def async_on_remove(self, remove):
            self.removers.append(remove)

        def _handle_coordinator_update(self):
            self.async_write_ha_state()

        def async_write_ha_state(self):
            self.writes += 1

    timers, removed = [], []

    def track(hass, callback, interval):
        timers.append((callback, interval.total_seconds()))
        return lambda: removed.append(True)

    stubs = {
        "homeassistant.config_entries": module(ConfigEntry=object),
        "homeassistant.core": module(HomeAssistant=object, callback=lambda f: f),
        "homeassistant.helpers.entity_platform": module(AddEntitiesCallback=object),
        "homeassistant.helpers.event": module(async_track_time_interval=track),
        "homeassistant.components.binary_sensor": module(BinarySensorEntity=type("Binary", (), {}),
                                                          BinarySensorEntityDescription=object),
        "protocol_tests.const": module(DOMAIN="test", BINARY_SENSOR_TYPES=[]),
        "protocol_tests.coordinator": module(SpeidelBraumeisterDataCoordinator=object),
        "protocol_tests.entity": module(SpeidelBraumeisterEntity=Entity),
    }
    namespace = {"__name__": "protocol_tests.binary_sensor", "__package__": "protocol_tests"}
    path = Path(__file__).parents[1] / "custom_components/speidel_braumeister/binary_sensor.py"
    with patch.dict("sys.modules", stubs):
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    coordinator = SimpleNamespace(last_update_success=True, data={
        "connection_status": "online", "data_source": "bridge", "device_timestamp": 1000,
        "process_status": "running", "heater_enabled": True})
    clock = [0]
    namespace["time"] = SimpleNamespace(monotonic=lambda: clock[0])
    sensor = namespace["ConnectionWarningSensor"](
        coordinator, SimpleNamespace(key="connection_warning"))
    # The HA stub has no suspended work; drive the lifecycle without an OS loop.
    with pytest.raises(StopIteration):
        sensor.async_added_to_hass().send(None)
    return sensor, coordinator, clock, timers, removed


def test_sensor_warns_during_coordinator_failure_and_cleans_up_timer(sensor_context):
    sensor, coordinator, clock, timers, removed = sensor_context
    assert sensor.is_on is None
    assert timers[0][1] == 5
    clock[0] = 30
    coordinator.data["device_timestamp"] = 1030
    sensor._handle_coordinator_update()
    assert sensor.is_on is False
    # No new callback/data is required to expire the evidence.
    coordinator.last_update_success = False
    clock[0] = 151
    timers[0][0](None)
    assert sensor.available is True
    assert sensor.is_on is True
    assert sensor.extra_state_attributes["activity_at_risk"] is True
    sensor._handle_coordinator_update()
    assert sensor.is_on is True
    coordinator.last_update_success = True
    coordinator.data["device_timestamp"] = 1152
    clock[0] = 152
    sensor._handle_coordinator_update()
    assert sensor.is_on is False
    for remove in sensor.removers:
        remove()
    assert removed == [True]


def test_unchanged_healthy_day_and_outage_do_not_publish_periodic_states(sensor_context):
    sensor, coordinator, clock, timers, _ = sensor_context
    tick = timers[0][0]
    assert sensor.writes == 0
    # Synthetic day: advancing normal polls every 30 s, passive ticks every 5 s.
    for seconds in range(5, 86401, 5):
        clock[0] = seconds
        if seconds % 30 == 0:
            coordinator.data["device_timestamp"] = 1000 + seconds
            sensor._handle_coordinator_update()
        tick(None)
    assert sensor.writes == 1  # Unknown -> healthy, not one write per tick/poll.
    assert sensor.is_on is False
    assert "age_seconds" not in sensor.extra_state_attributes

    coordinator.last_update_success = False
    for seconds in range(86405, 172801, 5):
        clock[0] = seconds
        sensor._handle_coordinator_update()
        tick(None)
    assert sensor.writes == 2  # One expiry, no repeated writes during the outage.
    assert sensor.is_on is True
    assert sensor.extra_state_attributes["activity_at_risk"] is True
    assert sensor.extra_state_attributes["last_device_timestamp"] == 87400

    clock[0] = 172805
    coordinator.last_update_success = True
    coordinator.data["device_timestamp"] = 173805
    sensor._handle_coordinator_update()
    assert sensor.writes == 3
    assert sensor.is_on is False


def test_timer_publishes_at_expiry_and_activity_changes_are_not_suppressed(sensor_context):
    sensor, coordinator, clock, timers, _ = sensor_context
    clock[0] = 30
    coordinator.data["device_timestamp"] = 1030
    sensor._handle_coordinator_update()
    assert sensor.writes == 1
    clock[0] = 60
    coordinator.data.update(device_timestamp=1060, heater_enabled=False)
    sensor._handle_coordinator_update()
    assert sensor.writes == 2  # Meaningful metadata changed while still healthy.
    assert sensor.extra_state_attributes["last_known_heater_enabled"] is False
    clock[0] = 179
    timers[0][0](None)
    assert sensor.writes == 2
    clock[0] = 180
    timers[0][0](None)
    assert sensor.writes == 3
    assert sensor.is_on is True
    timers[0][0](None)
    assert sensor.writes == 3
