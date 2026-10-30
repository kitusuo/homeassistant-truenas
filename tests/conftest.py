"""Shared fixtures: a fake TrueNAS answering from recorded data, and the integration set up against it.

`tests/fixtures/truenas_25_10.json` is a TrueNAS SCALE 25.10.7 recording, reduced to the
fields this integration reads and scrubbed: names, serials, addresses and secrets are placeholders, mapped
consistently so the joins the integration makes (a dataset's pool, a disk's temperature, an interface's graph) hold.
It is de-fingerprinted too: platform and app details are generic, every timestamp is shifted by one fixed offset and
every byte size is scaled by one factor, so relations hold and the hardware does not show.
A method the recording does not have answers like TrueNAS does for an unknown method: a JSON-RPC error.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.truenas.const import DOMAIN

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

ENTRY_DATA = {
    "name": "TrueNAS",
    "host": "nas.example.invalid",
    "api_key": "test-api-key",
    "verify_ssl": False,
}


def recording(name: str = "truenas_25_10") -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def method_not_found(service: str) -> dict:
    """What TrueNASAPI.query returns for a method the server does not have (the reply carries no "result")."""
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "error": {
            "code": -32601,
            "message": "Method does not exist",
            "data": {"reason": f"Method {service!r} not found"},
        },
    }


class _OneReplySocket:
    """The websocket TrueNASAPI talks to inside FakeTrueNASAPI: answers one send with one reply."""

    def __init__(self, reply: dict):
        self._reply = json.dumps(reply)

    def send(self, message: str) -> None:
        pass

    def recv(self) -> str:
        return self._reply

    def close(self) -> None:
        pass


class FakeTrueNASAPI:
    """Stands in for `custom_components.truenas.api.TrueNASAPI`: same surface, answers from a recording.

    `responses` maps a method to its result, or to a callable `(params) -> result`. Every call is recorded in `calls`.
    """

    def __init__(self, responses: dict[str, Any]):
        self.responses = responses
        self.calls: list[tuple[str, Any]] = []
        self._connected = True
        self.error = ""

    # the constructor signature TrueNASCoordinator / the config flow use
    def __call__(
        self, host: str, api_key: str, verify_ssl: bool = True
    ) -> "FakeTrueNASAPI":
        self.host, self.api_key, self.verify_ssl = host, api_key, verify_ssl
        return self

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def connected(self) -> bool:
        return self._connected

    def connection_test(self) -> tuple[bool, str]:
        return True, ""

    def query(
        self, service: str, params: Any = {}
    ) -> Any:  # noqa: B006 - the real signature
        # recorded as it goes over the wire: TrueNASAPI.query sends `{}` as [] and wraps a non-list in a list
        wire = (
            [] if params == {} else (params if isinstance(params, list) else [params])
        )
        self.calls.append((service, wire))
        if service not in self.responses:
            reply = method_not_found(service)
        else:
            answer = self.responses[service]
            answer = copy.deepcopy(answer(wire) if callable(answer) else answer)
            # a test injects a JSON-RPC error reply (the envelope: "jsonrpc", no "result") as the answer itself.
            # Anything else is a result, even one with an "error" field of its own (25.10's update.status).
            is_error_reply = (
                isinstance(answer, dict)
                and "jsonrpc" in answer
                and "error" in answer
                and "result" not in answer
            )
            reply = (
                answer
                if is_error_reply
                else {"jsonrpc": "2.0", "id": 0, "result": answer}
            )
        return self._through_the_real_client(service, params, reply)

    def _through_the_real_client(self, service: str, params: Any, reply: dict) -> Any:
        """Hand the wire reply to the REAL TrueNASAPI over a one-reply socket, so every test sees exactly what the
        client returns for it (a result, or what it makes of an error reply) and its logging, not a copy of them.
        """
        from custom_components.truenas.api import TrueNASAPI

        client = TrueNASAPI(getattr(self, "host", "?"), "key")
        client._ws = _OneReplySocket(reply)
        client._connected = True
        data = client.query(service, params)
        self.error = client.error
        return data

    def called(self, service: str) -> list[Any]:
        return [p for s, p in self.calls if s == service]


def jobs_from(recorded: list[dict]):
    """core.get_jobs, honouring the `[["id", "=", n]]` filter the integration sends."""

    def answer(params):
        filters = params[0] if params else []
        out = recorded
        for field, op, value in filters:
            assert op == "=", op
            out = [j for j in out if j.get(field) == value]
        return out

    return answer


def graphs_from(recorded: list[dict]):
    """reporting.netdata_get_data returns the graphs ASKED for (by name, and identifier where one is given)."""

    def answer(params):
        wanted = params[0]
        return [
            g
            for g in recorded
            if any(
                w["name"] == g["name"]
                and w.get("identifier", g["identifier"]) == g["identifier"]
                for w in wanted
            )
        ]

    return answer


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/truenas."""
    yield


@pytest.fixture
def truenas_api():
    """The fake TrueNAS, patched in wherever the integration constructs its API."""
    rec = recording()
    responses: dict[str, Any] = {m: v for m, v in rec.items() if m != "core.get_jobs"}
    responses["core.get_jobs"] = jobs_from(rec["core.get_jobs"])
    responses["reporting.netdata_get_data"] = graphs_from(
        rec["reporting.netdata_get_data"]
    )
    api = FakeTrueNASAPI(responses)
    with (
        patch("custom_components.truenas.coordinator.TrueNASAPI", api),
        patch("custom_components.truenas.config_flow.TrueNASAPI", api),
    ):
        yield api


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title="TrueNAS", data=dict(ENTRY_DATA), version=1
    )


@pytest.fixture
async def setup_integration(hass, truenas_api, config_entry):
    """The integration, set up against the fake TrueNAS. Returns the config entry."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def ha_deprecations(monkeypatch):
    """Every deprecation Home Assistant reports while this test runs (its `report_usage`, from the device registry
    and the entity platform). A spy, not the log: the log wording can change, and HA reports each one only once per
    process, so a log check silently passes after an earlier test triggered it."""
    from homeassistant.helpers import device_registry, entity_platform

    seen: list[str] = []

    def spy(what, *args, **kwargs):
        seen.append(str(what))

    monkeypatch.setattr(device_registry, "report_usage", spy)
    monkeypatch.setattr(entity_platform, "report_usage", spy)
    return seen
