# Local-mode hardware feedback, November 14, 2026

Test combination: Integration 3.2.1-beta.3, Companion 0.1.0-beta.12,
Display Card 0.7.0-beta.22 and Bridge 0.5.1-beta.2. The user enabled local-only
mode and reported restarting the Bridge after the configuration change.

## Observations reported by the tester

- Recipe Up/Down and the selected highlight update immediately to the tester.
- When navigating recipes from the phone, the tester observes the selected
  recipe changing simultaneously on the phone and PC Display Cards.
- Switching to manual control and pump/heater on/off feedback is responsive.
- During the brewing process, the user also reports a substantial improvement
  in responsiveness compared with the previous polling behavior.
- Standing next to the brewer and controlling it through HA on a phone, the
  tester observes the physical display and Display Card switching screens
  almost synchronously. The physical display visibly redraws line by line,
  from top to bottom. This is a visual observation without synchronized timing.
  It suggests distinguishing the start of a screen change from completion of
  the device's redraw; it does not identify whether CPU, firmware, display bus
  or display controller limits that redraw.
- The supplied screenshot at 09:08 CET shows a paused mash-in screen, an alarm,
  target/actual temperatures of 38/12 °C and a confirmed menu action. It does
  not by itself measure latency or validate every brewing stage or control.

These are qualitative hardware observations, not timed latency measurements.
A full internet-disconnected test including HA/Bridge restart remains open.

## TODO: compare reaction times with the controller generation from 2021

- [ ] Identify an available newer controller and record model, hardware revision,
  firmware, network connection and supported local protocol before comparing.
- [ ] Measure both controller generations under comparable network conditions
  and HA/Bridge/card settings, using normal, already-supported operations.
- [ ] Separate command submission, delivery in a device poll, device status
  confirmation, HA entity update and card rendering timestamps. Also measure
  spontaneous status changes during brewing, independently of button presses.
- [ ] Record both displays together on video and distinguish the first visible
  change from the fully drawn screen, especially on the older device's display.
- [ ] Record device message intervals and repeated measurements (sample count,
  median, 95th percentile and maximum), rather than only perceived speed.
- [ ] Determine whether any difference comes from firmware/controller processing,
  the Wi-Fi module, protocol cadence, network latency or HA polling.

The tester suspects the older controller's MCU (identified by the tester as a
32 MHz ATxmega256A3) may now be the limiting factor. This remains a hypothesis;
neither the clock rate alone nor the current responsiveness establishes the
bottleneck. No claim that the newer generation is faster has been verified.
