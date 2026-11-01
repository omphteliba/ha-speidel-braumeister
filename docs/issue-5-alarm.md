# Alarm entity follow-up (issue #5)

The existing parser already recognizes remove-lid and hop-addition alarms,
plus mash-in temperature reached, rest end and brew finished. This follow-up
checks the actual XHR parser and bridge parser through the coordinator and
binary sensor, including acknowledgement with stale portal text.

Fix: an explicit decoded `alarm` value is authoritative even without a state
code. Previously those values were ignored and an old phase label could keep
an acknowledged alarm active. The legacy phase fallback is used only when no
`alarm` field exists. Alarm types and entity IDs remain unchanged.

These are offline regression tests with Home Assistant boundary stubs, not a
new live-brew validation. No push notifications or device commands are added.
Review should confirm whether this covers the reporter's remaining symptoms;
short alarms between polls can still be missed.
