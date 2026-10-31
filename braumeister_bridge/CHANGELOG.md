# Changelog

## 0.1.2

- Log every command the cloud sends to the device (`$k`, `$rz`, `$d`, ...), e.g. to follow a
  recipe sync.

## 0.1.1

- Log every change of state code, pump/heater flags and alarm indicator, so short
  events (e.g. a hop-addition beep) show up in the app log.

## 0.1.0

- First version: DNS answer for `api2.myspeidel.com`, receiver on port 80 with forwarding to
  My Speidel, passthrough of other port-80 traffic, local status API for the integration.
