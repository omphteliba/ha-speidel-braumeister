# Changelog

## 0.5.0

All new actions use the loopback API only, need `control_enabled`, a fresh matching
device status and are confirmed by the next status. Everything is off by default.

- Manual mode: pump on/off (`manual_pump_enabled`), heater on (`allow_remote_heating`)
  and heater off (only `control_enabled`, also during a regulation pause) (thanks to
  DanielP-1337, #21)
- Program control: select the highlighted recipe (stops at "Wasser eingefüllt?"), pause
  during pump purging or heating to mash-in, and abort from the pause dialog. Resuming
  after a purge pause additionally needs `program_control_enabled` and
  `allow_remote_heating` (thanks to DanielP-1337, #24)

## 0.4.2

- Recipe navigation accepts up to nine recipes on the device (it refused six or more)

## 0.4.1

- Keeps the last device message with an alarm, so the integration also sees alarms that
  were confirmed between two polls (a hop addition confirmed after 6 seconds was missed)

## 0.4.0

- New option `control_enabled` (off by default): local menu navigation through
  `POST /api/control` on the loopback API (settings, manual mode, recipe list, moving the
  recipe highlight). One action at a time, sent only when pump and heater are off and
  confirmed by the next device status. Works with and without cloud forwarding. Nothing
  is started or heated (thanks to DanielP-1337, #20)

## 0.3.1

- New option `diagnostics_enabled` (off by default): writes a compact summary of each device
  exchange (time, response source, HTTP status, key commands, screen code, actuator flags)
  to `/data/diagnostics-summary.jsonl`, capped at 1 MiB. No device IDs, signatures, account
  data, recipes or raw messages (thanks to DanielP-1337, #19)

## 0.3.0

- Cloud lookups reject private/local answers, so a network-wide DNS rewrite (e.g. AdGuard
  with `dns_port: 0`) can no longer loop the bridge back to itself. New option `cloud_dns`
  for an explicit resolver in that setup; by default the host resolver is used as before.
- `dns_port: 0` is accepted (disables the DNS server, as documented).
- Deflate-compressed cloud answers are unpacked for the device; redirects are not followed.
  (thanks to DanielP-1337, #13)

## 0.2.2

- After a restart the restored recipe list was written again on the first message; now only
  real changes are saved.

## 0.2.1

- The state-change log also shows the temperature unit (field 2) and the display language
  (field 0) and logs when they change.

## 0.2.0

- The recipe list of each device is saved in the app's data folder and restored after a
  restart, so the integration can show the recipes also while the Braumeister is off.

## 0.1.3

- **Fix:** answers from the cloud reached the device gzip-compressed, because aiohttp asked
  for compression on its own. The device could not read them: recipe syncs and other
  commands were lost and it reported only every ~4 s. The bridge now asks for plain text
  and unpacks compressed answers.
- Debug log: status, duration and answer of every request forwarded to the cloud.

## 0.1.2

- Log every command the cloud sends to the device (`$k`, `$rz`, `$d`, ...), e.g. to follow a
  recipe sync.

## 0.1.1

- Log every change of state code, pump/heater flags and alarm indicator, so short
  events (e.g. a hop-addition beep) show up in the app log.

## 0.1.0

- First version: DNS answer for `api2.myspeidel.com`, receiver on port 80 with forwarding to
  My Speidel, passthrough of other port-80 traffic, local status API for the integration.
