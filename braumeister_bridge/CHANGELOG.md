# Changelog

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
