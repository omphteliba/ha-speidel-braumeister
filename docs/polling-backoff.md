# Polling backoff and server protection

Applies on top of `perf/adaptive-polling`, including release `2.0.4-beta`.
No version/tag changes are included. Publish a new prerelease after testing;
do not move the existing `2.0.4-beta` tag.

## Successful requests versus errors

A successful response reporting an offline device stays at the configured base
interval (default 30 seconds). It does **not** progressively slow to 300 seconds.
Online idle remains 10 seconds and active brewing/manual mode 5 seconds by default
(or the configured 3 seconds).

Every normal interval receives positive jitter of 0–10%, limited to 5 seconds.
Examples: 3–3.3, 5–5.5, 10–11, 30–33 seconds. These are scheduling intervals;
network latency and HA scheduling add to the observed delay.

Consecutive transport/server failures use base × 2^(failures−1), capped at
max(300 seconds, configured base). Default: 30, 60, 120, 240, 300 seconds,
plus jitter. Any successful refresh, including offline, resets the failure count.
Failed updates become unavailable rather than presenting old data as fresh.

429 and 5xx stop the entire HTTP refresh, including alternate IDs, login retries,
metadata/recipe requests and fallback to another endpoint. Retry-After supports
integer seconds and HTTP-date; absent/invalid values use a 30-second client
pause plus coordinator exponential backoff. The longer of local backoff and
server delay applies, followed by positive jitter. A valid server delay is not
shortened to the 300-second local cap. Very long waits are checked locally in
one-day scheduling slices without making HTTP requests before the deadline.
Transport errors/timeouts also terminate fallback attempts.

The guards cover web_auth, the legacy XHR client and Cloud API HTTP requests.
State is in memory per client/coordinator; it is not account-wide across separate
HA installations and does not persist across an integration reload or restart.
Do not repeatedly reload the integration to bypass a server pause.

## Opening the dashboard

The existing custom card only reads HA states. Opening it does not call MySpeidel.
Healthy offline detection therefore takes up to roughly 33 seconds at defaults,
plus device boot, WLAN/cloud propagation and request latency. During a real
server failure or Retry-After pause it can take longer, intentionally.

`homeassistant.update_entity` on ONE Braumeister sensor requests a coordinator
refresh for all its sensors. It does not require a separate call per sensor.
It respects active error/server cooldowns; repeated clicks neither bypass nor
extend the deadline. A click does not guarantee that the device has booted yet.

Optional dashboard button (manual YAML card; replace entity for other users):

```yaml
type: button
name: Jetzt aktualisieren
icon: mdi:refresh
tap_action:
  action: perform-action
  perform_action: homeassistant.update_entity
  target:
    entity_id: sensor.badezimmer_braumeister_20l_plus_temperatur_2
```

Optional automation: paste into the YAML editor of ONE new HA automation.
This is a bounded refresh after power-on, not another polling loop.
The delay allows boot/WLAN startup; adjust it if your device takes longer.

```yaml
alias: Braumeister nach Einschalten aktualisieren
triggers:
  - trigger: state
    entity_id: switch.braumeister_20l_r_s60_3
    from: "off"
    to: "on"
actions:
  - delay: "00:00:15"
  - condition: state
    entity_id: switch.braumeister_20l_r_s60_3
    state: "on"
  - action: homeassistant.update_entity
    target:
      entity_id: sensor.badezimmer_braumeister_20l_plus_temperatur_2
mode: single
```

## Validation

Run `python -m unittest discover -s tests -v`. Tests use fake HTTP responses and
HA boundary doubles, never live server overload tests. Coverage includes HTTP
429/5xx at login/status/metadata/recipes, both header formats, invalid headers,
transport timeouts, cancellation, exponential cap, reset, manual cooldown and
absence of fallback after a rate limit. Full HA scheduler and hardware validation
remain necessary. No credentials or session cookies belong in test fixtures.

HTTP semantics: https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after
HA refresh action: https://www.home-assistant.io/integrations/homeassistant/
