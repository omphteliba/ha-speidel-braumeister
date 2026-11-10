"""Tests that need a Home Assistant install (pytest-homeassistant-custom-component).

Kept apart from tests/, which load single modules without Home Assistant.
Run with: pip install -r requirements_test_ha.txt && pytest tests_ha
"""

import sys
from pathlib import Path

import pytest

# Make custom_components importable as a package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components/."""
    yield
