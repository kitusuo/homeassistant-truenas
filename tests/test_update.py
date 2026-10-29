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
    truenas_api.responses["app.upgrade"] = 9429
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
    truenas_api.responses["app.upgrade"] = 9429
    job = {"id": 9429, "method": "app.upgrade", "state": "RUNNING"}
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
    truenas_api.responses["app.upgrade"] = 9429
    job = {"id": 9429, "method": "app.upgrade", "state": "RUNNING"}
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
    truenas_api.responses["app.upgrade"] = 9429
    truenas_api.responses["core.get_jobs"] = jobs(
        {"id": 9429, "method": "app.upgrade", "state": "RUNNING"}
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
    assert truenas_api.called("update.run") == [[{"reboot": True}]]
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
