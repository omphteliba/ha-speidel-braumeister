# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Local display texts for the current step derived from the device state ("Malz einfüllen!", "Malzrohr entnehmen!", "Hopfen zugeben" …), no cloud needed with the bridge (thanks to DanielP-1337, #12)
- Braumeister Bridge 0.3.0: loop protection for network-wide DNS rewrites, optional `cloud_dns` resolver, `dns_port: 0` allowed, deflate answers decoded (thanks to DanielP-1337, #13)
- Example brewery dashboard (`examples/brewery-dashboard.yaml`, README section "Example Dashboard"): temperature gauge, status chips, progress, alarm banner, temperature curve and recipes

### Fixed
- Braumeisters set to **Fahrenheit** reported their °F values as °C (e.g. 91.5 °C instead of 33 °C), and at boiling temperature the value was dropped as implausible. Temperatures are now converted to °C; Home Assistant shows them in the user's unit
- The target temperature is now only shown during a program or manual mode; in the settings menu it showed the last program's stale value (after switching °F back to °C even as 104 °C)
- With the device set to Fahrenheit, the recipe temperatures (Device Recipes sensor) were °F values labelled °C; they are converted to °C as well
- Example dashboard: the recipe table was rendered as a single line (folded YAML block instead of a literal one)

## [3.0.0] - 2026-10-31

Highlights: **alarms that actually work**, and the optional **Braumeister Bridge** app that
receives the device's data locally, every second.

### Breaking changes
- **Pump and heating sensors are enum sensors with the states `on`/`off`**, translated by Home Assistant (On/Off, Ein/Aus). They used to always show the German words "Ein"/"Aus". Automations comparing the state with "Ein"/"Aus" must use `on`/`off`
- Connection status, subscription required and process status are enum sensors with translated states as well. "Subscription required" changed from `Yes`/`No` to `yes`/`no`
- Requires Home Assistant 2025.1 or newer

### Alarms
- The **alarm binary sensor** is on while the Braumeister beeps and waits for you – the same rule the My Speidel web display uses. Before, it never triggered via XHR polling
- Recognized alarms (attribute `alarm_type`): mash-in temperature reached, rest end reached, remove lid, hop addition, brew finished. All verified in live brews
- Attribute `state_code` with the raw device state

### Braumeister Bridge app (new, optional)
- `braumeister_bridge/`: add this repository to the app store. Answers DNS for `api2.myspeidel.com`, receives the device's messages on port 80, forwards them to My Speidel (app, web interface and recipe sync keep working) and passes other port-80 traffic on (e.g. to `emulated_hue`)
- The integration reads from the bridge first and falls back to the web interface; step text, mode and device type are still taken from the web interface when reachable
- Status every second instead of every 30 s; temperature, pump, heater and alarms keep working without the cloud
- Recipe lists are kept across restarts and while the device is off
- See `braumeister_bridge/DOCS.md` and the README section "Local Mode"

### Added
- Sensor **Device Recipes** ("Rezepte auf dem Gerät"): number of recipes on the device, every recipe (mash-in, rests, boil, hop additions) as attributes
- Remaining time during rests and the boil
- Progress calculated from the device status (318 = 100 %), like the web interface
- Process status `finished` when the brew has ended
- `docs/DEVICE_PROTOCOL.md`: the device protocol, reverse-engineered from packet captures, firmware strings and MySpeidel's web display
- Tests (pytest, 78 tests), ruff, hassfest/HACS validation and app checks in GitHub Actions
- With debug logging, the integration logs once at startup what the documented cloud timeseries API returns

### Fixed
- Pump and heating were read from the wrong status fields (a seconds counter and a recipe counter); now from the actuator flags, as in MySpeidel's own display (thanks to DanielP-1337, PR #8)
- Remaining time always showed 80 minutes and the process status was always "running"
- A running brew was shown as idle (the web interface reports "wartet" even during a program); boiling now also counts as running
- Wrong recipe name: the recipe slot was read from the wrong field, and the recipe list was not reloaded after a re-sync
- Target temperature: no negative values for "no target", no stale target in the main menu; 0 °C between steps like the web interface
- "Current phase" showed the text `UNKNOWN`; in German it had the same name as "Current step"
- The alarm binary sensor had no English name
- `hacs.json` and manifest fixed for HACS validation

## [2.0.3] - 2026-03-03

### Fixed
- Fixed "'DeviceDataResult' object is not a mapping" error when converting Pydantic v2 models to dictionaries in coordinator
- Added robust conversion with multiple fallback strategies (model_dump for Pydantic v2, dict for v1, vars fallback)
- Added debug logging to help diagnose future data conversion issues
- Improved error handling for API data conversion edge cases

### Technical Details
- The issue occurred when all data sources (XHR, Web API, Cloud API) failed for a device, leaving the coordinator with a DeviceDataResult object that couldn't be converted to a dict
- The fix ensures proper conversion regardless of Pydantic version or edge cases
- Debug logging now tracks which conversion method is being used (e.g., "Using model_dump() for conversion", "Using dict() for Pydantic v1", etc.)

## [2.0.2] - Previous Release

## [2.0.1] - Previous Release

## [2.0.0] - Previous Release
