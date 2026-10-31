# Adaptive polling (experimental hardware-test patch)

Based on parser-fix commit `0919c45` (PR #8); this patch does not duplicate that fix or modify the dashboard.

## Default cadence

| State | Interval |
| --- | --- |
| Offline, unknown, failed update | Existing `scan_interval`, default 30 seconds |
| Online / main menu / idle | 10 seconds |
| Brewing, brewing dialogs/pauses, manual operation, active P/H or alarm | 5 seconds (configurable down to 3) |

Options take precedence over the original config entry. Existing custom base intervals are retained. Faster states are capped at the preceding slower interval: active <= online <= base. The options form shows saved options when reopened. Configuration changes reload the integration through its existing listener.

The coordinator sets its next `update_interval` after each fetch. This is a polling delay, not a hard latency guarantee: request duration and cloud/device delays add to it. An offline-to-online transition can take a base interval to discover; a brew start from idle can take an online interval. Failure returns to the base cadence; no parallel polling loop or automatic device commands are added.

## Fast data and state selection

Each XHR telemetry response supplies temperature, P/H, numeric `BrauStatus` (field 3) and the alarm bits (field 15). The cadence uses the current numeric code in preference to cached mode, recipe, or time. Codes 2021–3449 cover automatic brewing and dialogs; 4006/4007 cover manual operation. Active actuators or alarms also select the fast cadence. When there is no numeric code (e.g. cloud fallback), explicit running/paused process or manual/automatic mode is used.

The German step text, mode and other device JSON information are refreshed every 30 seconds; they can lag behind the fast P/H/temperature/alarm data. Device and account recipes are refreshed every 300 seconds. Attempts are throttled even for empty lists and failures. Periodic auxiliary refreshes still run sequentially in the same update and can delay that update. Each GET has a 10-second timeout; retries across alternative device IDs can take longer overall. There are no unmanaged background refresh tasks.

The existing WebSocket client is retained, not validated or replaced. A received message stops suppressing XHR polling after 30 seconds without another message. This fixes the previous indefinite reuse of old MQTT data; it is not proof that the Speidel endpoint supports this client's presumed protocol/topics.

## Alarms

Based on the supplied original MySpeidel `bm_controll.min.js`, `parseStatus`, `updateScreen` and `buildScreen`:

- field 15 character 1 (zero-based): `1` or `2` triggers sound; `D` is a cover warning;
- codes 3080–3449 identify the hop-addition dialog when not interrupted;
- missing/unrecognized alarm flags are unknown, not forced off;
- a fresh fast alarm value takes precedence over old phase text;
- legacy cloud data without an alarm field retains the existing phase-name fallback.

This is a polled binary state, not a queued alarm event or push notification. A short signal entirely between two polls can be missed. Hop-alarm and cover-warning decoding must still be checked on the actual firmware. No notifications, sounds, automations, acknowledgements or device-control calls are added by this patch.

## Install for a hardware test

1. Back up the current HA `custom_components/speidel_braumeister` folder.
2. Apply the patch on a new branch based on `fix/xhr-pump-heating-status` (commit `0919c45`).
3. Run `python -m unittest discover -s tests -v` with aiohttp installed.
4. Copy these changed runtime files from the patched branch into the existing HA integration folder, preserving subdirectories:
   - `__init__.py`
   - `config_flow.py`
   - `coordinator.py`
   - `web_auth.py`
   - `binary_sensor.py`
   - `polling.py` (new)
   - `strings.json`
   - `translations/de.json`
   - `translations/en.json`
5. Keep `status_parser.py` and the corrected `xhr_client.py` from PR #8 installed.
6. Restart Home Assistant. In the integration options, use base 30, online 10, active 5 seconds. After a successful test, optionally set active to 3.

For rollback, restore the backed-up integration folder and restart HA. Applying a git patch alone does not change your running HA installation.

## Validation

Offline unittest coverage exercises the real XHR parser and coordinator fetch methods, using simulated responses and minimal HA boundary doubles. Checks include options precedence, legacy values, interval bounds, offline/main-menu/brew/manual transitions, pauses with P/H off, 3-second polling, failure fallback, stale MQTT data, recipe/metadata throttling, alarm decoding and binary sensor propagation. The original actuator tests remain included.

These tests are not a full Home Assistant runtime/scheduler test and do not establish cloud rate limits or hardware behavior. No network requests or live device commands are sent by the tests.

Hardware checklist: check idle at 10 s, manual/brewing at 5 s, stop/return to main menu at 10 s, device offline at 30 s, then reconnect. Check a real hop-addition signal and its clearing. Test 3 s only after 5 s is stable. In debug logs the coordinator reports `Adaptive polling: state=..., next interval=...` after each update.

Reference: https://contributors.home-assistant.io/core/integrations/fetching-data/
