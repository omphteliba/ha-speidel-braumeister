# Local-only Bridge mode

The Bridge already receives device messages and can answer them without forwarding
to MySpeidel. This mode removes the integration's remaining cloud dependencies:
setup authentication, optional web metadata, cloud fallback and diagnostic probes.

## Existing installations

1. Keep the existing Speidel Braumeister integration entry. In its Configure/Options
   dialog enable **Local Bridge only (no cloud)**. The integration reloads with a
   fixed five-second polling interval; the separate cloud interval is ignored.
2. In the Bridge app set `forward_to_cloud: false` and restart the app. Preserve DNS
   routing and all existing control permissions. MySpeidel will no longer receive
   the device's current state.
3. Keep the current entities and dashboard mappings. No duplicate device is needed.

New installations select local-only mode on the first setup form, leave cloud
credentials blank and enter the device ID reported by the Bridge. Existing combined
Machine UUIDs are also supported. The integration still requires the separately
installed Bridge app and correct device-to-Bridge DNS routing.

An existing cloud-created entry can switch back using its retained credentials.
A credential-free entry cannot turn on cloud mode without a separate cloud setup.

## Runtime behavior

- One local status request per polling cycle, shared by all integration entities.
- No cloud clients, login, metadata enrichment, fallback or diagnostic requests.
- Startup succeeds with an unavailable Bridge/device; subsequent polls recover.
- Messages older than ten seconds are treated as offline. Device reporting cadence
  and request duration contribute to actual display latency; five-second polling
  is not a guarantee that every device change appears within exactly five seconds.
- Cloud-only information may be absent. Existing cloud-capable mode is preserved.
- Optional control clients can emit `braumeister_menu_updated` with `device_id`
  after a confirmed action. A matching local-mode entry requests an extra refresh.
  This event carries no device command and is not required for regular polling.
  Companion beta.12 implements it and accepts fresh acknowledged local responses;
  that separate repository is not a dependency for local telemetry.

## Validation and hardware observations

Automated tests exercise credential-free setup/reload, diagnostics without cloud
clients, existing-entry migration, five-second timing configuration, unavailable
Bridge fallback prevention, matched refresh events, and local Bridge control with
forwarding prohibited. Existing cloud setup, reauthentication and polling tests
remain in place.

The tester reports responsive recipe navigation, manual pump/heater feedback and
brewing-process updates with the coordinated fork beta. Phone, PC and physical
screen changes appear nearly synchronous. These observations are qualitative and
were made with the fork's additional display/control changes, not with a separately
installed build of this upstream PR. See the [hardware report](local-mode-hardware-test-2026-11-14.md).

A full hardware test with WAN access blocked, including HA/Bridge restart, remains
open. Preserve LAN/DNS access during that test and check offline detection, recovery,
phase changes and alarms. This change does not enable additional brewing actions.
