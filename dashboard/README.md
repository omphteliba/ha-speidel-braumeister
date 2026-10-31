# Braumeister Display 0.3.0

Requires integration 2.0.8-beta for local bridge display attributes.
Copy `braumeister-display-card.js` to `/config/www/braumeister-display-card.js`.
Register the dashboard JavaScript module resource as
`/local/braumeister-display-card.js?v=0.3.0` (update the existing resource).
Reload the browser. Keep your existing card YAML and entity IDs; see example.yaml.
HACS integration updates do not copy this dashboard file to www.

The header combines recipe and phase. During rests, Zeit shows target and elapsed
minutes:seconds from device fields 6/7, without a client-side countdown.
Missing times show a dash; offline displays hide times and actuator highlights.
Original P/H flags from the current-step attributes take precedence over binary
sensors: P/H active yellow, q/i inactive diagonal yellow/white, p/h white.
Existing binary sensors and automations are unchanged. Older/cloud data without
these attributes retain the binary display. Unknown flags remain unknown in the
integration. No device controls or audio playback are added in this version.

The header clock uses device status field 1 unchanged; its RTC/time source is not established.
Validation: 153 Python tests and 297 subtests; Node card tests and syntax check.

## Installation and entity selection


Updating a Git checkout or publishing a release does not update the running Home
Assistant installation. Install the integration files under
`/config/custom_components/speidel_braumeister` and restart Home Assistant.
Copy the dashboard JavaScript separately to `/config/www`, update the existing
module resource URL to invalidate the browser cache, and reload the dashboard.

Configure all entity IDs explicitly using `example.yaml`. In particular,
`entities.step` must reference the current-step sensor whose attributes include
`display_state_code`, `display_clock`, and `display_time_elapsed_seconds`.
The German translations currently give both current_phase and current_step the
name "Aktueller Schritt". Numeric entity-ID suffixes are installation-specific:
select by attributes in Developer Tools > States, not by the name or suffix.
The current-phase sensor can show the correct text while providing none of the
attributes required for the clock, rest timer, or diagonal actuator indicators.

## Hardware validation (2026-10-31)

User-reported test on a pre-2020 Braumeister 20 L Plus with external WLAN module,
firmware 1.1.27, using the local bridge and AdGuard DNS rewrite:

- MySpeidel commands reached the device after compressed-response handling was fixed.
- Home Assistant and MySpeidel showed synchronized temperatures and brewing steps.
- The dashboard displayed the device clock, target/elapsed rest time, and diagonal
  heater indication during temperature holding.
- During an automatic brew, the device was unplugged, left off, and powered on
  again. The user reported that the process continued at the same elapsed time
  and both dashboards remained synchronized.

This validates the observed automatic-brew scenario on that device; it is not a
claim that manual-mode actuators restart automatically or that the bridge
implements process persistence. The device owns the brewing process and timer.
