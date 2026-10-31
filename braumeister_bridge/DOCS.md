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

In both setups, cloud forwarding resolves through `cloud_dns` (default
`1.1.1.1`, `1.0.0.1`) rather than the host resolver. Allow outbound DNS to these
resolvers, or configure reachable resolvers without the local rewrite. Non-public
answers are rejected to prevent a forwarding loop; failure retains the existing
local response behavior. `upstream_dns` still serves the built-in DNS forwarder
for other names. HTTP passthrough still uses the host resolver, so local targets
continue to work. Cloud redirects are not followed.

Cloud requests ask for identity encoding; gzip and both zlib-wrapped and raw
HTTP deflate responses are decoded if the server compresses anyway. Recipe
persistence and the device command-response format are unchanged.
