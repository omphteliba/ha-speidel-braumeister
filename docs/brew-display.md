# Local brewing display status

The bridge path now populates the existing `current_step` sensor with German
screen messages rather than `Statuscode N`. The existing dashboard card reads
this sensor; no card replacement is required. Raw state, phase, interrupt,
rest number and hop number are exposed as sensor attributes.

Mapping evidence: user-supplied MySpeidel `bm_controll.min.js` (buildScreen and
parseStatus) and the German control-page bmtext captured on 2026-10-30, firmware
1.1.27. This includes water confirmation, pump venting, heating, malt prompts,
rests/pump pauses, malt pipe removal, boiling, hop prompts and completion.
Interrupts override the normal message; cover indicator D overrides the
interrupt digit as in the portal. Rest/hop indices become one-based labels.
Unmapped codes stay numeric. No control commands are generated.

Scope: local bridge telemetry only. Existing cloud fallback text is unchanged.
This does not reconstruct the complete portal layout, recipe timeline or
button controls. The current card uses the same sensor for header and main text.
The mapping is covered by synthetic boundary/override tests; validate the
screens against the real device during the next test brew.
