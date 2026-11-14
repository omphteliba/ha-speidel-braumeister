"""Credential-free startup, restart and local config flow in real HA."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

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
         patch(f'{PACKAGE}.async_setup_entry', return_value=True):
        flow = await hass.config_entries.flow.async_init('speidel_braumeister', context={'source': config_entries.SOURCE_USER})
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'local_only': True})
        assert flow['step_id'] == 'local'
        flow = await hass.config_entries.flow.async_configure(flow['flow_id'], {'name': 'Local brewer', 'machine_uuid': 'TEST'})
        assert flow['type'] is FlowResultType.CREATE_ENTRY
        assert flow['data'] == {'machine_uuid': 'TEST', 'local_only': True}

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
