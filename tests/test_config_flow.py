"""The config flow: add a TrueNAS, refuse a duplicate name or a NAS that cannot be reached, reconfigure."""

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.truenas.const import DOMAIN

from .conftest import ENTRY_DATA


async def test_the_form_creates_an_entry(hass, truenas_api):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["errors"] == {}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TrueNAS" and result["data"] == ENTRY_DATA
    assert truenas_api.host == ENTRY_DATA["host"] and truenas_api.verify_ssl is False


async def test_an_unreachable_nas_shows_the_reason(hass, truenas_api):
    truenas_api.connection_test = lambda: (False, "connection_refused")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(ENTRY_DATA)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"host": "connection_refused"}


async def test_a_name_already_used_is_refused(hass, truenas_api, config_entry):
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(ENTRY_DATA)
    )
    assert result["errors"] == {"base": "name_exists"}


async def test_reconfigure_updates_the_entry(hass, setup_integration, truenas_api):
    entry = setup_integration
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "reconfigure"
    new = {"host": "nas2.example.invalid", "api_key": "new-key", "verify_ssl": True}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    # the abort reloads the entry: let it finish, or its storage write lingers past the test
    await hass.async_block_till_done()
    assert (
        result["type"] is FlowResultType.ABORT
        and result["reason"] == "reconfigure_successful"
    )
    assert (
        entry.data["host"] == "nas2.example.invalid" and entry.data["name"] == "TrueNAS"
    )


async def test_reconfigure_shows_a_connection_error(
    hass, setup_integration, truenas_api
):
    truenas_api.connection_test = lambda: (False, "invalid_key")
    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "x", "api_key": "bad", "verify_ssl": False}
    )
    assert result["type"] is FlowResultType.FORM and result["errors"] == {
        "host": "invalid_key"
    }
