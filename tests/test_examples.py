"""The example dashboard must be valid YAML and use only entities this integration creates."""

import re

import yaml

from conftest import ROOT

DASHBOARD = ROOT / "examples" / "brewery-dashboard.yaml"
KNOWN = {
    "sensor.braumeister_temperature", "sensor.braumeister_target_temperature",
    "sensor.braumeister_pump_status", "sensor.braumeister_heating_status",
    "sensor.braumeister_process_status", "sensor.braumeister_current_phase",
    "sensor.braumeister_current_step", "sensor.braumeister_remaining_time",
    "sensor.braumeister_brew_name", "sensor.braumeister_brewing_progress",
    "sensor.braumeister_device_mode", "sensor.braumeister_connection_status",
    "sensor.braumeister_last_online", "sensor.braumeister_device_recipes",
    "binary_sensor.braumeister_alarm",
}


def test_dashboard_is_valid_yaml():
    config = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
    assert config["views"][0]["sections"]


def test_dashboard_uses_only_known_entities():
    body = "\n".join(line for line in DASHBOARD.read_text(encoding="utf-8").splitlines() if not line.startswith("#"))
    used = set(re.findall(r"\b(?:sensor|binary_sensor)\.braumeister_[a-z_]+\b", body))
    assert used, "no entities found"
    assert used <= KNOWN, used - KNOWN


def test_markdown_cards_keep_line_breaks():
    """Markdown tables need real newlines; a folded block (>-) joins them into one line."""
    config = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
    cards = [c for s in config["views"][0]["sections"] for c in s["cards"] if c["type"] == "markdown"]
    assert cards
    for card in cards:
        assert "\n|---|" in card["content"] or "{% for r in recipes %}\n" in card["content"]
