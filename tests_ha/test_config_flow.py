"""Config and options flow: happy path, error recovery, duplicates."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speidel_braumeister.api import (
    SpeidelApiError,
    SpeidelAuthError,
    SpeidelConnectionError,
)
from custom_components.speidel_braumeister.const import DOMAIN

CREDENTIALS = {"username": "brewer@example.invalid", "password": "test-password"}
MACHINE = {"name": "Braumeister", "machine_uuid": "1234567890ABCDEF.123", "scan_interval": 30}
FLOW = "custom_components.speidel_braumeister.config_flow"


@pytest.fixture
def setup_entry():
    with patch("custom_components.speidel_braumeister.async_setup_entry", return_value=True) as mock:
        yield mock


async def start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_user_flow_creates_entry(hass: HomeAssistant, setup_entry) -> None:
    result = await start(hass)
    with patch(f"{FLOW}.validate_auth", AsyncMock(return_value={"success": True, "user_id": 1})):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "machine"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**MACHINE, "machine_uuid": "  1234567890ABCDEF.123 "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Braumeister"
    assert result["data"] == {**CREDENTIALS, "machine_uuid": "1234567890ABCDEF.123", "scan_interval": 30}
    assert result["result"].unique_id == "1234567890abcdef.123"
    assert len(setup_entry.mock_calls) == 1


@pytest.mark.parametrize(("error", "key"), [
    (SpeidelAuthError("wrong"), "invalid_auth"),
    (SpeidelApiError("500"), "cannot_connect"),
    (SpeidelConnectionError("offline"), "cannot_connect"),
    (RuntimeError("boom"), "unknown"),
])
async def test_auth_errors_are_shown_and_recoverable(hass: HomeAssistant, setup_entry, error, key) -> None:
    result = await start(hass)
    with patch(f"{FLOW}.validate_auth", AsyncMock(side_effect=error)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": key}

    with patch(f"{FLOW}.validate_auth", AsyncMock(return_value={"success": True, "user_id": 1})):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], MACHINE)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("existing", [
    {"unique_id": "1234567890abcdef.123", "data": {"machine_uuid": "1234567890abcdef.123"}},
    # Entries created before unique IDs existed
    {"unique_id": None, "data": {**CREDENTIALS, "machine_uuid": "1234567890ABCDEF.123"}},
])
async def test_same_device_is_not_set_up_twice(hass: HomeAssistant, setup_entry, existing) -> None:
    MockConfigEntry(domain=DOMAIN, **existing).add_to_hass(hass)
    result = await start(hass)
    with patch(f"{FLOW}.validate_auth", AsyncMock(return_value={"success": True, "user_id": 1})):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDENTIALS)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], MACHINE)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(setup_entry.mock_calls) == 0


async def test_options_flow_stores_scan_interval(hass: HomeAssistant, setup_entry) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={**CREDENTIALS, **MACHINE})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"scan_interval": 60})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"scan_interval": 60}
