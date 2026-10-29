"""The integration's entity services: services, apps, VMs, cloud sync, snapshots, reboot/shutdown.

Each one first reads the object's current state from TrueNAS and refuses (logs, does nothing) when the action
would make no sense — starting what runs, stopping what is stopped — or when the reply is unusable.
"""

from __future__ import annotations

import pytest

from custom_components.truenas.const import DOMAIN

SERVICE = "binary_sensor.truenas_services_ftp"
ACTIONS = ("service.start", "service.stop", "service.restart", "service.reload")
APP = "binary_sensor.truenas_apps_app1"


async def call(hass, service: str, entity_id: str, **data) -> None:
    await hass.services.async_call(
        DOMAIN, service, {"entity_id": entity_id, **data}, blocking=True
    )
    await hass.async_block_till_done()


def ftp_id(truenas_api) -> int:
    return next(
        s["id"] for s in truenas_api.responses["service.query"] if s["service"] == "ftp"
    )


# ---------------------------------------------------------------- services (ftp is STOPPED in the recording)
@pytest.mark.parametrize(
    "action, state, method",
    [
        ("service_start", "STOPPED", "service.start"),
        ("service_stop", "RUNNING", "service.stop"),
        ("service_restart", "RUNNING", "service.restart"),
        ("service_reload", "RUNNING", "service.reload"),
    ],
)
async def test_a_service_action_runs_when_the_state_allows_it(
    hass, setup_integration, truenas_api, action, state, method
):
    truenas_api.responses["service.get_instance"] = {
        "id": ftp_id(truenas_api),
        "state": state,
    }
    await call(hass, action, SERVICE)
    assert truenas_api.called(method) == [["ftp"]]
    assert truenas_api.called("service.get_instance") == [[ftp_id(truenas_api)]]


@pytest.mark.parametrize(
    "action, state",
    [
        ("service_start", "RUNNING"),
        ("service_stop", "STOPPED"),
        ("service_restart", "STOPPED"),
        ("service_reload", "STOPPED"),
    ],
)
async def test_a_service_action_that_makes_no_sense_is_refused(
    hass, setup_integration, truenas_api, action, state, caplog
):
    truenas_api.responses["service.get_instance"] = {"state": state}
    await call(hass, action, SERVICE)
    assert not [
        s
        for s, _ in truenas_api.calls
        if s.startswith("service.")
        and s != "service.get_instance"
        and s != "service.query"
    ]
    assert "ftp" in caplog.text


@pytest.mark.parametrize(
    "action", ["service_start", "service_stop", "service_restart", "service_reload"]
)
async def test_an_unusable_service_reply_is_refused(
    hass, setup_integration, truenas_api, action, caplog
):
    truenas_api.responses["service.get_instance"] = {"unexpected": True}
    await call(hass, action, SERVICE)
    assert "invalid" in caplog.text
    assert not [
        s for s, _ in truenas_api.calls if s in ACTIONS
    ], "nothing is started, stopped, restarted or reloaded"


# ---------------------------------------------------------------- apps (app1 is RUNNING)
async def test_app_stop_and_start(hass, setup_integration, truenas_api):
    app_id = truenas_api.responses["app.query"][0]["id"]
    truenas_api.responses["app.get_instance"] = {"state": "RUNNING"}
    await call(hass, "app_stop", APP)
    assert truenas_api.called("app.stop") == [[app_id]]
    truenas_api.responses["app.get_instance"] = {"state": "STOPPED"}
    await call(hass, "app_start", APP)
    assert truenas_api.called("app.start") == [[app_id]]


@pytest.mark.parametrize(
    "action, reply",
    [
        ("app_start", {"state": "RUNNING"}),
        ("app_stop", {"state": "STOPPED"}),
        ("app_start", None),
        ("app_stop", {"nope": 1}),
    ],
)
async def test_an_app_action_that_makes_no_sense_is_refused(
    hass, setup_integration, truenas_api, action, reply
):
    truenas_api.responses["app.get_instance"] = reply
    await call(hass, action, APP)
    assert not truenas_api.called("app.start") and not truenas_api.called("app.stop")


# ---------------------------------------------------------------- VMs (none recorded: one is added)
VM = {
    "id": "vm1",
    "name": "vm1",
    "type": "VM",
    "cpu": 2,
    "memory": 4 * 1024**3,
    "autostart": True,
    "image": {"description": "Debian"},
    "status": "STOPPED",
}


@pytest.fixture
async def with_vm(hass, truenas_api, config_entry):
    truenas_api.responses["virt.instance.query"] = [dict(VM)]
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return "binary_sensor.truenas_vms_vm1"


async def test_a_vm_is_an_entity_with_its_memory_in_gib(hass, with_vm):
    state = hass.states.get(with_vm)
    assert state.state == "off"
    assert state.attributes["Memory"] == 4, "bytes from TrueNAS, GiB on the entity"


async def test_vm_start_and_stop(hass, with_vm, truenas_api):
    truenas_api.responses["virt.instance.get_instance"] = {"status": "STOPPED"}
    await call(hass, "vm_start", with_vm)
    assert truenas_api.called("virt.instance.start") == [["vm1"]]
    truenas_api.responses["virt.instance.get_instance"] = {"status": "RUNNING"}
    await call(hass, "vm_stop", with_vm)
    assert truenas_api.called("virt.instance.stop") == [
        ["vm1", {"timeout": 0, "force": True}]
    ]


@pytest.mark.parametrize(
    "action, reply",
    [
        ("vm_start", {"status": "RUNNING"}),
        ("vm_stop", {"status": "STOPPED"}),
        ("vm_start", {"x": 1}),
        ("vm_stop", {"x": 1}),
    ],
)
async def test_a_vm_action_that_makes_no_sense_is_refused(
    hass, with_vm, truenas_api, action, reply
):
    truenas_api.responses["virt.instance.get_instance"] = reply
    await call(hass, action, with_vm)
    assert not truenas_api.called("virt.instance.start") and not truenas_api.called(
        "virt.instance.stop"
    )


# ---------------------------------------------------------------- sensors' services
CLOUDSYNC = "sensor.truenas_cloudsync_task1"


async def test_cloudsync_run_and_abort(hass, setup_integration, truenas_api):
    task_id = truenas_api.responses["cloudsync.query"][0]["id"]
    truenas_api.responses["cloudsync.get_instance"] = {"job": {"state": "SUCCESS"}}
    await call(hass, "cloudsync_run", CLOUDSYNC)
    assert truenas_api.called("cloudsync.sync") == [[task_id]]
    truenas_api.responses["cloudsync.get_instance"] = {"job": {"state": "RUNNING"}}
    await call(hass, "cloudsync_abort", CLOUDSYNC)
    assert truenas_api.called("cloudsync.abort") == [[task_id]]


@pytest.mark.parametrize(
    "action, reply",
    [
        ("cloudsync_run", {"job": {"state": "RUNNING"}}),
        ("cloudsync_abort", {"job": {"state": "SUCCESS"}}),
        ("cloudsync_run", {"nojob": 1}),
        ("cloudsync_abort", {"nojob": 1}),
    ],
)
async def test_a_cloudsync_action_that_makes_no_sense_is_refused(
    hass, setup_integration, truenas_api, action, reply
):
    truenas_api.responses["cloudsync.get_instance"] = reply
    await call(hass, action, CLOUDSYNC)
    assert not truenas_api.called("cloudsync.sync") and not truenas_api.called(
        "cloudsync.abort"
    )


async def test_dataset_snapshot(hass, setup_integration, truenas_api):
    await call(hass, "dataset_snapshot", "sensor.truenas_datasets_pool1_ds8")
    ((params,),) = truenas_api.called(
        "zfs.snapshot.create"
    )  # a dict, wrapped in a list on the wire
    assert params["dataset"] == "pool1/ds8" and params["name"].startswith("custom-")


@pytest.mark.parametrize(
    "action, method",
    [("system_reboot", "system.reboot"), ("system_shutdown", "system.shutdown")],
)
async def test_reboot_and_shutdown(
    hass, setup_integration, truenas_api, action, method
):
    await call(hass, action, "sensor.truenas_system_uptime")
    assert truenas_api.called(method) == [["Home Assistant Integration"]]
