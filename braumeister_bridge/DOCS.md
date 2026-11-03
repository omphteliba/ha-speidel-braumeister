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

List navigation uses the device-reported recipe count (one to five) and
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
