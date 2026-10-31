# Braumeister Device ↔ Cloud Protocol

Reverse-engineered from a packet capture of a Braumeister talking to the My Speidel
cloud (Fritzbox packet capture, 2026-10-30, ~5.5 minutes, 281 requests).
Everything marked *hypothesis* is inferred from a single capture and needs confirmation.

Device used for the capture:

| Property | Value |
|---|---|
| Firmware | `V1.1.27 Sep 12 2018` |
| WLAN module | Redpine Signals (MAC OUI `00:23:A7`) |
| Local services | none — all 65535 TCP ports closed/filtered, device is client-only |
| Power saving | WLAN drops off the network intermittently; first ping after idle takes ~250 ms |

## Transport

- **Plain HTTP, no TLS**: `POST http://api2.myspeidel.com/braumeister/connect` (port 80).
- One short-lived TCP connection per request.
- Interval: ~1.2 s on average, up to ~5 s.
- Request body is URL-encoded (`%20` for spaces, etc.); the first `=` separates the
  message type from the payload.
- No DNS query was seen during the capture, so it is still open whether the device
  resolves `api2.myspeidel.com` or uses a hard-coded IP. Capture a device power-cycle
  to find out — this decides whether a DNS override can redirect it.

## Device → Server

All messages share the same envelope:

```
<type>=<firmware>;<device_id>;<unix_time>;<payload>;<constant>;<signature>
```

| Field | Example | Notes |
|---|---|---|
| `firmware` | `V1.1.27 Sep 12 2018` | |
| `device_id` | `1234567890ABCDEF` | 16 hex chars, the "long UUID" |
| `unix_time` | `1793383969` | Device clock, seconds since epoch (UTC). Previously misnamed `session_id` in the code |
| `payload` | see below | |
| `constant` | 8 hex chars | Same value in every message of one device |
| `signature` | 8 hex chars | Changes per message. Not CRC32/Adler32/MD5/SHA1/SHA256 of any obvious substring — probably keyed. A local server does not need to verify it |

### `bm_stat` — status (sent continuously)

Payload is 19 fields separated by `X`:

```
0X18:12XCX101X-1000X 24.5X4800X82X1X0X0X0X0XEMSRXphX000X0X0X0
```

| Pos | Observed values | Meaning |
|---|---|---|
| 0 | `0` | Unknown (always `0`) |
| 1 | `18:12` | Device clock, HH:MM |
| 2 | `C` | Temperature unit (Celsius) |
| 3 | `101`, `2xxx`, `3xxx`, `4006`, `4007`, `6010` | **State / screen code** (see below) |
| 4 | `-1000`, `0`, `380`…`1030` | **Target temperature × 10**; `-1000` = none, `0` between steps (shown as 0 °C, like MySpeidel's web interface). In the main menu (state `101`) it can still hold the last program's target, so the parser ignores it there |
| 5 | ` 24.5` | **Current temperature** in °C (leading space, 0.5 °C steps) |
| 6 | `4800`, `1200`, `60`, `0` | **Duration of the current program step in seconds**: rest (`60` for a 1-min rest), boil (`1200` for 20 min). Outside timed steps it keeps the boil time of the selected recipe. Remaining time = field 6 − field 7 during `2820` (rest) and `3070` (boil) |
| 7 | `0`…`167` | **Seconds since the current state was entered**, resets on state change |
| 8 | `0`…`5` | *Hypothesis:* number of recipe slots synced. Dropped to 0 after `$d=A`, then counted up by one per `$rz` |
| 9 | `0`…`4` | **Recipe slot of the running program** (`0` for Weizen, `2` for the test recipe). Briefly `4` after entering manual mode, so only meaningful during a program |
| 10 | `0`, `5` | Unknown; became `5` at rest end and stayed until the end |
| 11 | `0`, `-1` | *Hypothesis:* hop addition state; changed from `0` to `-1` at the hop addition 10 min before the end of the boil |
| 12 | `0`…`318` | Unknown, counts up during a program (about 3 per minute while boiling) |
| 13 | `EMSR`, `APHT`, `ADUS`, `A000`, `A00F`, `A00S` | Screen/message code (see below) |
| 14 | `ph`, `Ph`, `pH`, `PH`, `qh`, `qH`, `Pi`, `pi` | **Actuator flags**, as read by MySpeidel's own web display (`parseStatus`/`updateScreen` in `bm_controll.min.js`): 1st char pump, 2nd char heater. `P`/`H` = active, `q`/`i` = shown as inactive, `p`/`h` = unmarked. The parser maps `q`/`i` to off. `q` appears during the boil, `i` near the target temperature |
| 15 | `000`, `010`, `0D0`, `00T`, `120` | **Alarm indicator** (middle character): `1` = alarm (mash-in temperature reached, rest end, brew finished), `D` = remove lid (from 99 °C while heating to boil). `00T` while editing the manual-mode target temperature, `120` together with `A00F` |
| 16–18 | `0` | Unknown |

#### State codes (field 3) — *hypotheses*

| Code | Field 13 | Observed context |
|---|---|---|
| `101` | `EMSR` | Main menu / idle |
| `4006` | `APHT` | Manual mode, target 38.0 °C, pump toggled here |
| `4007` | `ADUS` | Manual mode, editing target temperature (38.0 → 39.0) |
| `6010` | `ADUS` | Some sub-menu, entered with `$k=4`, left with `$k=1` |
| `2300` | `A000` | Program started, heating to mash-in (target 40.0 °C), pump cycling |
| `2301` | `A000` | Program, briefly before returning to 101 |
| `2310` | `A000` | Alternates with 2300 (*hypothesis:* pump pause) |
| `2410` | `A000` | Heating to mash-in (pump + heater on) |
| `2510` | `A00S` | **Alarm:** mash-in temperature reached; web step text "… – Einmaischen Temp. erreicht" |
| `2610` | `A00S` | Mash-in temperature reached, waiting for the user to add the malt (seen without beep) |
| `2810` | `A000` | Heating to the next rest (pump + heater on) |
| `2820` | `A00S` | Holding a rest |
| `2930`, `2960` | `A00S` | After rest end, waiting for the user (*hypothesis:* remove malt pipe / start boil). Target `0`, pump and heater off, no beep. `2930` followed `2910` once the alarm was confirmed |
| `2030` | `ADUS` | Program start screen ("Automatik – <recipe> starten") |
| `2910` | `A00S` | **Alarm:** rest end reached ("Rastende erreicht"), field 15 `010` |
| `3010` | `A00S` | Heating to boil (target 103.0 °C). From 99 °C field 15 is `0D0` = **alarm "Deckel entfernen"** |
| `3070` | `A00S` | Boiling; field 7 counts the boil time, field 11 changed from `0` to `-1` at a hop addition |
| `3450` | `A00S` | **Alarm:** brew finished ("Brauvorgang beendet"), pump and heater off, field 15 `010` |

The thousands digit is the program phase: `2xxx` = mashing, `3xxx` = boiling; both count as a
running program. An alarm is active while field 15 signals a beep (`1`/`2`) or the lid (`D`), as in
MySpeidel's own display; `device_protocol.ALARM_STATES` only names it by state code. Codes from
`2410` on come from two live brews where the web interface was polled every 30 s, so short
states can be missed (e.g. the moment of an abort).

After an abort the device goes straight back to `101`. Hop additions did not show up as a
state or alarm indicator; the beep is probably shorter than the 30 s polling interval.

The heater flag is often `i` near the target temperature and while holding a rest; MySpeidel's display
shows it as inactive. Field 13 `A00S` is not an alarm marker: it holds the labels of the display buttons.

### `rz` — recipe slots (sent on connect / after changes)

The payload starts with the number of slots, then one line per slot (separated by `\r\n`):

```
rz=<fw>;<id>;<time>;5
0X40X44X20X52X20X63X35X73X35X78X10X90X103X90X15X0X0X0X0.Weizen
1X55X55X10X63X45X72X25X78X5X0X0X70X103X60X10X10X0X0X0.Belgisches Gol
...
4X40X40X5X52X20X63X20X73X35X78X20X80X103X60X20X10X0X0X0.NEIPA Nectaron;<constant>;<signature>
```

Each slot line has 20 `X`-separated numbers followed by `.` and the name:

| Pos | Example (Weizen) | Meaning |
|---|---|---|
| 0 | `0` | Slot number (0–4) |
| 1 | `40` | Mash-in temperature °C |
| 2–11 | `44 20 52 20 63 35 73 35 78 10` | 5 rests as (temperature °C, minutes); unused = `0 0` (or `40 0` on the device) |
| 12 | `90` | Boil time, minutes |
| 13 | `103` | *Hypothesis:* boil temperature °C (always 103) |
| 14–19 | `90 15 0 0 0 0` | Hop additions, minutes before end of boil; `0` = unused |

The name is truncated to 14 characters (`Belgisches Gol…`).

## Server → Device

Every request gets an HTTP response with this body:

```
Start\r\n
[$<command>\r\n]
OK\r\n
Done
```

There is no signature, so the device appears to accept unsigned commands.
At most one command per response was observed.

| Command | Observed effect — *hypotheses* |
|---|---|
| `$k=1` | Key press "back": 4006 → 101, 6010 → 101 |
| `$k=2` | Key press "enter/select": 101 → 4006 (manual mode); inside 4006 it toggled the pump |
| `$k=4` | Key press: 101 → 6010 |
| `$d=A` | *Hypothesis:* delete/reset all recipe slots — field 8 dropped to 0 and was followed by `$rz` for all 5 slots |
| `$rz=<slot line>` | Write one recipe slot, same format as the `rz` lines above. The device reports it back in its next `rz` message |

What a `$k` key press does depends on the screen the device currently shows (field 3).

### Security implications

- Device ↔ cloud traffic is **plain HTTP**: status, recipes and commands can be read by anyone
  on the network path.
- Server responses carry **no signature**. Whoever can answer the device's requests instead of
  the real server (DNS spoofing, ARP spoofing, a compromised router) can send it commands,
  including key presses that start a program or switch on the heater.
- The signature on the device's own messages does not protect the device, because the device
  never checks anything coming back.
- Only Speidel can fix this (TLS with certificate validation, signed responses).

## Relation to the web interface XHR string

The string returned by the My Speidel XHR endpoint is the device's `bm_stat` message,
passed through unchanged:
`firmware;device_id;unix_time;payload;constant;signature`.

It is parsed by `custom_components/speidel_braumeister/device_protocol.py`.
Earlier versions misread it: they took remaining time from pos 6 (a constant, so it always
showed 80 min and "running") and pump/heating from bits of pos 7/8 (a seconds counter and
the recipe count). They also took the recipe slot from field 0 instead of field 9.

### Request and response details

The device sends `Content-Length:` without a space, a static `Authorization: Basic …` header,
`User-Agent: Mozilla/4.0` and `Connection: close`; the body ends with `\r\n `.
The server answers `200`, `Transfer-Encoding: chunked`, `Content-Type: text/plain; charset=UTF-8`,
body `Start\r\n[$command\r\n]OK\r\nDone\r\n`.

## Local integration path

Because the protocol is plain HTTP with unsigned server responses, Home Assistant can
take the cloud's place:

1. Redirect `api2.myspeidel.com` to a local endpoint (DNS override; the device uses DNS, see below).
2. Answer `POST /braumeister/connect` with `Start\r\nOK\r\nDone` and parse `bm_stat`/`rz`.
3. Optionally forward requests to the real cloud (proxy mode) to keep the app working.

This is implemented by the **Braumeister Bridge** app in `braumeister_bridge/` (see its
`DOCS.md`). The Braumeister's WiFi settings allow a manual DNS server, so only the
Braumeister needs to use the app's DNS server.

## Firmware analysis (public updater package)

Source: `BraumeisterSoftwareUpdater-1.1.27-120918.zip` from the official
[download page](https://www.speidels-braumeister.de/en/service/downloads.html). It contains
the controller firmware `BrewControl-1-1-26.hex` and `BrewControl-1-1-27.hex`, a
`WiFiUpdater.hex` and the flashing tools. The controller is an Atmel AVR (`AVROSP.exe` is
Atmel's programmer). Only the readable strings were examined; nothing was executed or flashed.

- **The device uses DNS (verified).** Both versions contain the Redpine WiFi module commands
  `dnsget=` / `dnsserver=`, the hostnames are stored as text (`api2.myspeidel.com`,
  `firmware.myspeidel.com`), and the server IP does not appear anywhere in the firmware.
  A capture of a power cycle confirmed it: DHCP Discover/Request → ARP for the gateway →
  `A api2.myspeidel.com` to the DNS server from DHCP (the router) → answer `79.99.80.214`,
  TTL 7200 s → first `POST /braumeister/connect` 0.5 s later. The device resolves only
  once when it connects, which is why the earlier capture of a running device showed no
  DNS traffic. A DNS override therefore takes effect after the next power cycle (whether it
  re-resolves after the TTL expires is unknown).
- **Cloud endpoints (1.1.27):** `POST /braumeister/connect` on `api2.myspeidel.com`, firmware
  check `GET /version.txt` and `GET /getfw.php?` on `firmware.myspeidel.com` / `api2.myspeidel.com`.
  1.1.26 used `gaermeister.myspeidel.com` for the firmware check. 1.1.27 added the e-mail
  registration (`Enter Mail:`, `Register`).
- **Local web server:** both versions contain an HTTP server (`ltcp=` = listening TCP socket,
  `HTTP/1.1 200 OK`, `404 Not found`) with these paths:
  `/index.html`, `/bm.html`, `/bm.txt`, `/ui.txt`, `/rz.txt`, `/vs.txt`, plus `image/bmp`
  output (probably a screenshot of the display).
  With 1.1.26 this server was reachable in the local network. The third-party tool
  [speidel-ui](https://gitlab.com/vegard.vesterheim/speidel-ui) uses it:
  - `GET /bm.txt`: status
  - `GET /rz.txt`: list recipes (same format as the `rz` message)
  - `POST /rz.txt` with body `rz=<slot line>`: write a recipe
  - `GET /rz.txt?d=<slot>`: delete a recipe

  With 1.1.27 no TCP port was open on the test device, although the code is still present.
  Its author reports that local access stopped working with 1.1.27. Whether it can be
  re-enabled by a setting is unknown (would need disassembly).
- **Display texts** that match the program steps and alarms: `Wasser eingefüllt?`,
  `Malz eingefüllt?`, `Rastende erreicht`, `Malzrohr entnehmen!`, `Start Hopfenkochen?`,
  `Hopfen zugeben`, `Deckel entfernen`, `Jetzt Whirlpool...`, `Brauvorgang beendet`, `Prost!`,
  `Abbruch`, `Pumpenpause` (supports the 2310 = pump pause hypothesis) and
  `Pumpe wird entlüftet` (supports `q` in the actuator flags = pump venting).

## My Speidel Cloud API (api.cloud.myspeidel.com)

Documented at <https://api.cloud.myspeidel.com/> (OpenAPI 3.0, v1.0; the
v2.0-test spec links return "Cannot GET"). Probed 2026-10-30 with an account that
has a subscription and one Braumeister of the generation described above.

- The server validates every request against the OpenAPI spec. Undocumented
  paths (`/account/machines`, `/machine/{uuid}/status`, which older versions of
  `api.py` used) return `404` just like made-up paths.
- Login: `POST /v1.0/auth/authentication` with `username` and `pass` → bearer token.
- Only timeseries are available (`process`, `phase`, `sensor`, `actor`). There is no
  live-status endpoint and no control endpoint.
- Query values must be URL-encoded (`:` → `%3A`), otherwise `400`.
  `actor` rejects `granularity` (`400 Unknown query parameter`), contrary to the spec.
- Machine IDs: the short numeric ID (the part after the `.`) is accepted. The
  16-hex device ID and the combined form return `404`; IDs longer than 64 characters return `400`.
- **All timeseries were empty** (`200 []`), including the last 24 h, although the
  device had run manual mode and an automatic program a few hours earlier.
  `/account/timeseries/process` is empty too. So data from this device generation
  (firmware V1.x, `api2.myspeidel.com`) does not reach the cloud API.
- The public `/v1.0/firmware` list only contains Linux images for i.MX6UL
  (`image-speidel-swu-imx6ul-var`), i.e. the newer device generation. The cloud API
  is most likely only useful for those devices. This is untested — it needs an
  account that owns such a device.

## Open questions

- Does the device resolve the hostname via DNS or use a hard-coded IP?
- Meaning of fields 0, 6, 9–12, 15–18 and of more state codes (rests, boil, hop alarms, end).
  This needs a capture of a full brew.
- Full `$k` key mapping, and the meaning of `$d=A`.
- Behaviour during an alarm (e.g. hop addition, "add malt pipe").
