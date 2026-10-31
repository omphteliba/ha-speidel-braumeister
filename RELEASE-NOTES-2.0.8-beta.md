# 2.0.8-beta – Rest timers and actuator display

- Expose target/elapsed rest seconds and original P/H display flags as current-step attributes.
- Add optional dashboard card 0.3.0 with recipe/phase heading, rest time and diagonal inactive badges.
- Correct current-step sensor value to return text; metadata belongs in attributes.
- Binary actuator values, forwarding and controls remain unchanged.

Update the integration via HACS and restart HA. Separately install dashboard JS
as described in dashboard/README.md. Bridge remains 0.1.4.

The header clock uses device status field 1 unchanged; its RTC/time source is not established.
Validation: 153 Python tests and 297 subtests; Node card tests and syntax check.
