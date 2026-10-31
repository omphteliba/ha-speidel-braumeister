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
