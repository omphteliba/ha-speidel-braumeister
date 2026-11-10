"""Reauthentication, unavailable logging and parallel updates (quality scale Silver)."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speidel_braumeister import binary_sensor, sensor
from custom_components.speidel_braumeister.api import SpeidelApiError, SpeidelAuthError
from custom_components.speidel_braumeister.const import DOMAIN
from custom_components.speidel_braumeister.coordinator import SpeidelBraumeisterDataCoordinator

PACKAGE = "custom_components.speidel_braumeister"
FLOW = f"{PACKAGE}.config_flow"
DATA = {
    "username": "brewer@example.invalid", "password": "old-password",
    "machine_uuid": "1234567890ABCDEF.123", "scan_interval": 30,
}


def test_platforms_limit_parallel_updates() -> None:
    assert sensor.PARALLEL_UPDATES == 0
    assert binary_sensor.PARALLEL_UPDATES == 0


async def test_rejected_password_at_setup_starts_reauth(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry.add_to_hass(hass)
    api = MagicMock(authenticate=AsyncMock(side_effect=SpeidelAuthError("Invalid credentials")), close=AsyncMock())
    with patch(f"{PACKAGE}.SpeidelBraumeisterAPI", return_value=api):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


@pytest.mark.parametrize(("error", "key"), [
    (SpeidelAuthError("wrong"), "invalid_auth"),
    (SpeidelApiError("500"), "cannot_connect"),
    (RuntimeError("boom"), "unknown"),
])
async def test_reauth_flow_updates_password(hass: HomeAssistant, error, key) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, unique_id="1234567890abcdef.123")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["username"] == DATA["username"]

    with patch(f"{FLOW}.validate_auth", AsyncMock(side_effect=error)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "typo"})
    assert result["errors"] == {"base": key}

    with patch(f"{FLOW}.validate_auth", AsyncMock(return_value={"success": True})) as validate, \
            patch(f"{PACKAGE}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "new-password"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert validate.call_args.args[1:] == (DATA["username"], "new-password")
    assert entry.data == {**DATA, "password": "new-password"}


async def test_device_offline_and_back_is_logged_once(hass: HomeAssistant, caplog) -> None:
    coordinator = SpeidelBraumeisterDataCoordinator(hass, MagicMock(), DATA["machine_uuid"])
    states = iter(["online", "online", "offline", "offline", "online", "online"])

    async def fetch():
        return {"connection_status": next(states)}

    coordinator._fetch_data = fetch
    caplog.set_level(logging.INFO, logger=f"{PACKAGE}.coordinator")
    for _ in range(6):
        await coordinator._async_update_data()
    messages = [r.getMessage() for r in caplog.records if r.name == f"{PACKAGE}.coordinator"]
    assert messages == [
        "Braumeister is not sending data (switched off or no WiFi)",
        "Braumeister is sending data again",
    ]


async def test_device_off_at_startup_is_not_logged(hass: HomeAssistant, caplog) -> None:
    coordinator = SpeidelBraumeisterDataCoordinator(hass, MagicMock(), DATA["machine_uuid"])

    async def fetch():
        return {"connection_status": "offline"}

    coordinator._fetch_data = fetch
    caplog.set_level(logging.INFO, logger=f"{PACKAGE}.coordinator")
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert not [r for r in caplog.records if r.name == f"{PACKAGE}.coordinator"]
