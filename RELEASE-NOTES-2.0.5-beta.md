# 2.0.5-beta — adaptive polling with server protection

Prerelease from `perf/adaptive-polling` in DanielP-1337/ha-speidel-braumeister,
including the polling protection change at `64797d8`.

## Changes since 2.0.4-beta

- Exponential backoff after communication/server errors: 30, 60, 120, 240,
  then 300 seconds with the default base interval. Longer configured base
  intervals are respected.
- Positive random jitter of 0–10%, limited to 5 seconds, spreads requests.
- Respect Retry-After delay-seconds and HTTP dates on HTTP 429 and 5xx.
  Server-requested waits longer than 300 seconds are not shortened.
- Stop alternate-ID, login and endpoint fallback attempts after transport
  failures or overload responses. Apply HTTP protection to web authentication,
  metadata, recipes, the legacy XHR client and Cloud API requests.
- Manual refresh cannot bypass an active cooldown or extend its deadline.
- Successful requests reset backoff. A healthy server reporting an offline
  device stays at the configured base interval (default approximately 30–33
  seconds with jitter), rather than gradually slowing to five minutes.
- Document an optional dashboard refresh button and a one-shot refresh after
  turning on a smart plug in `docs/polling-backoff.md`.

Includes the existing pump/heater parser correction, fast alarm decoding,
metadata/recipe caching and adaptive 30/10/5-second polling (active configurable
as low as 3 seconds).

## Validation and limitations

29 offline regression tests pass. The previous 2.0.4-beta was tested on real
hardware with 3- and 5-second manual-mode polling. The new backoff behavior was
verified with simulated HTTP errors; full HA runtime/hardware validation of
this prerelease is still pending. No live server overload tests were performed.
Cooldowns are in memory and do not persist across integration reloads/restarts.
They are not shared across separate HA installations. Polling does not guarantee
capture of every short-lived alarm.

## Installation through HACS

Use the DanielP-1337 fork and select prerelease `2.0.5-beta`. Enable beta versions
if necessary, download the release, then restart Home Assistant. Existing
configuration and entity IDs are retained; the integration domain is unchanged.
Do not delete the configured integration/device entry to perform this update.

The optional native dashboard card is on a separate branch and is not installed
or updated by this release. The optional refresh examples must be added manually.
Keep the existing `2.0.4-beta` tag unchanged for comparison/rollback.
