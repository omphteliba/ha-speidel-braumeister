# Cloud HTTP cooldown

Normal polling remains at the upstream 30-second default. This change adds no
active/idle polling modes and does not accelerate requests.

All web, legacy XHR and cloud API HTTP paths (including login, recipe metadata
and diagnostics) use a shared request policy within an integration entry. HTTP
429 and 5xx stop the refresh before endpoint fallback or re-login. Retry-After
accepts delay-seconds and timezone-aware HTTP dates. Invalid/missing headers use
30, 60, 120, 240, then 300 seconds of exponential backoff. A longer server delay
is never shortened. Transport errors stop the current refresh without fallback
or re-login, but neither start nor escalate a cooldown. The next normal polling
tick can retry. Existing unavailable-state behavior is retained; this change
does not present stale cloud values as fresh readings. Success resets the
failure counter. Cancellation is propagated without starting a cooldown.

Cooldowns use a monotonic deadline. Attempts during the pause make no HTTP
request and do not extend it. Existing coordinator ticks may resume later than
the deadline, never earlier. Setup retries retain the policy for that entry.
Fresh local bridge data still works when optional cloud metadata is paused.
The bridge's device-to-cloud forwarding path is unchanged by this PR.
