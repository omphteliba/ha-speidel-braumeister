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

Hardware evidence: on 2026-11-01 a manual +3 minute adjustment on a pre-2020
20 L Braumeister (firmware 1.1.27, external WLAN) also shifted the HA card's
reported device time by +3 minutes. The new diagnostic entities themselves
still need a hardware test after installation.
