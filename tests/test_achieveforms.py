"""The AchieveForms reply readers: rows, first_row, data_rows and page_session_id."""

from __future__ import annotations

import pytest

from api.councils._base import UpstreamError
from api.councils._platforms.achieveforms import (
    data_rows,
    first_row,
    page_session_id,
    rows,
)

pytestmark = pytest.mark.ci


def _reply(rows_data: object) -> dict:
    return {"integration": {"transformed": {"rows_data": rows_data}}}


def test_rows_returns_the_dict_and_empty_for_no_rows():
    assert rows(_reply({"0": {"a": "1"}})) == {"0": {"a": "1"}}
    assert rows(_reply({})) == {}
    assert rows(_reply([])) == {}
    assert rows({"integration": {"transformed": {}}}) == {}


def test_rows_keys_a_list_by_position_or_by_a_field():
    data = [{"name": "x", "v": 1}, {"name": "y", "v": 2}]
    assert list(rows(_reply(data))) == ["0", "1"]
    assert list(rows(_reply(data), key="name")) == ["x", "y"]


@pytest.mark.parametrize(
    "reply",
    [
        {"result": "logout"},
        {"status": "error"},
        {"integration": {}},
        {"integration": {"transformed": {"error": "boom"}}},
        _reply("not rows"),
        [],
    ],
)
def test_rows_raises_upstream_error_for_a_reply_without_rows(reply):
    with pytest.raises(UpstreamError):
        rows(reply)


def test_first_row():
    assert first_row(_reply({"0": {"a": "1"}})) == {"a": "1"}
    assert first_row(_reply({})) is None
    with pytest.raises(UpstreamError):
        first_row(_reply({"0": "text"}))


def test_data_rows_reads_each_row_of_the_xml():
    xml = (
        '<?xml version="1.0"?><Responses><RequestResponse><DatabaseResponse><Rows>'
        '<Row id="0"><result column="a" IsNull="false">1</result><result column="b" isNull="True"/></Row>'
        '<Row id="1"><result column="a" IsNull="false">x &amp; y</result></Row>'
        "</Rows></DatabaseResponse></RequestResponse></Responses>"
    )
    assert data_rows({"data": xml}) == [{"a": "1", "b": ""}, {"a": "x & y"}]
    assert data_rows({}) == []
    assert data_rows({"data": "<Responses/>"}) == []


def test_data_rows_falls_back_to_a_pattern_for_broken_xml():
    xml = '<Rows><Row id="0"><result column="a" IsNull="false">Black & Blue</result></Row></Rows>'
    assert data_rows({"data": xml}) == [{"a": "Black & Blue"}]


def test_data_rows_raises_on_logout():
    with pytest.raises(UpstreamError):
        data_rows({"result": "logout"})


def test_page_session_id():
    assert page_session_id('var x = {"auth-session":"abc123", "y": 1}') == "abc123"
    assert page_session_id("{'auth-session' : 'def'}") == "def"
    with pytest.raises(UpstreamError):
        page_session_id("<html></html>")
