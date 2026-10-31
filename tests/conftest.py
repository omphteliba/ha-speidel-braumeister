"""Load the modules under test directly from their files.

device_protocol.py has no Home Assistant imports, so it can be tested without
installing Home Assistant (importing the package would load __init__.py).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


device_protocol = _load(
    "device_protocol", ROOT / "custom_components" / "speidel_braumeister" / "device_protocol.py"
)
bridge = _load("bridge", ROOT / "braumeister_bridge" / "app" / "bridge.py")


@pytest.fixture
def dp():
    return device_protocol


@pytest.fixture
def bridge_module():
    return bridge


@pytest.fixture
def samples() -> list[str]:
    lines = (FIXTURES / "bm_stat_samples.txt").read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line and not line.startswith("#")]
