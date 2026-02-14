# Speidel Braumeister Home Assistant Integration

[![hacs][hacs-badge]][hacs]
[![GitHub Release][release-badge]][release]
[![License][license-badge]][license]

A Home Assistant integration for Speidel Braumeister brewing systems via the My Speidel Cloud API. This integration allows you to monitor your Braumeister brewing process with real-time data and recipe information.

## Features

### Sensors

| Sensor | Description |
|--------|-------------|
| Connection Status | Shows the connection status: `online`, `offline`, or `invalid_uuid` |
| Temperature | Current temperature reading from the Braumeister |
| Target Temperature | The target temperature for the current phase |
| Pump Status | Current pump state (Ein/Aus - German for On/Off) |
| Heating Status | Current heating element state (Ein/Aus) |
| Process Status | Current brewing process status (running, idle, etc.) |
| Current Phase | Current brewing phase (Einmaischen, Rast, Kochen, etc.) |
| Remaining Time | Estimated remaining time for the current phase |
| Brew Name | Name of the current brew/recipe |
| Device Type | Braumeister model (e.g., "Braumeister 20 Liter") |
| Device Mode | Current mode (Automatik, wartet, etc.) |
| Current Step | Full step name (e.g., "Stone IPA – Einmaischen") |
| Brewing Progress | Progress percentage of the current brew |
| Last Online | Last time the device was online |

### Recipe Information

The Brew Name sensor includes additional attributes:
- `recipe_slot` - Which device slot (0-4) the recipe is loaded from
- `recipe_matched` - Whether the recipe was found in your account
- `account_recipe_id` - The account recipe ID if matched
- `recipe_date` - Recipe creation date

### Switches (Future Control)

| Switch | Description |
|--------|-------------|
| Pump | Control the pump on/off |
| Heating | Control the heating element on/off |

> **Note:** Switch entities are currently unavailable as the Speidel Cloud API does not yet support direct control commands.

### Buttons (Future Control)

| Button | Description |
|--------|-------------|
| Start Process | Start a brewing process |
| Stop Process | Stop the current brewing process |
| Pause Process | Pause the current brewing process |
| Next Phase | Skip to the next brewing phase |

> **Note:** Button entities are currently unavailable as the Speidel Cloud API does not yet support direct control commands.

### Translations

The integration includes translations for:
- 🇬🇧 English (default)
- 🇩🇪 German (Deutsch)

Sensor names are automatically displayed in your Home Assistant language.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the "+" button
4. Search for "Speidel Braumeister"
5. Click "Download"
6. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/speidel_braumeister` directory to your Home Assistant `custom_components` folder
2. Restart Home Assistant

## Configuration

### Via UI (Recommended)

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for "Speidel Braumeister"
4. Enter your My Speidel credentials:
   - **Username**: Your My Speidel account username
   - **Password**: Your My Speidel account password
5. Enter your Machine UUID (see below for how to find it)

## Finding Your Machine UUID

The Machine UUID is a unique identifier for your Braumeister device. The Speidel Cloud API uses a combined format.

### Method 1: From the My Speidel Web Interface HTML (Most Reliable)

1. Log in to [My Speidel](https://www.myspeidel.com)
2. Go to your Braumeister's control page
3. Right-click on the page and select "View Page Source" or "Inspect"
4. Search for `data-machine=` in the HTML
5. The full machine identifier is in this attribute

For example, if you find:
```html
<li class="teaser-box-item online" id="device_323" data-machine="0004A30B003D70F4.323" ...>
```

Then your Machine UUID is: **`0004A30B003D70F4.323`** (the full `data-machine` value)

### Method 2: From the URL

1. Log in to [My Speidel](https://www.myspeidel.com)
2. Navigate to your Braumeister's control page
3. Look at the URL in your browser's address bar
4. The number at the end is the short ID

For example:
```
https://www.myspeidel.com/braumeister/control/323
```

The short ID is `323`. **However**, the API may require the full combined format. Use Method 1 to get the full identifier.

### Which UUID Format to Use?

The integration supports multiple UUID formats and will try them automatically:
- **Combined format** (recommended): `0004A30B003D70F4.323`
- **Short ID**: `323`
- **Long UUID**: `0004A30B003D70F4`

**We recommend using the combined format** from the `data-machine` attribute for best results.

## Prerequisites

### My Speidel Account

You need a **My Speidel account** with your Braumeister registered. The integration uses XHR polling (the same method as the web interface) which works for all users without requiring a subscription.

### Device Requirements

- Speidel Braumeister (any model with WiFi capability)
- Device connected to your local WiFi network
- Device registered with My Speidel cloud service

## How It Works

### Data Fetching Priority

The integration uses multiple data sources for maximum reliability:

1. **XHR Polling (Primary)** - Same method used by the My Speidel web interface
2. **Device Info JSON** - Additional metadata (device type, mode, step, progress)
3. **Cloud API (Fallback)** - Historical data (may require subscription)

### XHR Polling

The integration polls the web interface endpoints to get real-time data:

- **Status Endpoint**: `/braumeister/getDeviceStatusControl/{device_id}`
- **Device Info**: `/braumeister/getDeviceStatus/{device_id}` (JSON with metadata)
- **Recipes**: `/braumeister/getDeviceRecipes/{machine_id}`
- **Account Recipes**: `/recipes/index/my_recipes`

### Recipe Matching

The integration automatically matches recipes stored on your Braumeister device (slots 0-4) with recipes in your My Speidel account:

1. **Exact match** - Recipe names match exactly (case-insensitive)
2. **Partial match** - Device recipe name is contained in account recipe name (e.g., "Low Rider Pale" matches "Low Rider Pale Ale")

This allows you to see the account recipe ID, creation date, and style for the currently brewing recipe.

## Automations

### Example: Notification when brew is complete

```yaml
alias: "Brewing Complete"
trigger:
  - platform: state
    entity_id: sensor.braumeister_process_status
    to: "finished"
action:
  - service: notify.mobile_app
    data:
      message: "Your brew '{{ states('sensor.braumeister_brew_name') }}' is complete!"
```

### Example: Temperature alert

```yaml
alias: "Braumeister Temperature Alert"
trigger:
  - platform: numeric_state
    entity_id: sensor.braumeister_temperature
    above: 100
action:
  - service: notify.mobile_app
    data:
      message: "Warning: Braumeister temperature is {{ states('sensor.braumeister_temperature') }}°C"
```

### Example: Track brewing progress

```yaml
alias: "Brewing Progress Update"
trigger:
  - platform: state
    entity_id: sensor.braumeister_current_step
action:
  - service: notify.mobile_app
    data:
      message: >
        Step: {{ states('sensor.braumeister_current_step') }}
        Temperature: {{ states('sensor.braumeister_temperature') }}°C
        Progress: {{ states('sensor.braumeister_brewing_progress') }}%
```

## Dashboard Card Example

Here's an example dashboard card for your Braumeister:

```yaml
type: entities
title: Braumeister
entities:
  - entity: sensor.braumeister_connection_status
    name: Connection
  - entity: sensor.braumeister_brew_name
    name: Brew
  - entity: sensor.braumeister_device_type
    name: Device
  - entity: sensor.braumeister_device_mode
    name: Mode
  - entity: sensor.braumeister_current_step
    name: Step
  - entity: sensor.braumeister_temperature
    name: Temperature
  - entity: sensor.braumeister_target_temperature
    name: Target
  - entity: sensor.braumeister_brewing_progress
    name: Progress
  - entity: sensor.braumeister_remaining_time
    name: Remaining
  - entity: sensor.braumeister_pump_status
    name: Pump
  - entity: sensor.braumeister_heating_status
    name: Heating
```

## Troubleshooting

### Connection Status Shows "invalid_uuid"

This means the Machine UUID you entered is not recognized by the Speidel Cloud API. 

1. Verify the UUID by following the steps in the **Finding Your Machine UUID** section above
2. Make sure you're using the correct account (the same one you see your Braumeister in on the My Speidel website)

### Connection Status Shows "offline"

This means:
- The Braumeister exists in your account but is not currently sending data
- The device may be turned off or not actively brewing
- The device may not be connected to WiFi

Check that:
1. Your Braumeister is powered on
2. The device is connected to WiFi
3. You can see live data in the My Speidel app/website

### Sensors show "Unknown"

If sensors show "Unknown" after setup:
1. Check that your Braumeister is online in the My Speidel app
2. Verify your credentials are correct
3. Check the Home Assistant logs for errors
4. Try reloading the integration from Settings > Devices & Services

## Debug Logging

To enable debug logging for this integration, add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.speidel_braumeister: debug
```

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting a pull request.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/omphteliba/ha-speidel-braumeister/issues)
- **Discussions**: [GitHub Discussions](https://github.com/omphteliba/ha-speidel-braumeister/discussions)

## Credits

- Speidel for the Braumeister brewing system and Cloud API
- The Home Assistant community for inspiration and support

[hacs]: https://github.com/custom-components/hacs
[hacs-badge]: https://img.shields.io/badge/HACS-Default-blue.svg
[release]: https://github.com/omphteliba/ha-speidel-braumeister/releases
[release-badge]: https://img.shields.io/github/v/release/omphteliba/ha-speidel-braumeister
[license]: LICENSE
[license-badge]: https://img.shields.io/github/license/omphteliba/ha-speidel-braumeister
