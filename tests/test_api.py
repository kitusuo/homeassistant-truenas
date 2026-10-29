"""TrueNASAPI — the JSON-RPC client over websockets, against a fake socket (no network)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from custom_components.truenas import api as api_mod
from custom_components.truenas.api import TrueNASAPI


class FakeSocket:
    """A websocket that answers each `send` with the next queued reply."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent: list[dict] = []
        self.closed = False

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def recv(self) -> str:
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    def close(self) -> None:
        self.closed = True


def connected_api(*replies, login=True) -> tuple[TrueNASAPI, FakeSocket]:
    sock = FakeSocket([{"jsonrpc": "2.0", "id": 0, "result": login}, *replies])
    api = TrueNASAPI("nas.example.invalid", "key", verify_ssl=True)
    with patch.object(api_mod, "connect", return_value=sock):
        api.connect()
    return api, sock


def test_the_ssl_context_follows_verify_ssl():
    strict = TrueNASAPI("h", "k", verify_ssl=True)._ssl_context
    loose = TrueNASAPI("h", "k", verify_ssl=False)._ssl_context
    assert strict.check_hostname and strict.verify_mode.name == "CERT_REQUIRED"
    assert not loose.check_hostname and loose.verify_mode.name == "CERT_NONE"


def test_connect_logs_in_with_the_api_key():
    api, sock = connected_api()
    assert api.connected()
    assert sock.sent[0] == {
        "method": "auth.login_with_api_key",
        "jsonrpc": "2.0",
        "id": 0,
        "params": ["key"],
    }


def test_a_refused_key_is_not_connected_and_says_why():
    api, _ = connected_api(login=False)
    assert not api.connected()
    assert api.error == "invalid_key"


def test_a_login_that_breaks_is_not_connected():
    sock = FakeSocket([OSError("reset")])
    api = TrueNASAPI("h", "k")
    with patch.object(api_mod, "connect", return_value=sock):
        assert api.connect() is False
    assert not api.connected()


@pytest.mark.parametrize(
    "message, error",
    [
        (
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
            "certificate_verify_failed",
        ),
        ("The plain HTTP request was sent to HTTPS port", "http_used"),
        ("[SSL: TLSV1_UNRECOGNIZED_NAME]", "tlsv1_not_supported"),
        ("No WebSocket UPGRADE header", "websocket_not_supported"),
        ("Name or service not known", "invalid_hostname"),
        ("server rejected WebSocket connection: HTTP 404", "api_not_found"),
    ],
)
def test_a_failed_connection_is_classified_for_the_config_flow(message, error):
    api = TrueNASAPI("h", "k")
    with patch.object(api_mod, "connect", side_effect=OSError(message)):
        assert api.connect() is False
    assert api.error == error


@pytest.mark.parametrize(
    "arg, error",
    [
        ("No address associated with hostname", "unknown_hostname"),
        ("Connection refused", "connection_refused"),
        ("No route to host", "invalid_hostname"),
        ("timed out while waiting for handshake response", "handshake_timeout"),
    ],
)
def test_errors_matched_on_the_exception_argument(arg, error):
    api = TrueNASAPI("h", "k")
    with patch.object(api_mod, "connect", side_effect=OSError(arg)):
        api.connect()
    assert api.error == error


def test_the_connect_error_is_logged_once_until_a_success(caplog):
    api = TrueNASAPI("h", "k")
    with patch.object(api_mod, "connect", side_effect=OSError("down")):
        api.connect()
        api.connect()
    assert caplog.text.count("failed to connect") == 1


def test_query_returns_the_result_and_sends_params_as_a_list():
    api, sock = connected_api(
        {"jsonrpc": "2.0", "id": 0, "result": {"version": "25.10.7"}},
        {"jsonrpc": "2.0", "id": 0, "result": [1]},
    )
    assert api.query("system.info") == {"version": "25.10.7"}
    assert sock.sent[-1]["params"] == []
    assert api.query("core.get_jobs", {"x": 1}) == [1]
    assert sock.sent[-1]["params"] == [{"x": 1}]


def test_query_logs_an_error_reply_and_returns_it(caplog):
    reply = {
        "jsonrpc": "2.0",
        "id": 0,
        "error": {
            "code": -32601,
            "message": "Method does not exist",
            "data": {"reason": "no such method"},
        },
    }
    api, _ = connected_api(
        reply, {"jsonrpc": "2.0", "id": 0, "error": {"code": 1, "message": "plain"}}
    )
    assert api.query("update.check_available")["error"]["code"] == -32601
    assert api.error == "malformed_result"
    assert "no such method" in caplog.text
    api.query("x")
    assert "plain" in caplog.text


def test_a_non_json_reply_is_returned_as_text():
    api, _ = connected_api("not json")
    assert api.query("x") == "not json"


def test_a_broken_socket_disconnects_and_returns_none():
    api, sock = connected_api(OSError("broken pipe"))
    assert api.query("system.info") is None
    assert not api.connected() and sock.closed
    assert api.error == "broken pipe"


def test_query_reconnects_when_disconnected():
    api, _ = connected_api()
    api.disconnect()
    sock = FakeSocket([{"result": True}, {"result": "ok"}])
    with patch.object(api_mod, "connect", return_value=sock):
        assert api.query("x") == "ok"
    assert api.connected()


def test_reconnect_and_connection_test():
    api, _ = connected_api()
    sock = FakeSocket([{"result": True}, {"result": {"version": "1"}}])
    with patch.object(api_mod, "connect", return_value=sock):
        assert api.reconnect() is True
    sock = FakeSocket([{"result": True}, {"result": {"version": "1"}}])
    with patch.object(api_mod, "connect", return_value=sock):
        assert api.connection_test() == (True, "")
