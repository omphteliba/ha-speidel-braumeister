"""Setup and unload of a config entry with the cloud clients mocked."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.speidel_braumeister.const import DOMAIN
from custom_components.speidel_braumeister.request_policy import PollingError

PACKAGE = "custom_components.speidel_braumeister"
DATA = {
    "username": "brewer@example.invalid", "password": "test-password",
    "machine_uuid": "1234567890ABCDEF.123", "scan_interval": 30,
}


def clients(authenticate=None):
    api = MagicMock(authenticate=AsyncMock(side_effect=authenticate), close=AsyncMock(), subscription_id=None,
                    probe_timeseries=AsyncMock())  # runs when debug logging is on (pytest -v)
    web = MagicMock(login=AsyncMock(return_value=True), close=AsyncMock(), machines=[])
    return (
        patch(f"{PACKAGE}.SpeidelBraumeisterAPI", return_value=api),
        patch(f"{PACKAGE}.SpeidelWebAuth", return_value=web),
        patch(f"{PACKAGE}.coordinator.SpeidelBraumeisterDataCoordinator._async_update_data",
              AsyncMock(return_value={"temperature": 20.5})),
    )


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options={"scan_interval": 60})
    entry.add_to_hass(hass)
    api, web, update = clients()
    with api, web, update:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        # The interval from the options flow wins over the one from setup
        assert entry.runtime_data.update_interval == timedelta(seconds=60)
        assert hass.services.has_service(DOMAIN, "upload_recipes")
        assert hass.states.async_entity_ids("sensor")

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_is_retried_when_my_speidel_asks_for_a_pause(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry.add_to_hass(hass)
    api, web, update = clients(authenticate=PollingError("MySpeidel requested a polling pause"))
    with api, web, update:
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
