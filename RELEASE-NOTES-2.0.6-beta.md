# 2.0.6-beta — local Braumeister Bridge with AdGuard support

- Import the upstream Bridge and device protocol parser from
  omphteliba/ha-speidel-braumeister commit dda46326cec491567449a7f907399eb76d4a1542.
  Original code and attribution remain under the repository MIT license.
- Prefer fresh local bridge telemetry, checked every second once detected.
- Keep adaptive cloud polling and Retry-After/backoff; cloud cooldowns never
  prevent local recovery. Missing bridge data is not reported as fresh.
- Add a dedicated configurable cloud DNS resolver to bypass AdGuard rewrites;
  reject non-public cloud DNS answers to prevent forwarding loops.
- Preserve device request body, Host and Authorization, and return cloud
  response bytes/status/headers without following redirects.
- Default the app's DNS port to zero for existing AdGuard installations.
- Add data_source and bridge_age attributes to the connection sensor.

Integration and Bridge are separate installs. See docs/bridge-adguard.md.
Detailed display messages and matching UI buttons are explicitly a later step.
Local mode currently shows a numeric status code rather than cloud step text.
The upstream parser also supplies timed-step remaining time and program progress.
The cloud path keeps the fork's existing parsing behavior for now.

Offline automated tests use loopback servers and synthetic DNS answers.
Real Raspberry Pi app installation, Docker image build and physical device
forwarding still require validation. No live device commands were issued.
