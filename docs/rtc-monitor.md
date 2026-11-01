# RTC offset diagnostics

Two diagnostic entities are added without changing polling or sending commands:

- **RTC offset** (`rtc_offset`, minutes): positive means the Braumeister clock is
  ahead of Home Assistant; negative means it is behind.
- **Check RTC** (`rtc_warning`, problem binary sensor): turns on after at least
  three fresh abnormal samples spanning three minutes. Automations can notify on
  its transition to `on`, even when no dashboard is open. No notification is sent
  automatically by the integration.

The comparison uses the device's `time_display` (HH:MM) and Home Assistant's
configured local timezone. Configure that timezone to match the device. One
minute of uncertainty is allowed for quantization and normal delivery delay;
warning starts at an absolute displayed offset of six minutes (five minutes
beyond that tolerance). A +3 minute manual RTC adjustment is visible in the
sensor without triggering the warning. A fresh reading within tolerance clears
it. These constants are intentionally fixed for this initial diagnostic.

Freshness is independent of the device's absolute RTC value. The first payload
only establishes a baseline. Device timestamps must then advance plausibly
relative to host monotonic time. Re-fetching the same payload never refreshes
its age or increments warning persistence. After 120 seconds without progression,
both values become unknown on the next coordinator update. Offline/missing or
malformed data clears evidence; source changes, timestamp discontinuities, host
clock corrections and timezone/DST changes require a new baseline. Only verified
bridge/XHR clock fields are used by these paths; MQTT without them is unknown.

This is a clock-face offset, not oscillator drift per day. Midnight wraps to the
shortest signed difference in [-720, 720) minutes; wrong dates and offsets of a
whole day cannot be detected. Cloud responses with steadily advancing but delayed
payloads can bias the measurement. No bounded transport delay is guaranteed, so
this is an approximate diagnostic, not proof that an RTC error caused a Wi-Fi
or cloud failure. It never changes device time, firmware state, recipes or commands.

## Hardware validation

User-reported hardware test on 2026-11-01 with a Braumeister 20 L Plus,
firmware 1.1.27, using the RTC implementation in fork release 2.0.11-beta:

- Both diagnostic entities registered after using `EntityCategory.DIAGNOSTIC`.
- With the device clock manually advanced, RTC offset reported +9 minutes.
- Check RTC changed from OK at 13:06:11 to Problem at 13:09:12, consistent
  with the three-minute persistence requirement.
- After manually correcting the device clock, Check RTC became unknown at
  13:18:37 and OK at 13:18:47; RTC offset then reported +1 minute.

This validates warning activation and recovery on that installation. It is
not a measurement of long-term oscillator drift or proof of a connection
failure caused by RTC offset. Automated tests additionally cover stale and
repeated payloads, malformed data, offline state, midnight, source changes,
and host clock/timezone changes.

The entity registration regression test explicitly checks the category enum
instance for both entities: a plain string equal to `"diagnostic"` is rejected
by Home Assistant's entity registry. The test uses HA boundary stubs; actual
registration was verified in the hardware test above.
