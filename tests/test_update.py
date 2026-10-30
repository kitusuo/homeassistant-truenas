"""Update entities: the TrueNAS system and its apps."""

from __future__ import annotations

import pytest

APP_UPDATE = "update.truenas_apps_app1"


def app_with_update(truenas_api, state="RUNNING"):
    app = truenas_api.responses["app.query"][0]
    app.update(
        upgrade_available=True, version="1.3.21", latest_version="1.3.22", state=state
    )
    return app


@pytest.fixture
async def setup(hass, truenas_api, config_entry):
    async def _setup():
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    return _setup


async def test_an_app_with_an_update_offers_it(hass, truenas_api, setup):
    app_with_update(truenas_api)
    await setup()
    st = hass.states.get(APP_UPDATE)
    assert st.state == "on"
    assert (
        st.attributes["installed_version"] == "1.3.21"
        and st.attributes["latest_version"] == "1.3.22"
    )
    assert st.attributes["title"] == "app1"


async def test_installing_an_app_update_upgrades_that_app(hass, truenas_api, setup):
    app = app_with_update(truenas_api)
    truenas_api.responses["app.upgrade"] = 1234
    await setup()
    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )
    assert truenas_api.called("app.upgrade") == [[app["id"]]]


async def test_a_stopped_app_is_not_upgraded(hass, truenas_api, setup, caplog):
    app_with_update(truenas_api, state="STOPPED")
    await setup()
    entity = hass.data["update"].get_entity(APP_UPDATE)
    await entity.async_install(None, False)
    assert not truenas_api.called("app.upgrade")
    assert "must not be in stopped state" in caplog.text


async def test_the_system_update_entity_shows_the_installed_version(
    hass, setup_integration
):
    st = hass.states.get("update.truenas_system")
    assert st.attributes["installed_version"] == "25.10.7"
    assert st.attributes["in_progress"] is False


async def test_before_25_10_an_available_system_update_is_offered(
    hass, truenas_api, setup
):
    """`update.check_available` is how TrueNAS before 25.10 reports an update."""
    truenas_api.responses["update.check_available"] = {
        "status": "AVAILABLE",
        "version": "25.04.3",
    }
    truenas_api.responses["system.info"]["version"] = "25.04.2"
    await setup()
    st = hass.states.get("update.truenas_system")
    assert st.state == "on" and st.attributes["latest_version"] == "25.04.3"


async def test_a_running_system_update_job_reports_its_progress(
    hass, truenas_api, setup
):
    """While an install job runs, the entity follows its percentage; when it ends, progress resets."""
    truenas_api.responses["update.check_available"] = {
        "status": "AVAILABLE",
        "version": "25.04.3",
    }
    truenas_api.responses["system.info"]["version"] = "25.04.2"
    jobs = [{"id": 77, "state": "RUNNING", "progress": {"percent": 40}}]
    truenas_api.responses["core.get_jobs"] = lambda params: [
        j for j in jobs if j["id"] == params[0][0][2]
    ]
    await setup()
    coordinator = next(iter(hass.data["truenas"].values()))
    coordinator.ds["system_info"]["update_jobid"] = 77
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    st = hass.states.get("update.truenas_system")
    assert (
        st.attributes["in_progress"] is True
        and st.attributes["update_percentage"] == 40
    )
    jobs[0]["state"] = "SUCCESS"
    await coordinator.async_refresh()
    assert coordinator.ds["system_info"]["update_jobid"] == 0


# ---------------------------------------------------------------- bug 1: an app update stuck "in progress"
def jobs(*records):
    """core.get_jobs over a mutable job list, honouring the [["id", "=", n]] filter."""
    store = list(records)

    def answer(params):
        return [j for j in store if j["id"] == params[0][0][2]]

    answer.store = store
    return answer


async def test_an_app_upgrade_is_in_progress_only_while_its_job_runs(
    hass, truenas_api, setup
):
    """After one upgrade, the next must install: the job id must not keep the app "in progress" for ever
    (every later install was refused with "Update installation already in progress" until HA restarted).
    """
    app = app_with_update(truenas_api)
    truenas_api.responses["app.upgrade"] = 1234
    job = {"id": 1234, "method": "app.upgrade", "state": "RUNNING"}
    truenas_api.responses["core.get_jobs"] = jobs(job)
    await setup()
    entity = hass.data["update"].get_entity(APP_UPDATE)
    coordinator = next(iter(hass.data["truenas"].values()))

    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )
    assert entity.in_progress is True, "while the upgrade job runs"

    job["state"] = "SUCCESS"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert entity.in_progress is False, "the job has finished"

    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )
    assert truenas_api.called("app.upgrade") == [[app["id"]], [app["id"]]]


@pytest.mark.parametrize("final", ["FAILED", "ABORTED"])
async def test_a_failed_app_upgrade_is_no_longer_in_progress(
    hass, truenas_api, setup, final
):
    app_with_update(truenas_api)
    truenas_api.responses["app.upgrade"] = 1234
    job = {"id": 1234, "method": "app.upgrade", "state": "RUNNING"}
    truenas_api.responses["core.get_jobs"] = jobs(job)
    await setup()
    entity = hass.data["update"].get_entity(APP_UPDATE)
    coordinator = next(iter(hass.data["truenas"].values()))
    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )
    job["state"] = final
    await coordinator.async_refresh()
    assert entity.in_progress is False


async def test_a_job_truenas_no_longer_knows_is_not_in_progress(
    hass, truenas_api, setup
):
    """TrueNAS restarted: core.get_jobs no longer has the job."""
    app_with_update(truenas_api)
    truenas_api.responses["app.upgrade"] = 1234
    truenas_api.responses["core.get_jobs"] = jobs(
        {"id": 1234, "method": "app.upgrade", "state": "RUNNING"}
    )
    await setup()
    entity = hass.data["update"].get_entity(APP_UPDATE)
    coordinator = next(iter(hass.data["truenas"].values()))
    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )
    truenas_api.responses["core.get_jobs"].store.clear()
    await coordinator.async_refresh()
    assert entity.in_progress is False


async def test_an_error_reply_to_app_upgrade_is_not_an_upgrade_in_progress(
    hass, truenas_api, setup
):
    """No job id came back (the method failed): nothing is upgrading."""
    app_with_update(truenas_api)
    # app.upgrade absent from the responses: the fake answers with a JSON-RPC error, as TrueNAS does
    await setup()
    entity = hass.data["update"].get_entity(APP_UPDATE)
    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )
    assert entity.in_progress is False


# ---------------------------------------------------------------- bug 2: TrueNAS 25.10's update API
SYSTEM_UPDATE = "update.truenas_system"


async def test_on_25_10_an_available_system_update_comes_from_update_status(
    hass, truenas_api, setup, caplog
):
    """25.10 removed update.check_available (logged as "Method does not exist" twice a day): update.status says."""
    truenas_api.responses["update.status"]["status"]["new_version"] = {
        "version": "25.10.8",
        "train": "TrueNAS-SCALE-Goldeye",
    }
    await setup()
    st = hass.states.get(SYSTEM_UPDATE)
    assert st.state == "on" and st.attributes["latest_version"] == "25.10.8"
    assert not truenas_api.called("update.check_available")
    assert "Method does not exist" not in caplog.text and "not found" not in caplog.text


async def test_on_25_10_no_new_version_is_up_to_date(hass, truenas_api, setup):
    await setup()  # the recording: update.status new_version is null
    st = hass.states.get(SYSTEM_UPDATE)
    assert st.state == "off" and st.attributes["latest_version"] == "25.10.7"
    assert truenas_api.called("update.status")


async def test_on_25_10_install_runs_the_update(hass, truenas_api, setup):
    """update.update is the update CONFIGURATION on 25.10; installing is update.run."""
    truenas_api.responses["update.status"]["status"]["new_version"] = {
        "version": "25.10.8"
    }
    truenas_api.responses["update.run"] = 4321
    await setup()
    await hass.services.async_call(
        "update", "install", {"entity_id": SYSTEM_UPDATE}, blocking=True
    )
    assert truenas_api.called("update.run") == [
        [{"reboot": True, "version": "25.10.8"}]
    ]
    assert not truenas_api.called("update.update")


async def test_before_25_10_install_keeps_update_update(hass, truenas_api, setup):
    truenas_api.responses["update.check_available"] = {
        "status": "AVAILABLE",
        "version": "25.04.3",
    }
    truenas_api.responses["system.info"]["version"] = "25.04.2"
    truenas_api.responses["update.update"] = 4321
    await setup()
    await hass.services.async_call(
        "update", "install", {"entity_id": SYSTEM_UPDATE}, blocking=True
    )
    assert truenas_api.called("update.update") == [[{"reboot": True}]]
    assert not truenas_api.called("update.run")
    assert not truenas_api.called("update.status"), "pre-25.10 has no update.status"


# ---------------------------------------------------------------- review-2 1.1 / 1.3: the TrueNAS version
async def test_a_truenas_upgrade_while_ha_runs_switches_to_the_25_10_update_api(
    hass, truenas_api, setup
):
    """The version was parsed once: upgraded from 25.04 to 25.10 under a running HA, the integration kept calling
    update.check_available (gone) and update.update (configuration) until HA restarted.
    """
    truenas_api.responses["update.check_available"] = {
        "status": "UNAVAILABLE",
        "version": "",
    }
    truenas_api.responses["system.info"]["version"] = "25.04.2"
    await setup()
    coordinator = next(iter(hass.data["truenas"].values()))

    truenas_api.responses["system.info"]["version"] = "25.10.7"
    truenas_api.responses["update.status"]["status"]["new_version"] = {
        "version": "25.10.8"
    }
    truenas_api.responses["update.run"] = 4321
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    st = hass.states.get(SYSTEM_UPDATE)
    assert st.state == "on" and st.attributes["latest_version"] == "25.10.8"
    await hass.services.async_call(
        "update", "install", {"entity_id": SYSTEM_UPDATE}, blocking=True
    )
    assert truenas_api.called("update.run") == [
        [{"reboot": True, "version": "25.10.8"}]
    ]


@pytest.mark.parametrize(
    "version, new_api",
    [
        ("25.10-RC.1", True),
        ("25.10.0-BETA.1", True),
        ("TrueNAS-SCALE-24.04.2", False),
        ("TrueNAS-13.0-U6.2", False),
        ("MASTER-20261030", False),
    ],
)
async def test_any_version_string_is_parsed_without_failing_the_refresh(
    hass, truenas_api, setup, version, new_api
):
    """`int(version.split(".")[1])` raised on 25.10-RC.1, failing every refresh. Unparseable: the pre-25.10 calls."""
    truenas_api.responses["system.info"]["version"] = version
    truenas_api.responses["update.check_available"] = {"status": "UNAVAILABLE"}
    await setup()
    entry = next(iter(hass.config_entries.async_entries("truenas")))
    assert entry.state.name == "LOADED"
    assert bool(truenas_api.called("update.status")) is new_api
    assert bool(truenas_api.called("update.check_available")) is not new_api


# ---------------------------------------------------------------- review-2 1.2 / 1.4 / 1.5: job handling
def recording_jobs(answer):
    """Wrap a core.get_jobs answer to record every id the integration asks for."""
    asked = []

    def wrapped(params):
        asked.append(params[0][0][2])
        return answer(params)

    wrapped.asked = asked
    return wrapped


async def test_an_error_reply_from_core_get_jobs_does_not_fail_the_refresh(
    hass, truenas_api, setup
):
    """The client returns an error reply as a dict, so `job[0]` raised KeyError: every refresh failed, and the id was
    never cleared, until HA restarted."""
    app_with_update(truenas_api)
    truenas_api.responses["app.upgrade"] = 1234
    truenas_api.responses["core.get_jobs"] = jobs(
        {"id": 1234, "method": "app.upgrade", "state": "RUNNING"}
    )
    await setup()
    coordinator = next(iter(hass.data["truenas"].values()))
    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )
    truenas_api.responses["core.get_jobs"] = lambda params: {
        "jsonrpc": "2.0",
        "id": 0,
        "error": {"code": 13, "message": "Not authorized"},
    }
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert hass.data["update"].get_entity(APP_UPDATE).in_progress is False


async def test_a_waiting_app_job_is_in_progress(hass, truenas_api, setup):
    app_with_update(truenas_api)
    truenas_api.responses["app.upgrade"] = 1234
    truenas_api.responses["core.get_jobs"] = jobs(
        {"id": 1234, "method": "app.upgrade", "state": "WAITING"}
    )
    await setup()
    coordinator = next(iter(hass.data["truenas"].values()))
    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )
    await coordinator.async_refresh()
    assert hass.data["update"].get_entity(APP_UPDATE).in_progress is True


async def test_a_disconnect_while_reading_the_app_job_keeps_it_in_progress(
    hass, truenas_api, setup
):
    app_with_update(truenas_api)
    truenas_api.responses["app.upgrade"] = 1234
    store = jobs({"id": 1234, "method": "app.upgrade", "state": "RUNNING"})
    truenas_api.responses["core.get_jobs"] = store
    await setup()
    coordinator = next(iter(hass.data["truenas"].values()))
    entity = hass.data["update"].get_entity(APP_UPDATE)
    await hass.services.async_call(
        "update", "install", {"entity_id": APP_UPDATE}, blocking=True
    )

    def drop(params):
        truenas_api.disconnect()
        return None

    truenas_api.responses["core.get_jobs"] = drop
    truenas_api.connect = lambda: False
    await coordinator.async_refresh()
    assert entity.in_progress is True, "a lost connection says nothing about the job"


@pytest.mark.parametrize(
    "entity_id, method", [(APP_UPDATE, "app.upgrade"), (SYSTEM_UPDATE, "update.run")]
)
async def test_an_error_reply_to_install_is_never_polled_as_a_job(
    hass, truenas_api, setup, entity_id, method
):
    """Only a job id (an int) is kept: an error reply stored as the 'job id' was sent back in core.get_jobs."""
    app_with_update(truenas_api)
    truenas_api.responses["update.status"]["status"]["new_version"] = {
        "version": "25.10.8"
    }
    asked = recording_jobs(jobs())
    truenas_api.responses["core.get_jobs"] = asked
    # `method` is absent from the responses: the fake answers a JSON-RPC error, as TrueNAS does
    await setup()
    await hass.services.async_call(
        "update", "install", {"entity_id": entity_id}, blocking=True
    )
    coordinator = next(iter(hass.data["truenas"].values()))
    await coordinator.async_refresh()
    assert truenas_api.called(method), method
    assert all(isinstance(i, int) for i in asked.asked), asked.asked


async def test_a_waiting_system_update_job_is_in_progress(hass, truenas_api, setup):
    """A queued (WAITING) update was cleared at once: only RUNNING counted."""
    truenas_api.responses["update.status"]["status"]["new_version"] = {
        "version": "25.10.8"
    }
    truenas_api.responses["update.run"] = 4321
    truenas_api.responses["core.get_jobs"] = jobs(
        {
            "id": 4321,
            "method": "update.run",
            "state": "WAITING",
            "progress": {"percent": 0},
        }
    )
    await setup()
    await hass.services.async_call(
        "update", "install", {"entity_id": SYSTEM_UPDATE}, blocking=True
    )
    coordinator = next(iter(hass.data["truenas"].values()))
    await coordinator.async_refresh()
    assert coordinator.ds["system_info"]["update_jobid"] == 4321
    assert hass.data["update"].get_entity(SYSTEM_UPDATE).in_progress


# ---------------------------------------------------------------- review-2 1.6 and update.status's real shapes
async def test_on_25_10_install_installs_exactly_the_version_shown(
    hass, truenas_api, setup
):
    """update.run without a version installs the newest release, which may be newer than the one offered."""
    truenas_api.responses["update.status"] = {
        "code": "NORMAL",
        "error": None,
        "status": {
            "current_version": {"train": "TrueNAS-SCALE-Goldeye"},
            "new_version": {"version": "25.10.8", "train": "TrueNAS-SCALE-Goldeye"},
        },
        "update_download_progress": None,
    }
    truenas_api.responses["update.run"] = 4321
    await setup()
    await hass.services.async_call(
        "update", "install", {"entity_id": SYSTEM_UPDATE}, blocking=True
    )
    ((options,),) = truenas_api.called("update.run")
    assert options == {"reboot": True, "version": "25.10.8"}


async def test_update_status_in_its_error_shape_offers_nothing(
    hass, truenas_api, setup
):
    """update.status reports a failed check as code ERROR with `status: null`."""
    truenas_api.responses["update.status"] = {
        "code": "ERROR",
        "error": "Unable to reach the update server",
        "status": None,
        "update_download_progress": None,
    }
    await setup()
    st = hass.states.get(SYSTEM_UPDATE)
    assert st.state == "off" and st.attributes["latest_version"] == "25.10.7"
