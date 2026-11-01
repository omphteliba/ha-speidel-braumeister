# Elapsed step time (issue #6)

Interprets "IST Time" as the device-reported elapsed time of the current rest
or boil, not wall-clock time and not the total duration of the brew. Maintainer
feedback on this interpretation is welcome.

Adds `elapsed_time` / "Elapsed step time" (German: "Verstrichene Phasenzeit"),
a duration sensor in seconds. It reads status field 7 in states 2820 (rest),
3070 (boil), and 3080 (hop addition, where the documented boil timer continues).
The sensor reports the device value unchanged, including zero and overruns;
it does not extrapolate between polls or accumulate across phases/restarts.
There is no total-increasing statistics class because phase timers reset.

Menus, heating to the target, manual operation, malformed/negative timers,
and offline data have no elapsed value. MQTT without a verified phase timer
clears an older bridge/XHR value. Existing remaining-time semantics are unchanged.

Offline tests cover parser -> XHR/bridge -> coordinator -> sensor, hop alarm
transitions, zero, phase reset, overrun, invalid values and source changes.
The HA entity boundary is stubbed; this is not a new live hardware test.
A live rest/boil test should compare the new sensor with the controller's
IST time before, during and after a hop-addition acknowledgement.
