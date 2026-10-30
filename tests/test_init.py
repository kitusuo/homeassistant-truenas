"""Setting the integration up, unloading it, reloading it — against the recorded TrueNAS."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.truenas.const import DOMAIN


async def test_setup_creates_entities_from_every_platform(hass, setup_integration):
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    domains = {e.domain for e in entities}
    assert {"sensor", "binary_sensor", "update"} <= domains
    assert (
        len(entities) > 50
    ), "pools, datasets, disks, services, interfaces, tasks and an app are all recorded"


async def test_the_coordinator_reads_every_recorded_method(
    hass, setup_integration, truenas_api
):
    called = {s for s, _ in truenas_api.calls}
    for method in (
        "system.info",
        "interface.query",
        "service.query",
        "pool.query",
        "boot.get_state",
        "pool.dataset.query",
        "disk.query",
        "disk.temperatures",
        "virt.instance.query",
        "cloudsync.query",
        "replication.query",
        "pool.snapshottask.query",
        "app.query",
        "reporting.netdata_get_data",
    ):
        assert method in called, method


async def test_unload_removes_the_coordinator(hass, setup_integration):
    entry = setup_integration
    assert entry.entry_id in hass.data[DOMAIN]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_reload_sets_it_up_again(hass, setup_integration):
    entry = setup_integration
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_a_nas_that_cannot_be_reached_retries_setup(
    hass, truenas_api, config_entry
):
    truenas_api.connect = lambda: False
    truenas_api._connected = False
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_nas_that_drops_off_mid_update_makes_the_entities_unavailable(
    hass, setup_integration, truenas_api
):
    """A query whose connection breaks (TrueNASAPI.query disconnects and returns None) fails the whole refresh,
    rather than publishing a half-read NAS."""
    coordinator = hass.data[DOMAIN][setup_integration.entry_id]

    def broken(params):
        truenas_api.disconnect()
        return None

    truenas_api.responses["pool.query"] = broken
    truenas_api.connect = lambda: False  # and it stays away
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success is False
    assert hass.states.get("binary_sensor.truenas_services_ssh").state == "unavailable"


async def test_the_recorded_nas_produces_exactly_the_known_entities(
    hass, setup_integration
):
    """A guard on every change to how entities are created: the 84 entity ids the recording produces
    (tests/fixtures/entity_ids.json). A change here is a change users see — review it, then update the list.
    """
    import json
    import pathlib

    expected = json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "entity_ids.json").read_text()
    )
    ids = sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(
            er.async_get(hass), setup_integration.entry_id
        )
    )
    assert ids == expected
