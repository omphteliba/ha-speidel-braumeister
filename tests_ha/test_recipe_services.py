"""HA registration, device selection and generic transport."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from custom_components.speidel_braumeister.services import async_setup_services


@pytest.mark.parametrize('action,data,response,method', [
    ('recipe_upload_readiness', {}, {'device_id': 'BM', 'ready_for_upload': True}, 'GET'),
    ('start_recipe_upload', {'recipes': [{'name': 'Example'}]}, {'device_id': 'BM', 'job_id': '123'}, 'POST'),
    ('recipe_upload_status', {'job_id': '123'}, {'device_id': 'BM', 'job_id': '123', 'result': 'confirmed'}, 'GET'),
])
async def test_generic_actions(hass, action, data, response, method):
    async_setup_services(hass)
    entry = SimpleNamespace(entry_id='entry', state=ConfigEntryState.LOADED,
                            runtime_data=SimpleNamespace(_machine_uuid='BM.123'))
    reply = MagicMock(status=202 if method == 'POST' else 200, json=AsyncMock(return_value=response))
    session = MagicMock()
    session.request.return_value.__aenter__.return_value = reply
    with patch.object(hass.config_entries, 'async_entries', return_value=[entry]), patch(
        'custom_components.speidel_braumeister.services.async_get_clientsession', return_value=session
    ):
        result = await hass.services.async_call('speidel_braumeister', action, data, blocking=True, return_response=True)
    assert result == response
    assert session.request.call_args.args[0] == method


async def test_unknown_job_is_not_success(hass):
    async_setup_services(hass)
    entry = SimpleNamespace(entry_id='entry', state=ConfigEntryState.LOADED,
                            runtime_data=SimpleNamespace(_machine_uuid='BM.123'))
    reply = MagicMock(status=404, text=AsyncMock(return_value='Unknown or expired upload job'))
    session = MagicMock()
    session.request.return_value.__aenter__.return_value = reply
    with patch.object(hass.config_entries, 'async_entries', return_value=[entry]), patch(
        'custom_components.speidel_braumeister.services.async_get_clientsession', return_value=session
    ), pytest.raises(HomeAssistantError, match='404'):
        await hass.services.async_call('speidel_braumeister', 'recipe_upload_status', {'job_id': 'gone'},
                                       blocking=True, return_response=True)
