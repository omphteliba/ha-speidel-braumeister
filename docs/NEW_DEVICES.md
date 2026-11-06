# Helping with newer Braumeister models

The integration is developed and tested on the first Braumeister generation (WiFi
controller, firmware V1.x, e.g. V1.1.27). Models from about 2021 on use a new
controller (Linux, firmware 0.x–2.x) that talks to a different part of the My Speidel
cloud. We don't own such a device, so we depend on owners to tell us what it sends.

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

If the integration already shows temperature, pump or heater: the values come from the
Cloud API v1.0 timeseries. Their meaning is a best guess from the API documentation,
so please compare them with your device display and say how far they lag behind.

## 3. Optional: record what the My Speidel web interface receives

The Cloud API has no live status. For live data, the newer devices most likely use
MQTT over a WebSocket, which the My Speidel web interface receives as well. A short
recording of that traffic shows us the real format.

In Chrome or Edge, while the Braumeister is switched on:

1. Open the My Speidel web interface, log in and open your Braumeister.
2. Press **F12**, select the **Network** tab and the filter **WS** (WebSocket).
3. Reload the page (F5). A WebSocket connection appears in the list; click it and open
   the **Messages** tab.
4. Let it run for a few minutes, ideally while the device heats or a program runs.
5. Right-click a message → **Copy message** for a few typical messages, or export the
   whole recording with **Export HAR** (the download icon in the Network tab).

**Important:** the first messages of the connection (CONNECT / login) can contain your
login data or a token. **Never post them publicly**, and don't post the HAR file as a
whole in the issue. Copy only status messages that came later, or ask in the issue for
a private way to send the file.

## What happens next

We use your data to add parsing for the new generation, release it, and ask you to test
it. Controlling a newer device (pump, heater, programs) is not planned until its
protocol is understood and tested.
