# Local brewing screen messages

The status parser derives `current_step` and `display_phase` from device fields
3 (state), 14 (pump pause), and 15 (interrupt/lid prompt), using the observed
firmware 1.1.27 screen behavior. The bridge path no longer overwrites that text
with a web page title. Optional cloud metadata can still provide the account
recipe name, device name and mode; it is not required for the step text.

Examples: Wasser eingefüllt?, Pumpe wird entlüftet, Malz einfüllen!,
Malzrohr entnehmen!, Pumpenpause, Start Hopfenkochen?, Hopfen zugeben.
Unknown state gaps retain their numeric code. Missing rest/hop indexes are not
invented. Interrupt/lid prompts take precedence over the ordinary phase text.
The display strings currently follow the German firmware portal vocabulary.

The current-step sensor exposes display_phase, display_state_code,
display_interrupt, display_rest_number and display_hop_number as attributes.
This change does not add a dashboard, device controls, timers or audio. It does
not change the translated on/off enums, beep-based alarms (including state
3080), remaining-time calculation or recipe decoding/persistence.

Manual observations: a user tested the transitions through mash-in, rests,
pump pause, rest end, malt-pipe removal, lid removal prompt and heat-up for boiling on a pre-2020
20 L Plus with external WLAN and firmware 1.1.27. This newly rebased patch itself
has automated regression coverage; it has not yet been deployed to that device.
