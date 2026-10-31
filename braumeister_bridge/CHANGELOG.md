## 0.1.4 (DanielP-1337 fork)

- Request uncompressed cloud responses for the legacy WLAN module.
- Decode gzip and deflate responses if the server still compresses; remove
  stale encoding and representation headers. Keep command bytes unchanged.
- Leave chunked transfer and the unrelated HTTP passthrough unchanged.

# 0.1.2 (DanielP-1337 fork)

- Add dedicated cloud DNS resolution for AdGuard rewrite deployments.
- Reject non-public DNS answers on the outbound cloud path.
- Default built-in DNS to disabled; continue forwarding device traffic to cloud.
- Preserve cloud response headers and bytes; do not follow redirects.
- Upstream base: dda46326cec491567449a7f907399eb76d4a1542.

# Changelog

## 0.1.1

- Log every change of state code, pump/heater flags and alarm indicator, so short
  events (e.g. a hop-addition beep) show up in the app log.

## 0.1.0

- First version: DNS answer for `api2.myspeidel.com`, receiver on port 80 with forwarding to
  My Speidel, passthrough of other port-80 traffic, local status API for the integration.
