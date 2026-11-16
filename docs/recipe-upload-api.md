# Generic recipe upload API

Recipe applications, scripts and HA automations can submit controller programs
without depending on a particular recipe manager. The Bridge owns validation and
device safety checks. The integration exposes HA response actions; external
clients use HA authentication rather than exposing the Bridge on the LAN.

## Home Assistant actions

| Action (domain `speidel_braumeister`) | Data | Response |
| --- | --- | --- |
| `recipe_upload_readiness` | optional `config_entry_id` | connection, state, readiness and blocking reasons |
| `start_recipe_upload` | `recipes`, optional `config_entry_id` | `job_id`, result and progress |
| `recipe_upload_status` | `job_id`, optional `config_entry_id` | the specific job and available content verification |

The existing blocking `upload_recipes` action remains available. The new actions
require the matching Bridge update. None starts a brewing program.

External clients POST to
`/api/services/speidel_braumeister/<action>?return_response` with
`Authorization: Bearer <HA access token>` and `Content-Type: application/json`.
Read the result from `service_response`. Use HTTPS for remote access and never
embed tokens in recipes. See the [HA REST contract](https://developers.home-assistant.io/docs/api/rest/).

Example readiness request body: `{}` (or `{"config_entry_id":"..."}`).
Example upload body:

```json
{"recipes":[{"name":"Weizen","mash_in_temperature":40,
"rests":[{"temperature":63,"minutes":35},{"temperature":78,"minutes":10}],
"boil_minutes":60,"boil_temperature":100,"hop_additions":[60,15]}]}
```

Example status body: `{"job_id":"<returned ID>"}`.
The same calls work in HA scripts with `response_variable`:

```yaml
sequence:
  - action: speidel_braumeister.recipe_upload_readiness
    response_variable: readiness
  - condition: template
    value_template: "{{ readiness.ready_for_upload }}"
  - action: speidel_braumeister.start_recipe_upload
    data:
      recipes:
        - name: Weizen
          mash_in_temperature: 40
          rests: [{temperature: 63, minutes: 35}]
          boil_minutes: 60
          hop_additions: [60, 15]
    response_variable: upload
  - action: speidel_braumeister.recipe_upload_status
    data:
      job_id: "{{ upload.job_id }}"
    response_variable: progress
```

The last call reads progress once; clients should poll at about two seconds while
`result` is `queued` or `sending`. A successful readiness response is advisory:
the Bridge checks again on POST and on each device poll before writing.

## Bridge contract

Loopback only, no browser Origin header:

* `GET /api/recipes/readiness?device_id=...` works even if uploads are disabled.
* `POST /api/recipes`: existing `{device_id, recipes}` body, now returns a job ID.
* `GET /api/recipes?job_id=...`: specific job; 404 for unknown/evicted jobs.
* `GET /api/recipes`: unchanged legacy response for the last job.

Readiness includes `connected`, `status_age_seconds`, `main_menu`, `pump_on`,
`heater_on`, `upload_enabled`, `ready_for_upload`, `blocking_reasons` and
`replaces_all_recipes`. Unknown/stale states return null for actuator/menu values.
Connected means a recent device message, not proof of electrical power status.
The freshness threshold is the same CONTROL_TIMEOUT used for upload acceptance.
Blocking codes: `upload_disabled`, `device_status_stale`,
`device_status_unreadable`, `device_not_idle`, `busy`.

Job results: `queued`, `sending`, `confirmed`, `state_changed`, `unconfirmed`.
`written` counts slots acknowledged by the device's recipe-count field.
`confirmed` therefore means count acknowledgment, not verified recipe content.
`content_verification` is `not_available` until the first recipe-list message
received after confirmation, then `matched` or `mismatch`. Comparison uses the
exact encoded device program, including truncated names and Fahrenheit conversion.
There is no new command forcing readback: a device that sends no fresh list stays
`not_available`. A matching result describes that readback, not future cloud changes.

The last 32 jobs are retained in memory, lost on Bridge restart. Jobs are not
idempotency keys. If the POST response is lost, do not repeat it automatically.
If a known job disappears, report an unknown outcome rather than success.

Uploads require `recipe_write_enabled: true`, a fresh readable device status,
main menu and pump/heater off. The complete list of 1–9 recipes replaces all
device slots; there is no append or rollback. An interrupted write can leave a
partial list. Cloud forwarding can subsequently overwrite uploaded recipes.
See [Bridge recipe limits](../braumeister_bridge/DOCS.md#recipe-upload).

## Integration boundaries

A producer converts its source recipe to this device-program format. Ingredients,
stock, fermentation schedules and telemetry are not upload fields. Producers must
handle missing mash-in temperature, units, fractional times, unsupported rests,
flameout additions and name shortening explicitly rather than inventing values.
