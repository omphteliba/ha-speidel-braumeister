# Braumeister Bridge with AdGuard Home (fork)

Base: fork perf/adaptive-polling, 2.0.5-beta (23abdc7).
Upstream app/protocol source: dda46326cec491567449a7f907399eb76d4a1542.
This is a port of the bridge feature, not a complete merge of upstream main.
The existing cloud polling, options and server protection are retained.

## Two installations

1. Publish/install integration prerelease 2.0.6-beta through HACS, restart HA.
2. Install the Bridge app separately. This patch does not publish the feature
   branch as the app store's default branch.

For testing on HA OS, copy this repository's `braumeister_bridge` directory into
`/addons/braumeister_bridge` on the HA host (the Samba `addons` share, NOT
`/config/custom_components` and NOT `www`). In Settings > Apps > App store,
reload/check for updates and install **Braumeister Bridge** under local apps.
The local app build installs aiohttp and aiodns. Start it with watchdog/autostart
as desired. No app is installed merely by downloading the HACS integration.

## Configuration for AdGuard

```yaml
bridge_ip: ""
cloud_host: api2.myspeidel.com
forward_to_cloud: true
cloud_dns:
  - 1.1.1.1
  - 1.0.0.1
upstream_dns: ""
dns_port: 0
http_port: 80
passthrough_url: ""
api_port: 8642
log_level: info
```

AdGuard DNS rewrite: `api2.myspeidel.com` -> the LAN IPv4 address of the HA host.
The Braumeister must use AdGuard for DNS and be able to reach that IP on TCP 80.
If it is on guest WiFi, client/LAN isolation can block that route.
Reconnect/restart the Braumeister after changing DNS, when no brew is running.

`cloud_dns` is used ONLY for the bridge's outbound cloud connections. It must
point to DNS servers without the local rewrite. The default Cloudflare DNS
servers need outbound DNS access; replace them with another reachable resolver
without the rewrite if your network blocks them. Public destination addresses
are enforced. Never point cloud_dns at the same rewriting AdGuard service.
`upstream_dns` controls the optional built-in DNS forwarder, not cloud forwarding.
With dns_port=0 the bridge does not bind port 53; AdGuard keeps that port.

TCP 80 must be free on the HA host. If another service uses it, inspect that
service first. Move it only deliberately and configure passthrough_url if needed;
do not blindly change AdGuard/HA management ports. API 8642 binds loopback only.
No internet port forwarding is needed.

## Data flow and fallback

Device -> AdGuard-resolved HA IP:80 -> Bridge -> real api2.myspeidel.com:80.
The bridge records telemetry before forwarding and relays cloud response bytes
(including any cloud-provided device commands) back to the device. It does not
originate new control commands. On network failure it returns the upstream
bridge's local OK response; cloud control then cannot work. A received HTTP
error status is relayed rather than falsely treated as a successful cloud reply.

HA reads 127.0.0.1:8642/api/status. Bridge data must match the device and be no
older than 10 seconds. Once found, HA checks it every second. Missing/stale data
falls back to the existing cloud cadence; it does not cause cloud requests every
second. During a cloud cooldown HA continues checking locally. Before the first
bridge detection, discovery normally follows the configured cloud interval;
during errors local probes run at most every 10 seconds.

A fresh bridge response does not clear the cloud server's Retry-After deadline.
An existing configured integration can start with fresh local data if cloud
login fails. Initial creation of an account/device configuration still uses the
existing cloud config flow. An unavailable bridge plus unavailable cloud will
make entities unavailable. Short alarms can still fall between local reads.

The connection sensor has `data_source: bridge` and `bridge_age` attributes.
Detailed localized display status is not part of this patch: local current_step
shows `Statuscode N`. Recipe names depend on the device having sent its `rz`
message; temperature/P/H do not require it. No repeated cloud metadata lookup
is performed while local telemetry is fresh.

## Checks

- Confirm AdGuard resolves the device hostname to HA, and the Bridge log receives
  bm_stat messages. Confirm data_source is bridge in HA.
- Confirm MySpeidel still receives changing readings and last_response_source
  is cloud in the local bridge API. A local source means cloud forwarding failed.
- Stop the app: local data must expire and the integration should fall back.
- Restore the original DNS resolution before stopping/removing the bridge for
  rollback, then reconnect the device. Otherwise it keeps contacting HA:80.

Run tests in VS Code:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements_test.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Publish a new 2.0.6-beta prerelease after committing. Never move an existing tag.
