"""Credential-free startup, restart and local config flow in real HA."""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientConnectionError

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

PACKAGE = 'custom_components.speidel_braumeister'


async def test_local_setup_restart_and_diagnostics_never_construct_cloud_clients(hass):
    entry = MockConfigEntry(domain='speidel_braumeister', data={'machine_uuid': 'TEST', 'local_only': True})
    entry.add_to_hass(hass)
    with patch(f'{PACKAGE}.SpeidelBraumeisterAPI', side_effect=AssertionError('Cloud API')), \
         patch(f'{PACKAGE}.SpeidelWebAuth', side_effect=AssertionError('Web login')), \
         patch(f'{PACKAGE}.coordinator.SpeidelBraumeisterDataCoordinator._fetch_bridge', AsyncMock(return_value=None)):
        for _ in range(2):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            coordinator = entry.runtime_data
            assert coordinator.update_interval == timedelta(seconds=5)
            assert coordinator.api is None
            assert coordinator.data['connection_status'] == 'offline'
            from custom_components.speidel_braumeister.diagnostics import async_get_config_entry_diagnostics
            diagnostic = await async_get_config_entry_diagnostics(hass, entry)
            assert diagnostic['local_only'] is True
            with patch.object(coordinator, 'async_request_refresh', AsyncMock()) as refresh:
                hass.bus.async_fire('braumeister_menu_updated', {'device_id': 'OTHER'})
                await hass.async_block_till_done()
                refresh.assert_not_awaited()
                hass.bus.async_fire('braumeister_menu_updated', {'device_id': 'TEST'})
                await hass.async_block_till_done()
                refresh.assert_awaited_once()
            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()


async def test_new_local_entry_needs_no_cloud_credentials(hass):
    with patch(f'{PACKAGE}.config_flow.validate_auth', side_effect=AssertionError('Cloud auth')), \
         patch(f'{PACKAGE}.config_flow.async_bridge_devices', AsyncMock(return_value=['TEST'])), \
         patch(f'{PACKAGE}.async_setup_entry', return_value=True):
        flow = await hass.config_entries.flow.async_init('speidel_braumeister', context={'source': config_entries.SOURCE_USER})
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'local_only': True})
        assert flow['step_id'] == 'local'
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'name': 'Local brewer', 'machine_uuid': 'TEST'})
        assert flow['type'] is FlowResultType.CREATE_ENTRY
        assert flow['data'] == {'machine_uuid': 'TEST', 'local_only': True}


@pytest.mark.parametrize('existing_id,new_id,local', [
    ('1234567890ABCDEF.123', '1234567890abcdef', True),
    ('1234567890ABCDEF', '1234567890abcdef.123', True),
    ('1234567890ABCDEF', '1234567890abcdef.123', False),
])
async def test_local_cloud_duplicate_ids(hass, existing_id, new_id, local):
    entry = MockConfigEntry(domain='speidel_braumeister', data={'machine_uuid': existing_id})
    entry.add_to_hass(hass)
    with patch(f'{PACKAGE}.config_flow.async_bridge_devices', AsyncMock(return_value=[new_id])), \
         patch(f'{PACKAGE}.config_flow.validate_auth', AsyncMock(return_value={})), \
         patch(f'{PACKAGE}.async_setup_entry', return_value=True):
        flow = await hass.config_entries.flow.async_init('speidel_braumeister', context={'source': config_entries.SOURCE_USER})
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'local_only': local})
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'machine_uuid': new_id})
        assert flow['type'] is FlowResultType.ABORT
        assert flow['reason'] == 'already_configured'


@pytest.mark.parametrize('failure,error', [
    (ClientConnectionError(), 'cannot_connect'),
    (TimeoutError(), 'cannot_connect'),
    (ValueError(), 'cannot_connect'),
    ([], 'no_local_devices'),
])
async def test_local_discovery_failure_can_retry(hass, failure, error):
    with patch(f'{PACKAGE}.config_flow.async_bridge_devices', AsyncMock()) as discover, \
         patch(f'{PACKAGE}.async_setup_entry', return_value=True):
        discover.side_effect = failure if isinstance(failure, Exception) else None
        discover.return_value = failure
        flow = await hass.config_entries.flow.async_init('speidel_braumeister', context={'source': config_entries.SOURCE_USER})
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'local_only': True})
        assert flow['errors'] == {'base': error}
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'machine_uuid': 'TYPO'})
        assert flow['type'] is FlowResultType.FORM
        assert flow['errors']['base'] == ('unknown_local_device' if failure == [] else error)
        discover.side_effect = None
        discover.return_value = ['TEST']
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'machine_uuid': 'test.123'})
        assert flow['type'] is FlowResultType.CREATE_ENTRY


async def test_local_selection_is_rechecked_before_saving(hass):
    with patch(f'{PACKAGE}.config_flow.async_bridge_devices', AsyncMock(return_value=['ONE', 'TWO'])) as discover:
        flow = await hass.config_entries.flow.async_init('speidel_braumeister', context={'source': config_entries.SOURCE_USER})
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'local_only': True})
        validator = next(value for key, value in flow['data_schema'].schema.items() if str(key) == 'machine_uuid')
        assert set(validator.container) == {'ONE', 'TWO'}
        discover.return_value = ['TWO']
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'machine_uuid': 'ONE'})
        assert flow['errors'] == {'base': 'unknown_local_device'}
        discover.side_effect = ClientConnectionError()
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'machine_uuid': 'TWO'})
        assert flow['errors'] == {'base': 'cannot_connect'}


@pytest.mark.parametrize('payload,expected', [
    ({'devices': [{'device_id': 'TEST', 'bm_stat_received': 0}, {'device_id': 'TEST'}]}, ['TEST']),
    ({'devices': []}, []),
    ([], None),
    ({}, None),
    ({'devices': [None]}, None),
    ({'devices': [{'device_id': ''}]}, None),
])
async def test_bridge_discovery_reads_local_status(hass, payload, expected):
    from custom_components.speidel_braumeister.config_flow import async_bridge_devices
    response = MagicMock()
    response.json = AsyncMock(return_value=payload)
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    with patch(f'{PACKAGE}.config_flow.async_get_clientsession', return_value=session):
        if expected is None:
            with pytest.raises(ValueError):
                await async_bridge_devices(hass)
        else:
            assert await async_bridge_devices(hass) == expected
    assert session.get.call_args.args == ('http://127.0.0.1:8642/api/status',)
    assert session.get.call_args.kwargs['timeout'].total == 2
    response.raise_for_status.assert_called_once()

async def test_existing_entry_can_switch_to_local_without_changing_entity_identity(hass):
    data = {'machine_uuid': 'EXISTING.123', 'username': 'unused', 'password': 'unused', 'scan_interval': 30}
    entry = MockConfigEntry(domain='speidel_braumeister', unique_id='existing.123', data=data)
    entry.add_to_hass(hass)
    with patch(f'{PACKAGE}.async_setup_entry', return_value=True):
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        flow = await hass.config_entries.options.async_configure(flow['flow_id'], {'local_only': True, 'scan_interval': 30})
        assert flow['type'] is FlowResultType.CREATE_ENTRY
    assert entry.data == data
    assert entry.unique_id == 'existing.123'
    with patch(f'{PACKAGE}.SpeidelBraumeisterAPI', side_effect=AssertionError('Cloud API')), \
         patch(f'{PACKAGE}.SpeidelWebAuth', side_effect=AssertionError('Web login')), \
         patch(f'{PACKAGE}.coordinator.SpeidelBraumeisterDataCoordinator._fetch_bridge', AsyncMock(return_value={'temperature': 42, 'state_code': 2410})):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.update_interval == timedelta(seconds=5)
        assert entry.runtime_data.data['temperature'] == 42
        assert entry.runtime_data.data['data_source'] == 'bridge'
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_credential_free_entry_cannot_accidentally_enable_cloud(hass):
    entry = MockConfigEntry(domain='speidel_braumeister', data={'machine_uuid': 'TEST', 'local_only': True})
    entry.add_to_hass(hass)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow['flow_id'], {'local_only': False, 'scan_interval': 30})
    assert flow['type'] is FlowResultType.FORM
    assert flow['errors'] == {'base': 'cloud_credentials_required'}
