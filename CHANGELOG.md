# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Pump and heating sensors are now enum sensors with the states `on`/`off`**, translated by Home Assistant (English On/Off, German Ein/Aus). Before, they always showed the German words "Ein"/"Aus". Automations that compare the state with "Ein"/"Aus" must use `on`/`off` instead
- Connection status, subscription required and process status are enum sensors with translated states as well (e.g. process status `running` shows as "Läuft" in German). "Subscription required" changed from `Yes`/`No` to `yes`/`no`
- Requires Home Assistant 2025.1 or newer (`hacs.json`), matching the Pydantic v2 requirement
- `hacs.json` reduced to the keys HACS accepts; `issue_tracker` added to the manifest

### Fixed
- Pump and heating state were read from the wrong XHR status fields (a seconds counter and a recipe counter). They are now taken from the actuator flags in field 14 (`P`/`H` on; `p`/`q`, `h`/`i` off), as in MySpeidel's own web display (thanks to DanielP-1337, PR #8)
- Remaining time always showed 80 minutes and the process status was always "running": the field used is the step duration, not the remaining time. Remaining time is now calculated during rests and the boil and left empty otherwise
- Process status is now derived from the device state code (automatic program = running)
- Target temperature `-1000`/`-10000` ("no target") is no longer reported as a negative temperature; `0` between program steps is shown as 0 °C like in the MySpeidel web interface
- The alarm binary sensor had no English name
- "Current phase" showed the text `UNKNOWN` instead of an unknown state
- German: "Current phase" and "Current step" were both called "Aktueller Schritt"; the phase sensor is now "Aktuelle Phase"
- Wrong recipe name after recipes were re-sorted and re-synced to the device: the device recipe list is now reloaded when it changes, and the name of the running recipe is taken from the web interface's step text
- The main menu no longer shows the previous program's target temperature (the device keeps reporting it there)
- A running brew was shown as idle because the web interface reports the mode "wartet" even during a program. The coordinator now trusts the device state code
- Boiling (state 3xxx) now also counts as a running program
- The recipe slot (and with it the brew name) was always 0 / the first recipe; it is now read from the correct field and only during a program

### Added
- New **Braumeister Bridge** app (`braumeister_bridge/`, add this repository to the app store): receives the Braumeister's cloud traffic locally via a DNS entry for `api2.myspeidel.com`, forwards it to My Speidel and passes other port-80 traffic on (e.g. to `emulated_hue`). The integration reads from it first and falls back to the web interface
- Recipe names come from the device's own recipe list when the bridge is used
- With the bridge, the step text, mode and device type are still taken from the web interface when it is reachable; progress is calculated locally (field 12, 318 = 100 %)
- Remaining time during rests and the boil, calculated from the step duration and elapsed time in the device status
- Process status `finished` when the brew has ended
- Alarm binary sensor now uses the device state code, so it is on while the device beeps for an alarm (mash-in temperature reached, rest end, remove lid, hop addition, brew finished), the same rule MySpeidel's web display uses (it never triggered via XHR polling before). New attributes `alarm_type` and `state_code`.
- With debug logging enabled, the integration logs once at startup what the documented cloud timeseries API returns
- `docs/DEVICE_PROTOCOL.md`: the device's own protocol to the cloud, reverse-engineered from a packet capture
- `device_protocol.py`: shared parser for the device status message, used by both XHR clients

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
