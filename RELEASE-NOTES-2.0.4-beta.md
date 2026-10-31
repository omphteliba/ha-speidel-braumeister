# 2.0.4-beta — adaptive polling hardware test

Test release from `perf/adaptive-polling` in the DanielP-1337 fork.

- Correct pump/heating status decoding from XHR field 14 (PR #8).
- Adaptive polling: default 30 seconds offline, 10 seconds online/idle, and 5 seconds during brewing or manual operation; configurable down to 3 seconds for active polling.
- Apply saved interval options correctly.
- Throttle device metadata and recipe requests.
- Decode fast alarm flags and hop-addition dialogs; expire stale MQTT data so XHR polling can resume.

Validation: 17 offline regression tests passed for the underlying performance change. Full HA runtime timing and the new hop/cover alarm decoding still need hardware validation. Polling is not a guaranteed event-delivery mechanism.

Back up the installed integration before updating and restart Home Assistant afterward. Existing entity IDs and configuration are retained by keeping the integration domain unchanged. The optional dashboard card is not included in this branch and is not installed by this integration release.

See `docs/adaptive-polling.md` for configuration, hardware tests and rollback instructions.
