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
credentials blank and select a device discovered through the local Bridge status
API. If no devices are known, the form offers manual ID entry and instructions
to check device-to-Bridge routing. Saving requires a reachable Bridge and a known
device ID. Existing combined Machine UUIDs are also supported; duplicate detection
compares the long ID before the dot. This initial setup check does not change
offline startup/recovery for already configured entries. The integration still requires the separately
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

## Validation

Automated tests exercise credential-free setup/reload, local device discovery and
validation, duplicate detection across ID formats, diagnostics without cloud
clients, existing-entry migration, five-second timing configuration, unavailable
Bridge fallback prevention, matched refresh events, and local Bridge control with
forwarding prohibited. Existing cloud setup, reauthentication and polling tests
remain in place.
