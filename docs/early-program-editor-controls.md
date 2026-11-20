# Early-program and manual-editor controls

Port from the coordinated beta for Braumeister 20 L Plus, firmware 1.1.27.
These are named Bridge `/api/control` actions used by Companion beta.24; no
Companion installation or live Home Assistant configuration is changed here.

## Action contract

All actions require `control_enabled`, a loopback API client without an Origin
header, and fresh status. Manual-editor and water/delay actions require `ph`.
The source context is rechecked before dispatch, and a key is sent once only.
Existing cloud-command arbitration, pending-command exclusion and expiry apply.

| Action | Source screen / buttons / indicator | Key | Expected result |
| --- | --- | --- | --- |
| `open_temperature_editor` | 4006/APHT/000 | 4 | 4007/ADUS/00T |
| `temperature_up` | 4007/ADUS/00T | 3 | Same editor, target +1 °C |
| `temperature_down` | 4007/ADUS/00T | 2 | Same editor, target -1 °C |
| `confirm_temperature` | 4007/ADUS/00T | 4 | 4006/APHT/000 with the selected target |
| `cancel_temperature` | 4007/ADUS/00T | 1 | 101/EMSR; 00T can persist |
| `start_delay_up` | 2030 or 2111/ADUS/000 | 3 | 2111/ADUS/000 |
| `start_delay_down` | 2111/ADUS/000 | 2 | 2111/ADUS/000 |
| `confirm_start_delay` | 2111/ADUS/000 | 4 | 2120/A00S/000/ph, or 2300/A000/000/Ph with zero delay |
| `cancel_water_prompt` | 2030 or 2111/ADUS/000 | 1 | 101/EMSR/000 |
| `cancel_start_delay` | 2120/A00S/000 | 1 | 101/EMSR/000, delay zero |
| `start_now` | 2120/A00S/000, positive delay | 4 | 2300/A000/000/Ph, delay zero |
| `confirm_water_filled` | 2030/ADUS/000 | 4 | 2300/A000/000/Ph, delay zero |

The three additional program actions use exact screen/actuator/indicator tuples:

| Action | Source | Target | Key |
| --- | --- | --- | --- |
| `acknowledge_mash_temperature` | 2510/Pi/010 or 2510/qi/010 | 2610/ph/000 | 4 |
| `open_malt_confirmation` | 2610/ph/000 | 2705/ph/000 | 4 |
| `confirm_malt_added` | 2705/ph/000 | 2810/PH/000 | 4 |

`confirm_water_filled`, `confirm_start_delay`, `start_now`, and
`confirm_malt_added` additionally require both `program_control_enabled` and
`allow_remote_heating` at enqueue and immediately before dispatch. This also
covers selecting a delayed start that may later activate the program. Upstream's
existing heating gates for `start_boil` and `resume_program` are retained.
Manual editing is restricted to inactive actuators and does not switch them on.
Temperature arrows accept whole Celsius targets only, within 0–100 °C; Fahrenheit,
active-actuator editing and other editor screens are excluded.

## Evidence and limitations

The manual editor was captured on November 17: records 113→115 open the editor,
158→160 and 197→199 change 38↔39 °C, 240→242 confirms, and 330→332 cancels to the
main menu. All had `ph`. The follow-up 695→697→717→719→751 verifies that reopening
after cancellation restores the original target. Bounds are conservative software
guards, not hardware boundary validation.

Delay evidence on November 17 includes 2373→2375 (Up from 2030), 2390→2392
(Down), 2971→2973 (Select, field 17 = 3599), and 3057→3059 (countdown cancellation).
Initial water-prompt Cancel is recorded at 23:45:50–52, records 21→23 in the new
session. HA Up/Up/Select/Cancel was subsequently captured at 23:53–23:55.
On November 18, HA records 320→322 show Start now, and 1253→1255 show zero-delay
confirmation leading directly to purge.

Mash-in cloud transitions are recorded on November 18 at 2675→2677 (Pi),
2800→2802, and 2908→2910. The separate hot-start 2510/qi acknowledgment is recorded
at 18:20:26–27, records 3212→3214. This does not validate rest-end 2910/qi, which
remains unsupported. Sequence numbers belong to their respective sessions.

## Direct water-start hardware validation — November 20, 2026

The previously missing direct `confirm_water_filled` transition is now recorded
through both MySpeidel and the installed HA beta. Times are CET (UTC+01:00),
from Bridge timestamps rather than the minute-resolution device clock.

| Origin | Key-4 command | Source | First resulting status | Target |
| --- | --- | --- | --- | --- |
| MySpeidel (`cloud`) | 08:58:11.356, sequence 130673 | 2030/ph/ADUS/000 | 08:58:12.515, sequence 130675 | 2300/Ph/A000/000 |
| HA (`local_control`) | 09:04:37.284, sequence 131150 | 2030/ph/ADUS/000 | 09:04:38.382, sequence 131152 | 2300/Ph/A000/000 |

Field 17 is zero before and after both commands; all listed responses have HTTP
status 200. No Up/Down commands, delay-editor state 2111, or countdown state 2120
occur between entry into each water prompt and its confirmation. Earlier Down
commands belonged to recipe selection 2015, before the water prompt.
Sequence ranges 130614–130680 and 131121–131154 were checked and have no gaps.
The raw diagnostic snapshots are retained locally and are not included in this PR.

This closes the direct-start evidence gap and supports making the PR ready for
review. The HA hardware run used the installed beta, not this new upstream build.
The new implementation has automated coverage; not every ported route has been
individually hardware-retested on the upstream build. No device operation was
performed by the log inspection.

The selected delay value in 2111 is not exposed in the captured status. Arrow
commands that remain in 2111 therefore finish as `unconfirmed`, not a fabricated
numeric acknowledgment. Do not infer a delay from key counts or automatically
retry. Countdown expiry, boil/rest editing, held keys, and additional pause/abort
contexts are outside this PR. No broad beta permission tables are copied.

Evidence sources (pinned beta sources):
- [Manual editor](https://github.com/DanielP-1337/ha-speidel-braumeister/blob/a4a8bf1/docs/manual-editor-hardware-2026-11-17.md)
- [Start delay](https://github.com/DanielP-1337/ha-speidel-braumeister/blob/a4a8bf1/docs/start-delay-hardware-2026-11-17.md)
- [Mash-in](https://github.com/DanielP-1337/ha-speidel-braumeister/blob/a4a8bf1/docs/mash-in-hardware-2026-11-18.md)
- [Hot-start observation](https://github.com/DanielP-1337/braumeister-display-card/blob/905e8bd/docs/hardware-todo.md)
