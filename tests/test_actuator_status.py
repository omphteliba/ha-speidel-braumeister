"""Regression tests for both XHR parsers; no HA runtime or network required.

Run: python -m unittest discover -s tests -v
Requires aiohttp, already a runtime dependency of the clients.
"""

import importlib
import sys
import types
import unittest
from pathlib import Path

# Load the real client modules without executing the HA integration __init__.
PACKAGE = "_speidel_parser_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1] /
                        "custom_components" / "speidel_braumeister")]
sys.modules[PACKAGE] = package
SpeidelWebAuth = importlib.import_module(f"{PACKAGE}.web_auth").SpeidelWebAuth
SpeidelXHRClient = importlib.import_module(f"{PACKAGE}.xhr_client").SpeidelXHRClient


class ActuatorStatusTests(unittest.TestCase):
    def setUp(self):
        self.clients = (SpeidelWebAuth("", ""), SpeidelXHRClient("", ""))

    def payload(self, indicators="ph", counter="1004", field8="1"):
        # Sanitized firmware 1.1.27 main-menu response. No real identifiers,
        # cookies, session values, or account hashes are included.
        fields = ["0", "22:37", "C", "101", "-10000", " 20.0", "1200",
                  counter, field8, "0", "0", "0", "0", "EMSR", indicators,
                  "000", "0", "0", "0"]
        return "V1.1.27 Sep 12 2018;TEST_DEVICE;0;" + "X".join(fields) + ";test;test"

    def check(self, payload, pump, heating):
        for client in self.clients:
            with self.subTest(client=type(client).__name__):
                result = client._parse_xhr_response(payload)
                self.assertEqual(result["pump"], pump)
                self.assertEqual(result["heating"], heating)
                self.assertEqual(result["temperature"], 20.0)

    def test_captured_main_menu_does_not_report_heating(self):
        self.check(self.payload(), "off", "off")

    def test_all_active_inactive_combinations(self):
        for flags, pump, heater in (("ph", "off", "off"), ("Ph", "on", "off"),
                                     ("pH", "off", "on"), ("PH", "on", "on"),
                                     ("qh", "off", "off"), ("qH", "off", "on"),
                                     ("pi", "off", "off"), ("Pi", "on", "off"),
                                     ("qi", "off", "off")):
            with self.subTest(flags=flags):
                self.check(self.payload(flags), pump, heater)

    def test_counter_and_field8_do_not_control_actuators(self):
        for counter in ("0", "1", "2", "3", "1004", "1006", "invalid"):
            for flag in ("0", "1", "2", "3", "invalid"):
                for indicators, expected in (("ph", "off"), ("PH", "on")):
                    with self.subTest(counter=counter, flag=flag, indicators=indicators):
                        self.check(self.payload(indicators, counter, flag), expected, expected)

    def test_missing_unknown_and_partial_indicators(self):
        for flags, pump, heater in (("", "unknown", "unknown"),
                                    ("P", "on", "unknown"),
                                    ("?H", "unknown", "on"),
                                    ("p?", "off", "unknown"),
                                    ("QI", "unknown", "unknown"),
                                    ("PHextra", "unknown", "unknown")):
            with self.subTest(flags=flags):
                self.check(self.payload(flags), pump, heater)

    def test_truncated_payload_does_not_fall_back_to_numeric_flags(self):
        parts = self.payload().split(";")
        fields = parts[3].split("X")
        for length in (9, 14):
            parts[3] = "X".join(fields[:length])
            self.check(";".join(parts), "unknown", "unknown")


if __name__ == "__main__":
    unittest.main()
