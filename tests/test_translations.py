"""Consistency checks for the translation files."""

import json

import pytest

from conftest import ROOT

COMPONENT = ROOT / "custom_components" / "speidel_braumeister"
FILES = {
    "strings": COMPONENT / "strings.json",
    "en": COMPONENT / "translations" / "en.json",
    "de": COMPONENT / "translations" / "de.json",
}


def load(name: str) -> dict:
    return json.loads(FILES[name].read_text(encoding="utf-8"))


def keys(tree: dict, prefix: str = "") -> set[str]:
    out = set()
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        out |= keys(value, path) if isinstance(value, dict) else {path}
    return out


def test_strings_matches_english():
    assert load("strings") == load("en")


def test_german_has_same_keys_as_english():
    assert keys(load("de")) == keys(load("en"))


@pytest.mark.parametrize("sensor", ["pump_status", "heating_status"])
@pytest.mark.parametrize(("lang", "on", "off"), [("en", "On", "Off"), ("de", "Ein", "Aus")])
def test_actuator_states_translated(sensor, lang, on, off):
    assert load(lang)["entity"]["sensor"][sensor]["state"] == {"on": on, "off": off}
