"""HA registration, device selection and generic transport."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

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

@pytest.mark.parametrize('action,data', [
    ('recipe_upload_readiness', {}),
    ('recipe_upload_status', {'job_id': '123'}),
    ('start_recipe_upload', {'recipes': [{'name': 'Example'}]}),
])
@pytest.mark.parametrize('failure', [TimeoutError, ClientError])
async def test_transport_error_only_warns_about_upload_for_start(hass, action, data, failure):
    async_setup_services(hass)
    entry = SimpleNamespace(entry_id='entry', state=ConfigEntryState.LOADED,
                            runtime_data=SimpleNamespace(_machine_uuid='BM.123'))
    session = MagicMock()
    session.request.return_value.__aenter__.side_effect = failure('connection lost')
    with patch.object(hass.config_entries, 'async_entries', return_value=[entry]), patch(
        'custom_components.speidel_braumeister.services.async_get_clientsession', return_value=session
    ), pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call('speidel_braumeister', action, data, blocking=True, return_response=True)
    if action == 'start_recipe_upload':
        assert 'an upload may have been accepted' in str(error.value)
        assert 'Do not retry automatically' in str(error.value)
    else:
        assert str(error.value) == 'Bridge not reachable'
    assert session.request.call_count == 1


async def test_start_bad_request_preserves_bridge_validation_message(hass):
    async_setup_services(hass)
    entry = SimpleNamespace(entry_id='entry', state=ConfigEntryState.LOADED,
                            runtime_data=SimpleNamespace(_machine_uuid='BM.123'))
    reply = MagicMock(status=400, text=AsyncMock(return_value='Recipe writes are disabled'))
    session = MagicMock()
    session.request.return_value.__aenter__.return_value = reply
    with patch.object(hass.config_entries, 'async_entries', return_value=[entry]), patch(
        'custom_components.speidel_braumeister.services.async_get_clientsession', return_value=session
    ), pytest.raises(ServiceValidationError, match='^Recipe writes are disabled$'):
        await hass.services.async_call('speidel_braumeister', 'start_recipe_upload',
                                       {'recipes': [{'name': 'Example'}]}, blocking=True, return_response=True)
    assert session.request.call_count == 1
