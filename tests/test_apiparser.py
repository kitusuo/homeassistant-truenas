"""apiparser — turning TrueNAS's JSON into the coordinator's flat dicts."""

from datetime import timezone

from custom_components.truenas import apiparser as P


def test_from_entry_reads_nested_paths_and_rounds_floats():
    entry = {"a": {"b": {"c": 1.23456}}, "s": "x" * 300}
    assert P.from_entry(entry, "a/b/c", default=0) == 1.23
    assert P.from_entry(entry, "a/missing/c", default="none") == "none"
    assert P.from_entry(entry, "missing", default=5) == 5
    assert P.from_entry(entry, "s") == "x" * 255, "strings are capped at 255 characters"
    assert P.from_entry({"n": 7}, "n", default=0) == 7


def test_from_entry_bool_reads_words_and_reverses():
    assert P.from_entry_bool({"v": "ON"}, "v") is True
    assert P.from_entry_bool({"v": "down"}, "v") is False
    assert P.from_entry_bool({"v": True}, "v", reverse=True) is False
    assert P.from_entry_bool({"v": "maybe"}, "v", default=True) is True
    assert P.from_entry_bool({"a": {"b": True}}, "a/b") is True
    assert P.from_entry_bool({"a": 1}, "a/b", default=True) is True
    assert P.from_entry_bool({}, "v") is False


def test_utc_from_timestamp():
    assert P.utc_from_timestamp(0).tzinfo is not None
    assert P.utc_from_timestamp(86400).astimezone(timezone.utc).day == 2


def test_parse_api_keyed_list_with_ensure_and_proc():
    out = P.parse_api(
        data={},
        source=[{"id": "a", "n": 1, "on": "yes"}, {"id": "b", "n": 2}, {"n": 3}],
        key="id",
        vals=[{"name": "n", "default": 0}, {"name": "on", "type": "bool"}],
        ensure_vals=[{"name": "extra", "default": "x"}],
        # combine reads the PARSED fields (n), not the source entry; a missing one reads "unknown"
        val_proc=[
            [
                {"name": "label"},
                {"action": "combine"},
                {"key": "n"},
                {"text": "-"},
                {"key": "nope"},
            ]
        ],
    )
    assert out == {
        "a": {"n": 1, "on": True, "extra": "x", "label": "1-unknown"},
        "b": {"n": 2, "on": False, "extra": "x", "label": "2-unknown"},
    }


def test_parse_api_single_dict_and_timestamps():
    out = P.parse_api(
        data={},
        source={"t": 1700000000000, "u": 1700000000},
        vals=[
            {"name": "t", "default": 0, "convert": "utc_from_timestamp"},
            {"name": "u", "default": 0, "convert": "utc_from_timestamp"},
        ],
        ensure_vals=[{"name": "e"}],
    )
    assert out["t"].year == 2023 and out["u"].year == 2023 and out["e"] == ""


def test_parse_api_keyed_timestamps():
    out = P.parse_api(
        data={},
        source=[{"id": 1, "t": 1700000000000}],
        key="id",
        vals=[{"name": "t", "default": 0, "convert": "utc_from_timestamp"}],
    )
    assert out[1]["t"].year == 2023


def test_parse_api_without_a_source_fills_defaults():
    out = P.parse_api(
        data={},
        source=None,
        vals=[
            {"name": "s", "default": "d"},
            {"name": "b", "type": "bool", "default": True},
            {"name": "v", "default_val": "alt", "alt": "from-alt"},
        ],
    )
    assert out == {"s": "d", "b": True, "v": "from-alt"}
    assert P.parse_api(data={"k": 1}, source=[], key="id") == {"k": 1}


def test_parse_api_only_skip_and_secondary_keys():
    src = [
        {"id": "", "alt": "x", "type": "A"},
        {"id": "y", "type": "B"},
        {"alt": "z", "type": "A"},
        {"type": "A"},
        {"id": "w", "type": "A", "hidden": True},
    ]
    out = P.parse_api(
        data={},
        source=src,
        key="id",
        key_secondary="alt",
        vals=[{"name": "type"}],
        only=[{"key": "type", "value": "A"}],
        skip=[{"name": "hidden", "value": True}],
    )
    assert set(out) == {
        "z"
    }, "only type A; an empty primary key skips; hidden is skipped"
    out = P.parse_api(
        data={},
        source=[{"type": "A"}],
        key="id",
        vals=[{"name": "type"}],
        skip=[{"name": "id", "value": ""}],
    )
    assert out == {}, "a skip with an empty value skips entries lacking the key"


def test_parse_api_key_search_maps_onto_existing_uids():
    data = {"u1": {"name": "eth0"}}
    out = P.parse_api(
        data=data,
        source=[{"name": "eth0", "rx": 5}, {"name": "eth9", "rx": 1}],
        key_search="name",
        vals=[{"name": "rx", "default": 0}],
    )
    assert out == {"u1": {"name": "eth0", "rx": 5}}


def test_parse_api_logs_in_debug(caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger=P.__name__)
    P.parse_api(
        data={},
        source=[{"id": 1, "password": "s3cret"}],
        key="id",
        vals=[{"name": "id"}],
    )
    assert "Processing entry" in caplog.text and "s3cret" not in caplog.text
