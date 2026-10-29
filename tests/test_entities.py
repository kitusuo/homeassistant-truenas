"""What the recorded NAS looks like in Home Assistant: states, units, attributes, devices, diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.helpers import device_registry as dr, frame

from custom_components.truenas.diagnostics import async_get_config_entry_diagnostics

from .conftest import recording


def state(hass, entity_id):
    st = hass.states.get(entity_id)
    assert st is not None, entity_id
    return st


async def test_system_readings(hass, setup_integration):
    assert state(hass, "sensor.truenas_system_cpu_usage").state == "0.57"
    assert state(hass, "sensor.truenas_system_cpu_load_shortterm").state == "0.08"
    assert state(hass, "sensor.truenas_system_arc_size").state == "32.12503650164"
    # uptime is the BOOT time: now minus the recorded uptime_seconds
    boot = datetime.fromisoformat(state(hass, "sensor.truenas_system_uptime").state)
    uptime = recording()["system.info"]["uptime_seconds"]
    expected = datetime.now(timezone.utc) - timedelta(seconds=uptime)
    assert abs((boot - expected).total_seconds()) < 60


async def test_a_virtual_machine_is_not_asked_for_cpu_temperature(
    hass, truenas_api, config_entry
):
    """A hypervisor's virtual hardware has no CPU temperature: the graph is not even requested."""
    truenas_api.responses["system.info"]["system_manufacturer"] = "QEMU"
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    asked = [
        g["name"]
        for params in truenas_api.called("reporting.netdata_get_data")
        for g in params[0]
    ]
    assert "cputemp" not in asked and "cpu" in asked


async def test_other_hardware_is_asked_for_cpu_temperature_and_reports_the_hottest_core(
    hass, truenas_api, config_entry
):
    graphs = truenas_api.responses["reporting.netdata_get_data"]
    truenas_api.responses["reporting.netdata_get_data"] = lambda params: [
        *graphs(params),
        {
            "name": "cputemp",
            "identifier": "cputemp",
            "legend": ["time", "cpu0", "cpu1"],
            "aggregations": {"mean": {"cpu0": 41.2, "cpu1": 43.7}},
            "data": [],
        },
    ]
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    asked = [
        g["name"]
        for params in truenas_api.called("reporting.netdata_get_data")
        for g in params[0]
    ]
    assert "cputemp" in asked
    assert state(hass, "sensor.truenas_system_temperature").state == "43.7"


async def test_disk_temperatures_join_on_the_device_name(hass, setup_integration):
    assert state(hass, "sensor.truenas_disks_sdb").state == "25.0"
    assert (
        state(hass, "sensor.truenas_disks_sda").state == "unknown"
    ), "a disk TrueNAS has no reading for"


async def test_pools_datasets_and_tasks(hass, setup_integration):
    assert state(hass, "binary_sensor.truenas_system_pool1_healthy").state == "on"
    assert state(hass, "sensor.truenas_system_pool1_free").state == "2408.380044242"
    assert (
        state(hass, "sensor.truenas_datasets_pool1_ds8").attributes[
            "unit_of_measurement"
        ]
        == "GB"
    )
    assert state(hass, "sensor.truenas_cloudsync_task1").state == "SUCCESS"
    assert state(hass, "sensor.truenas_replication_task3").state == "SUCCESS"


async def test_services_and_apps_are_on_or_off(hass, setup_integration):
    assert state(hass, "binary_sensor.truenas_services_ssh").state == "on"
    assert state(hass, "binary_sensor.truenas_services_ftp").state == "off"
    app = state(hass, "binary_sensor.truenas_apps_app1")
    assert app.state == "on" and app.attributes["icon"]


async def test_a_stopped_service_shows_its_off_icon(hass, setup_integration):
    on = state(hass, "binary_sensor.truenas_services_ssh").attributes.get("icon")
    off = state(hass, "binary_sensor.truenas_services_ftp").attributes.get("icon")
    assert on and off and on != off


async def test_interfaces_report_traffic(hass, setup_integration):
    assert state(hass, "sensor.truenas_system_eth1_rx").state == "0.00145408"
    assert state(hass, "sensor.truenas_system_eth1_tx").state == "0.0007168"


async def test_every_entity_hangs_off_a_device(hass, setup_integration):
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), setup_integration.entry_id
    )
    names = {d.name for d in devices}
    assert "System" in names and len(devices) > 3


async def test_diagnostics_redact_the_secrets(hass, setup_integration):
    diag = await async_get_config_entry_diagnostics(hass, setup_integration)
    assert diag["entry"]["data"]["api_key"] == "**REDACTED**"
    assert diag["entry"]["data"]["host"] == "**REDACTED**"
    assert diag["data"]["system_info"]["system_serial"] == "**REDACTED**"
    assert diag["data"]["pool"], "the rest of the data is there"


# ---------------------------------------------------------------- bug 3: entity ids and device info HA deprecates
async def setup_fresh(hass, config_entry):
    """Set up with HA's report-once memory cleared: a deprecation already reported by an earlier test in the same
    process would otherwise be silent here."""
    frame._REPORTED_INTEGRATIONS.clear()
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_no_invalid_entity_id_is_built(hass, truenas_api, config_entry, caplog):
    """An entity with no name of its own built "update.truenas_system_" (trailing "_"), which HA refuses from
    2027.2 ("sets an invalid entity ID")."""
    await setup_fresh(hass, config_entry)
    assert "invalid entity ID" not in caplog.text
    assert hass.states.get("update.truenas_system") is not None


async def test_device_info_uses_no_deprecated_default_fields(
    hass, truenas_api, config_entry, caplog
):
    """default_name / default_model / default_manufacturer are removed in HA 2027.9."""
    await setup_fresh(hass, config_entry)
    assert "deprecated `default_" not in caplog.text
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    )
    sub = [d for d in devices if d.name != "System"]
    assert sub, "the pools, disks, datasets … devices"
    assert all(d.manufacturer == "manufacturer-1" for d in sub)
    assert all(d.model == "product-1" for d in sub)
