# Braumeister Bridge

Receives the data your Speidel Braumeister sends to the My Speidel cloud, directly in Home
Assistant. The Speidel Braumeister integration then reads the status locally, about once per
second instead of via the web interface. The data is still forwarded to My Speidel, so the
app and the web interface keep working.

Works with Braumeisters with the WiFi module and firmware 1.1.27.

## How it works

The Braumeister looks up `api2.myspeidel.com` via DNS when it connects. This app

1. runs a small DNS server that answers this one name with the Home Assistant IP and forwards
   all other names to your normal DNS server,
2. receives the Braumeister's messages on port 80 and forwards them to My Speidel,
3. passes every other request on port 80 to another service if you configure one (see below),
4. provides the latest messages to the integration on `127.0.0.1:8642`.

## Setup

1. Install and start this app.
2. On the Braumeister, open the WiFi settings and set the **DNS server** to the IP address of
   your Home Assistant. Only the Braumeister uses this DNS server; the rest of your network is
   not affected.
3. Switch the Braumeister off and on again. It only looks up the server address when it
   connects.
4. The app log shows `DNS api2.myspeidel.com from <Braumeister IP>` and the integration starts
   using the local data (debug log: `Got data via Braumeister Bridge`).

## Port 80 is already in use

The Braumeister always connects to port 80. If another service on your Home Assistant host
already uses port 80, move it to another port and enter it as `passthrough_url`. The app then
forwards every request that is not from the Braumeister to it.

Example for `emulated_hue` (Alexa expects it on port 80):

```yaml
emulated_hue:
  listen_port: 8300
  advertise_port: 80
```

App option: `passthrough_url: http://127.0.0.1:8300`

## Options

| Option | Default | Meaning |
|---|---|---|
| `bridge_ip` | auto | IP returned for `api2.myspeidel.com`. Auto-detected from the host. |
| `cloud_host` | `api2.myspeidel.com` | Hostname the Braumeister talks to. |
| `forward_to_cloud` | `true` | Forward messages to My Speidel. If `false`, or if the cloud is unreachable, the app answers itself and My Speidel shows the device as offline. |
| `upstream_dns` | auto | DNS server for all other names. Auto-detected from the host. |
| `cloud_dns` | `[]` | Host resolver by default; explicitly set DNS servers without the local rewrite when needed. |
| `dns_port` | `53` | Port of the DNS server. `0` turns it off (if you use your own DNS). |
| `http_port` | `80` | Port for the Braumeister's messages. Must be 80 for a real device. |
| `passthrough_url` | empty | Where other requests on port 80 go, e.g. `http://127.0.0.1:8300`. |
| `api_port` | `8642` | Local status API for the integration (only reachable from the host). |
| `log_level` | `info` | `debug` logs every message. |
| `recipe_write_enabled` | `false` | Allow replacing the device's recipes via the local API (see *Recipe upload*). |


## Cloud DNS and AdGuard rewrites

The built-in DNS remains enabled on `dns_port: 53` by default. For an existing
AdGuard (or other DNS) rewrite of `api2.myspeidel.com` to the HA host, set
`dns_port: 0` to disable only the bridge's DNS listener. The device must actually
use that DNS server; some routers use a separate resolver on guest Wi-Fi.

By default, `cloud_dns: []` uses the host resolver. In the documented setup,
only the Braumeister uses the bridge's DNS, so no separate cloud resolver is
needed and no third-party DNS service is selected by the bridge.

For a network-wide AdGuard rewrite with `dns_port: 0`, configure `cloud_dns`
with a reachable DNS resolver that does not apply the local rewrite. For example,
`cloud_dns: ["1.1.1.1", "1.0.0.1"]` explicitly opts into Cloudflare; choose a
resolver permitted by your network and your DNS/privacy preferences instead if
appropriate. Outbound DNS to the configured resolver must be allowed.

Both resolver modes reject non-public answers to prevent forwarding loops. The
error message points to `cloud_dns`; failure retains the existing local response
behavior. `upstream_dns` still serves the built-in DNS forwarder for other names.
HTTP passthrough still uses the host resolver, so local targets continue to work.
Cloud redirects are not followed.

Cloud requests ask for identity encoding; gzip and both zlib-wrapped and raw
HTTP deflate responses are decoded if the server compresses anyway. Recipe
persistence and the device command-response format are unchanged.

Set `diagnostics_enabled: true` to record a compact local summary of completed
device exchanges in `/data/diagnostics-summary.jsonl`. Each entry contains the
Bridge timestamp, response source and HTTP status, command count, recognized
key numbers, and, for status messages, the screen code and actuator flags.
The recorder stores only these fields. Device IDs, account data, signatures,
recipe contents, headers and raw bodies are excluded.

The file is capped at 1 MiB and is kept across restarts. The local health API
reports `diagnostics_missed` for writes skipped because the writer is busy,
the file is full, or storage is unavailable. To start a fresh capture, stop
the app, archive or remove the summary file, then start the app again.

With `control_enabled: true`, local API clients can POST JSON containing
`device_id` and `action` to `/api/control`. Supported actions:

| Action | Screen transition |
| --- | --- |
| `open_settings` / `close_settings` | 101 ↔ 8101 |
| `open_manual` / `close_manual` | 101 ↔ 4006 |
| `open_recipe_list` / `close_recipe_list` | 101 ↔ 6010 |
| `open_recipe_selection` / `cancel_recipe_selection` | 101 ↔ 2015 |
| `recipe_down` / `recipe_up` | 2015, change highlighted slot |

List navigation uses the device-reported recipe count (one to nine) and
confirms the expected highlighted slot, including wraparound.

The Bridge requires recent status with both actuators off. HTTP 202 means the
action is queued. Only one action can be pending across the Bridge.

The Bridge adds the key once on a fresh matching device poll with the
standard successful acknowledgment, including the local reply when cloud
forwarding is disabled or unavailable. Other cloud responses pass through
as received by the normal forwarding path. GET `/api/control` returns the
latest action's outcome. A later device poll reporting the expected screen
and actuator flags marks it confirmed. An action expires after five seconds
in the queue or becomes unconfirmed after five seconds awaiting telemetry.


### Manual actuator controls

With `control_enabled: true`, the loopback API accepts `heater_off` in manual
mode (4006) without heating permission. `pump_on` and `pump_off` additionally
require `manual_pump_enabled: true`; `heater_on` requires
`allow_remote_heating: true`. Both options default to false. Fresh matching
status and subsequent actuator flags are required; commands are never retried.
Stay near the device and follow Speidel's operating instructions.


### Program controls

The loopback API accepts `select_recipe` from recipe selection, stopping at the
water prompt. It validates the selected slot against field 8's recipe count.
`request_program_pause` is available at 2300 (purging) and 2410 (heating).
`abort_program` is available only from the matching pause dialog. These actions
require `control_enabled`. `resume_program` is limited to the purge pause and
additionally requires both `program_control_enabled: true` (default false) and
`allow_remote_heating: true`. Water confirmation, delayed start, state 2310 and
heating-stage resume are unsupported. Commands are checked again before sending;
a changed dialog cancels the queued command. First Cancel pauses, second Cancel
from the pause dialog ends the program.


### Recipe upload

With `recipe_write_enabled: true` (default false), local API clients can replace
all recipes on the Braumeister without My Speidel, for example when the cloud is
gone or `forward_to_cloud: false`. POST JSON to `/api/recipes`:

```json
{
  "device_id": "<long device ID>",
  "recipes": [
    {"name": "Weizen", "mash_in": 40,
     "rests": [[44, 20], [52, 20], [63, 35], [73, 35], [78, 10]],
     "boil_time": 90, "hops": [90, 15]}
  ]
}
```

- 1 to 9 recipes; they replace **all** recipes on the device, in this order.
- `name`: 1 to 14 characters `A-Z a-z 0-9`, space, `_` or `-` (no umlauts yet).
- `mash_in` and rest temperatures in °C (20–80), converted if the device is set
  to °F. 1 to 5 `rests` as `[temperature, minutes]` (1–180 min).
- `boil_time` 1–180 minutes; up to 6 `hops` in minutes before the end of the boil.

The device must show the main menu with pump and heater off. The Bridge then
replays what My Speidel does: it deletes all recipes (`$d=A`) and writes one slot
per poll (`$rz=…`), each confirmed by the recipe count in the next status and
resent up to three times. GET `/api/recipes` returns `queued`, `sending`,
`confirmed`, `state_changed` (device left the main menu) or `unconfirmed`.

If an upload stops halfway, the device has only the recipes written so far:
simply upload again. The last recipe list the device reported is kept in
`/data/recipes.json` (and in `/api/status`). Nothing is heated or started.
With `forward_to_cloud: true`, My Speidel may later replace the list with the
recipes of your account again.
