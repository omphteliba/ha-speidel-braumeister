# Helping with newer Braumeister models

There is no official overview of Braumeister models, controllers and firmware
versions, so we can only say what has been tested:

- **Works:** Braumeister 20 L with WiFi module and Braumeister 20 L PLUS, both with
  firmware `V1.1.27 Sep 12 2018`. These devices talk to `api2.myspeidel.com`.
- **Does not work yet:** Braumeister PLUS 50 L with firmware `1.8.3-rc.0` (issue #7).
  The controller's connection to the cloud is still an open question.
- **Everything else:** unknown.

If the integration shows no data for your Braumeister, the steps below help us find out
why. We don't own such a device, so we depend on owners to tell us what it sends.

None of the steps below sends anything to your Braumeister. They only read.

## 1. Install the integration and download the diagnostics

1. Install the integration (HACS or manually) and add your Braumeister as described
   in the [README](../README.md).
2. Enable debug logging for a few minutes (see "Debug Logging" in the README), then
   restart Home Assistant. If possible, have the Braumeister switched on, ideally
   during a brew or in manual mode.
3. Go to **Settings → Devices & services → Speidel Braumeister**, open the ⋮ menu of
   the entry and choose **Download diagnostics**.

The file contains which data source answered, the device type and firmware, and the
answers of the My Speidel Cloud API v1.0 (process, phase, sensor and actor
timeseries). Your username, password, machine and device IDs, tokens and signatures
are removed automatically. Please still have a quick look before posting it.

## 2. Open an issue

Open a [new issue with the "Newer Braumeister model" template](https://github.com/omphteliba/ha-speidel-braumeister/issues/new?template=new_device.yml)
and attach the diagnostics file. The template asks for the model, firmware, whether
you have a My Speidel subscription, and what the integration currently shows.

Alongside the export, note the time and time zone, the temperature and the brew
step visible on the appliance. If a step or temperature changes during normal
operation, a second observation helps us measure how far the cloud data lags.

When reviewing a report, check `device_type`, `firmware` and `data_source` first.
The diagnostics export requests `cloud_api.timeseries` even when another source
supplies the HA entities. For each available process, phase, sensor or actor
response, distinguish an error from a successful empty result and from actual
samples. Compare the latest sample time and value with the owner's observation.
Record conclusions for the specific model and firmware tested.

## 3. Optional: record what the My Speidel web interface receives

The documented Cloud API v1.0 exposes timeseries. Browser observations can
help identify how My Speidel displays live values. A WebSocket seen here
establishes the browser-to-cloud connection only. Identifying the appliance's
own transport would require separate device-side evidence or vendor documentation.

In Chrome or Edge, while the Braumeister is switched on:

1. Open the My Speidel web interface, log in and open your Braumeister.
2. Press **F12**, select the **Network** tab and the filter **WS** (WebSocket).
3. Reload the page (F5). If a WebSocket connection appears, open its **Messages**
   tab. If none appears, report that observation.
4. Let it run for a few minutes, ideally while the device heats or a program runs.
5. Right-click a message → **Copy message** for a few typical messages, or export the
   whole recording with **Export HAR** (the download icon in the Network tab).

**Important:** the first messages of the connection (CONNECT / login) can contain your
login data or a token. **Never post them publicly**, and don't post the HAR file as a
whole in the issue. Copy only status messages that came later, or ask in the issue for
a private way to send the file.

## What happens next

We use your data to add support for your device, release it, and ask you to test
it. Controlling a newer device (pump, heater, programs) is not planned until its
protocol is understood and tested.
