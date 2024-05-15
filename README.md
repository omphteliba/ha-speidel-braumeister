
![ha-speidel-braumeister_header](https://github.com/omphteliba/ha-speidel-braumeister/assets/196336/e0a90ea2-9633-41e9-b39c-fa792d79a1a9)

# Home Assistant Speidel Braumeister Integration

This integration allows you to monitor your Speidel Braumeister brewing system within Home Assistant.

## Add Repository

1. **Install HACS (Home Assistant Community Store):**
   - [Link to HACS installation instructions](https://github.com/hacs/integration/blob/master/docs/installation.md)
2. **Add the repository to HACS:**
   - In Home Assistant, go to **HACS > Integrations > Three dots**.
   - Click **Custom repositories** and select **Add from repository**.
   - Enter the URL of your GitHub repository: https://github.com/omphteliba/ha-speidel-braumeister .
   - Choose **Integration** from **Category**
   - Click **ADD** in HACS.

## Install Integration

1. **Add Integration:**
   - In Home Assistant, go to **Settings > Devices & Services** and click on **ADD INTEGRATIONS**.
   - Search for **Speidel** and click on **Speidel Braumeister**.
   - Enter your Speidel username and password in the provided fields.
   - Click **Submit**.

## Features

- Provides sensors for:
   - **sensor.speidel_braumeister_current_temperature:** Current temperature in °C.
   - **sensor.speidel_braumeister_target_temperature:** Target temperature in °C.
   - **sensor.speidel_braumeister_current_phase:** Current brewing phase.
   - **sensor.speidel_braumeister_current_time:** Current time.
   - **sensor.speidel_braumeister_remaining_time:** Remaining time in minutes.

## Requirements

- A Speidel Braumeister brewing system
- A Speidel account

## Notes

- This integration is under development. Please report any issues or feature requests on the GitHub repository.
