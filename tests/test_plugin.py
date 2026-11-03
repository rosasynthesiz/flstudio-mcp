"""Unit tests for resolve_param_index (E-1 batch foundation)."""

from __future__ import annotations

import pytest

from fl_studio_mcp import protocol
from fl_studio_mcp.tools.plugin import ParamNotFound, resolve_param_index

PARAMS = [
    {"i": 3, "name": "Gain", "v": 0.5},
    {"i": 7, "name": "Freq", "v": 0.4},
    {"i": 9, "name": "Q", "v": 0.3},
    {"i": 11, "name": "Mode", "v": 0.0},
    {"i": 12, "name": "Gain Trim", "v": 0.5},
]


def _bridge_with_params():
    from tests.conftest import FakeBridge
    b = FakeBridge({
        protocol.CMD_PLUGIN_GET_PARAM: {"i": 3, "name": "Gain"},
        protocol.CMD_PLUGIN_GET_PARAMS: {"total": len(PARAMS), "params": PARAMS},
    })
    return b


def test_int_index_used_directly():
    b = _bridge_with_params()
    idx, name = resolve_param_index(b, 1, 0, 5)
    assert idx == 5
    # one lookup for the name
    assert b.calls_to(protocol.CMD_PLUGIN_GET_PARAM)[0]["param"] == 5


def test_int_like_string():
    b = _bridge_with_params()
    idx, _ = resolve_param_index(b, 1, 0, "12")
    assert idx == 12


def test_exact_name_match():
    b = _bridge_with_params()
    idx, name = resolve_param_index(b, 1, 0, "Freq")
    assert (idx, name) == (7, "Freq")


def test_unique_substring_match():
    b = _bridge_with_params()
    idx, name = resolve_param_index(b, 1, 0, "req")    # -> Freq only
    assert (idx, name) == (7, "Freq")


def test_ambiguous_name_raises():
    b = _bridge_with_params()
    with pytest.raises(ParamNotFound, match="matches several"):
        resolve_param_index(b, 1, 0, "gai")     # Gain AND Gain Trim


def test_missing_name_raises_with_candidates():
    b = _bridge_with_params()
    with pytest.raises(ParamNotFound, match="no param named"):
        resolve_param_index(b, 1, 0, "Resonance")


def test_bool_rejected():
    b = _bridge_with_params()
    with pytest.raises(ParamNotFound, match="bool"):
        resolve_param_index(b, 1, 0, True)


def test_paginated_param_list_is_fetched():
    from tests.conftest import FakeBridge
    page1 = {"total": 4, "start": 0, "next_start": 2,
             "params": PARAMS[:2]}
    page2 = {"total": 4, "start": 2, "next_start": None,
             "params": PARAMS[2:]}
    b = FakeBridge({protocol.CMD_PLUGIN_GET_PARAMS: [page1, page2]})
    idx, name = resolve_param_index(b, 1, 0, "Q")
    assert (idx, name) == (9, "Q")
    assert len(b.calls_to(protocol.CMD_PLUGIN_GET_PARAMS)) == 2
