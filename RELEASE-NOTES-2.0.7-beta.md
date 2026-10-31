# 2.0.7-beta — Local brewing display messages

- Replace numeric bridge screen codes with German brewing status messages.
- Include water/malt confirmations, pump venting and pauses, heating, rests,
  hop additions, completion, lid prompts and interrupted operation.
- Preserve unknown codes and expose phase/interrupt/rest/hop attributes.
- Uses the existing current_step entity; no dashboard JavaScript update needed.
- Cloud fallback display logic is unchanged. Bridge remains at 0.1.4.

Validation: 150 tests and 297 subtests passed. State mappings follow the
captured firmware 1.1.27 portal logic; real brewing screen validation pending.
