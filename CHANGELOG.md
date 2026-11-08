# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Braumeister Bridge 0.5.0: optional local pump and heater control in manual mode and program control (select recipe up to the water prompt, pause, abort, resume after a purge pause). Off by default, loopback API only; heating needs `allow_remote_heating` (thanks to DanielP-1337, #21, #24)
- Recipe upload without My Speidel: action **Upload recipes** (`speidel_braumeister.upload_recipes`) with Braumeister Bridge option `recipe_write_enabled` (off by default). Replaces all recipes on the device from the main menu, the same way the cloud does, each slot confirmed by the device. Same format as the Device Recipes sensor attribute; names are cut to 14 characters. Tested on a Braumeister 20 L with nine recipes

### Changed
- MySpeidel overload or server errors (HTTP 429/5xx) pause cloud and web requests, honoring `Retry-After` (otherwise 30 s up to 5 min), instead of trying further endpoints and logins. A timeout only ends the current refresh. If MySpeidel is unreachable at startup, Home Assistant retries the setup later (thanks to DanielP-1337, #14)

## [3.2.0] - 2026-11-06

### Added
- Diagnostics download (Settings → Devices & services → ⋮ → Download diagnostics): data source, device type, firmware and the Cloud API v1.0 answers, with account data, IDs, tokens and signatures removed
- Read-only fallback for newer Braumeister models: process status, phase, temperature, pump and heater from the Cloud API v1.0 timeseries when neither the Bridge nor the web interface has data. Untested on real devices; the mapping is a best guess from the API documentation
- Guide and issue template for owners of newer models (`docs/NEW_DEVICES.md`)
- Passive device connection watchdog: warns on stale device timestamps and retains last-known brewing/heater permission, without extra requests or periodic recorder writes for unchanged status (thanks to DanielP-1337, #23)

### Changed
- Process status "waiting" (Waiting for start / Wartet auf Start) while a recipe is selected or the start screen "Wasser eingefüllt?" is shown (states 2015, 2030). Before, these counted as "running" although nothing heats. Automations that check for `running` no longer trigger there

### Removed
- The MQTT client: it was based on a guessed protocol, never received data and was not even started for accounts with a web login. Real-time support for newer models will be based on recorded traffic (see `docs/NEW_DEVICES.md`)

### Fixed
- Braumeister Bridge 0.4.2: recipe navigation refused devices with six or more recipes; the Braumeister holds up to nine

## [3.1.0] - 2026-11-05

### Added
- Local display texts for the current step derived from the device state ("Malz einfüllen!", "Malzrohr entnehmen!", "Hopfen zugeben" …), no cloud needed with the bridge (thanks to DanielP-1337, #12)
- Braumeister Bridge 0.3.0: loop protection for network-wide DNS rewrites, optional `cloud_dns` resolver, `dns_port: 0` allowed, deflate answers decoded (thanks to DanielP-1337, #13)
- "Elapsed Step Time" sensor: elapsed time of the current rest or boil as reported by the device, also during hop additions (thanks to DanielP-1337, #17)
- RTC diagnostics: "RTC offset" (device clock vs. Home Assistant time, in minutes) and "Check RTC", a problem sensor when the clock is off by 6 minutes or more for 3 minutes, e.g. after a DST change (thanks to DanielP-1337, #15)
- Braumeister Bridge 0.3.1: optional diagnostic summary of device exchanges, without IDs or raw data (thanks to DanielP-1337, #19)
- Braumeister Bridge 0.4.0: optional local menu navigation (off by default, no starting or heating) (thanks to DanielP-1337, #20)
- Example brewery dashboard (`examples/brewery-dashboard.yaml`, README section "Example Dashboard"): temperature gauge, status chips, progress, alarm banner, temperature curve and recipes

### Changed
- New integration icon (a brew kettle drawn by @DanielP-1337, #22) instead of the Speidel logo, and a README note that this is an unofficial project, not affiliated with Speidel

### Fixed
- Short alarms are no longer missed: with Braumeister Bridge 0.4.1, an alarm confirmed at the device between two polls (e.g. a hop addition) is still reported for one poll
- The alarm sensor could stay on after an alarm was acknowledged when no state code was available; the decoded alarm now always wins over the old phase text (thanks to DanielP-1337, #16)
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
