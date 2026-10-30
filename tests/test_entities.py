"""What the recorded NAS looks like in Home Assistant: states, units, attributes, devices, diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr

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
async def test_no_invalid_entity_id_is_built(
    hass, truenas_api, config_entry, ha_deprecations
):
    """An entity with no name of its own built "update.truenas_system_" (trailing "_"), refused from HA 2027.2."""
    await setup_entry(hass, config_entry)
    assert not [d for d in ha_deprecations if "entity ID" in d], ha_deprecations
    assert hass.states.get("update.truenas_system") is not None


async def test_device_info_triggers_no_device_registry_deprecation(
    hass, truenas_api, config_entry, ha_deprecations
):
    """default_name/model/manufacturer (removed in HA 2027.9) and via_device (removed in 2027.8, a month sooner:
    the parent is given by its registry id, via_device_id). ANY deprecation fails this test.
    """
    await setup_entry(hass, config_entry)
    assert ha_deprecations == []
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    )
    system = next(d for d in devices if d.name == "System")
    sub = [d for d in devices if d.name != "System"]
    assert sub, "the pools, disks, datasets … devices"
    assert all(d.manufacturer == "manufacturer-1" for d in sub)
    assert all(d.model == "product-1" for d in sub)
    assert all(
        d.via_device_id == system.id for d in sub
    ), "every device hangs off System"


# ---------------------------------------------------------------- bug 4: an empty CPU-temperature graph
def with_cputemp(truenas_api, mean):
    graphs = truenas_api.responses["reporting.netdata_get_data"]
    truenas_api.responses["reporting.netdata_get_data"] = lambda params: [
        *graphs(params),
        {
            "name": "cputemp",
            "identifier": "cputemp",
            "legend": ["time", *mean],
            "aggregations": {"mean": mean},
            "data": [],
        },
    ]


async def test_an_empty_cpu_temperature_graph_does_not_fail_the_update(
    hass, truenas_api, config_entry
):
    """A NAS whose sensors return nothing: `max()` of an empty mean raised, and the WHOLE update failed — every
    entity unavailable, for want of one temperature."""
    with_cputemp(truenas_api, {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert state(hass, "binary_sensor.truenas_services_ssh").state == "on"
    # no reading yet: the entity exists (the graph is supported) and is unknown — not missing, not 0 °C
    assert state(hass, "sensor.truenas_system_temperature").state == "unknown"


async def test_a_core_without_a_reading_is_skipped(hass, truenas_api, config_entry):
    with_cputemp(truenas_api, {"cpu0": None, "cpu1": 40.5})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert state(hass, "sensor.truenas_system_temperature").state == "40.5"


# ---------------------------------------------------------------- bug 5: a reporting graph TrueNAS cannot serve
ERROR = {"jsonrpc": "2.0", "id": 0, "error": {"code": 22, "message": "graph failed"}}


def key(graph: dict) -> tuple:
    return graph["name"], graph.get("identifier")


def reporting(truenas_api, fails):
    """reporting.netdata_get_data answering a JSON-RPC error when `fails(asked_keys)` says so. Returns the list of
    every request's keys, so tests assert on what the integration ASKS for."""
    graphs = truenas_api.responses["reporting.netdata_get_data"]
    asked = []

    def answer(params):
        keys = [key(g) for g in params[0]]
        asked.append(keys)
        return ERROR if fails(keys) else graphs(params)

    truenas_api.responses["reporting.netdata_get_data"] = answer
    return asked


async def setup_entry(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    return hass.data["truenas"][config_entry.entry_id]


def last_batch(asked):
    """The keys of the most recent multi-graph request."""
    return next(b for b in reversed(asked) if len(b) > 1)


async def test_a_graph_truenas_cannot_serve_is_set_aside_and_the_rest_still_read(
    hass, truenas_api, config_entry, caplog
):
    """One failing graph failed the whole batch and the statistics stayed unread: the retry path that should have
    found it could never run (it waited for api.error == 500, and then indexed a list with "graphs").
    """
    asked = reporting(truenas_api, lambda keys: ("arcsize", None) in keys)
    coordinator = await setup_entry(hass, config_entry)
    assert state(hass, "sensor.truenas_system_cpu_usage").state == "0.57"
    warnings = [
        r
        for r in caplog.records
        if r.levelname == "WARNING" and "arcsize" in r.getMessage()
    ]
    assert warnings, "the graph set aside is named in a WARNING"
    asked.clear()
    await coordinator.async_refresh()
    assert ("arcsize", None) not in last_batch(asked), "later batches leave it out"
    assert ("cpu", None) in last_batch(asked)


async def test_a_batch_that_failed_but_whose_graphs_work_alone_is_read_in_the_same_poll(
    hass, truenas_api, config_entry
):
    """The answers to the per-graph requests are used — not thrown away for another batch — and nothing is set
    aside: the next poll asks for everything again."""
    asked = reporting(truenas_api, lambda keys: len(keys) > 1 and len(asked) == 1)
    coordinator = await setup_entry(hass, config_entry)
    assert state(hass, "sensor.truenas_system_cpu_usage").state == "0.57"
    assert len(asked) < 15, "one batch plus one request per graph, no endless re-run"
    asked.clear()
    await coordinator.async_refresh()
    assert ("arcsize", None) in last_batch(asked)


async def test_when_every_graph_fails_nothing_is_set_aside_and_the_statistics_recover(
    hass, truenas_api, config_entry
):
    """netdata down for a moment (a NAS still booting): every graph fails alone too. That is the NAS, not the
    graphs — set aside, they stayed unread until Home Assistant restarted."""
    down = {"now": True}
    asked = reporting(truenas_api, lambda keys: down["now"])
    coordinator = await setup_entry(hass, config_entry)
    assert state(hass, "sensor.truenas_system_cpu_usage").state == "0.0"
    down["now"] = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "sensor.truenas_system_cpu_usage").state == "0.57"
    assert ("arcsize", None) in last_batch(asked)


async def test_a_graph_set_aside_is_tried_again_after_an_hour(
    hass, truenas_api, config_entry, freezer
):
    asked = reporting(truenas_api, lambda keys: ("arcsize", None) in keys)
    coordinator = await setup_entry(hass, config_entry)
    freezer.tick(timedelta(minutes=30))
    asked.clear()
    await coordinator.async_refresh()
    assert ("arcsize", None) not in last_batch(asked), "within the hour: still left out"
    freezer.tick(timedelta(minutes=31))
    asked.clear()
    await coordinator.async_refresh()
    assert ("arcsize", None) in last_batch(asked), "after an hour: asked again"


async def test_two_graphs_set_aside_side_by_side_are_both_left_out(
    hass, truenas_api, config_entry
):
    """The leave-out filter removed from the list it iterated, skipping the graph after each removal."""
    broken = {("cpu", None), ("arcsize", None)}
    asked = reporting(truenas_api, lambda keys: bool(broken & set(keys)))
    coordinator = await setup_entry(hass, config_entry)
    asked.clear()
    await coordinator.async_refresh()
    assert not broken & set(last_batch(asked))
    assert state(hass, "sensor.truenas_system_cpu_load_shortterm").state == "0.08"


async def test_one_failing_interface_graph_sets_aside_only_that_interface(
    hass, truenas_api, config_entry
):
    """Every interface graph is named "interface": set aside by name, one bad interface hid them all."""
    asked = reporting(truenas_api, lambda keys: ("interface", "eth2") in keys)
    coordinator = await setup_entry(hass, config_entry)
    assert state(hass, "sensor.truenas_system_eth1_rx").state == "0.00145408"
    asked.clear()
    await coordinator.async_refresh()
    assert ("interface", "eth2") not in last_batch(asked)
    assert ("interface", "eth1") in last_batch(asked)


async def test_a_disconnect_during_the_per_graph_retries_sets_nothing_aside(
    hass, truenas_api, config_entry
):
    """A lost connection is not a graph TrueNAS cannot serve: the refresh fails, and nothing is set aside."""
    state_ = {"phase": "ok", "calls": 0}

    def fails(keys):
        if state_["phase"] == "ok":
            return False
        state_["calls"] += 1
        if state_["calls"] == 1:
            return True  # the batch fails
        truenas_api.disconnect()  # the first per-graph retry: the connection drops
        truenas_api.connect = lambda: False
        return True

    asked = reporting(truenas_api, fails)
    coordinator = await setup_entry(hass, config_entry)
    state_["phase"] = "broken"
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    state_["phase"] = "ok"
    truenas_api.connect = lambda: truenas_api.__class__.connect(truenas_api)
    asked.clear()
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert ("arcsize", None) in last_batch(asked), "nothing was set aside"


# ---------------------------------------------------------------- review-2 2.2: the temperature entity
async def test_an_empty_first_cpu_temperature_still_creates_the_entity_which_fills_in_later(
    hass, truenas_api, config_entry
):
    """Entities are created only at setup, and one whose value was missing then was never created: a NAS whose
    first CPU-temperature reading was empty never got the sensor, even once readings arrived.
    """
    readings = {"mean": {}}
    graphs = truenas_api.responses["reporting.netdata_get_data"]
    truenas_api.responses["reporting.netdata_get_data"] = lambda params: [
        *graphs(params),
        {
            "name": "cputemp",
            "identifier": "cputemp",
            "legend": ["time", "cpu0"],
            "aggregations": dict(readings),
            "data": [],
        },
    ]
    coordinator = await setup_entry(hass, config_entry)
    assert state(hass, "sensor.truenas_system_temperature").state == "unknown"
    readings["mean"] = {"cpu0": 45.0}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, "sensor.truenas_system_temperature").state == "45.0"


async def test_a_cpu_temperature_graph_without_aggregations_is_unknown_not_zero(
    hass, truenas_api, config_entry
):
    """It reported a made-up 0.0 °C."""
    graphs = truenas_api.responses["reporting.netdata_get_data"]
    truenas_api.responses["reporting.netdata_get_data"] = lambda params: [
        *graphs(params),
        {"name": "cputemp", "identifier": "cputemp", "legend": ["time"], "data": []},
    ]
    await setup_entry(hass, config_entry)
    assert state(hass, "sensor.truenas_system_temperature").state == "unknown"
