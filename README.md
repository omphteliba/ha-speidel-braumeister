# Home Assistant Speidel Braumeister Integration

This integration allows you to monitor your Speidel Braumeister brewing system within Home Assistant.

## Installation

1. **Install HACS (Home Assistant Community Store):**
   - [Link to HACS installation instructions](https://github.com/hacs/integration/blob/master/docs/installation.md)
2. **Add the repository to HACS:**
   - In Home Assistant, go to **Settings > Integrations > Add integration**.
   - Click **Custom integrations** and select **Add from repository**.
   - Enter the URL of your GitHub repository: https://github.com/omphteliba/ha-speidel-braumeister .
3. **Install the integration:**
   - Click **Install** in HACS.

## Configuration

1. **Enter your Speidel credentials:**
   - In Home Assistant, go to **Settings > Integrations** and click on the **Speidel Braumeister** integration.
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
