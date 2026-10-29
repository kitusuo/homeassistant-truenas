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
