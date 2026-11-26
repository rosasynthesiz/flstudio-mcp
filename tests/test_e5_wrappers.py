"""E-5 wrapper tools: preset navigation, color reads, undo, api_probe.

Everything is driven through a fake bridge -- no FL needed. The point of
these tests is the wrapper contract: which command/params go out, what the
response adds (warnings, last_rollback, fresh re-read), and the probe's
full-envelope budget.
"""
from __future__ import annotations

import json

import pytest
from fastmcp import Client

from fl_studio_mcp import protocol
from fl_studio_mcp.server import build_server
from fl_studio_mcp.tools import color, preset, probe, undo
from tests.conftest import FakeBridge


class OpBridge(FakeBridge):
    """FakeBridge that keys replies by (command, op) when needed."""

    def __init__(self, by_op=None, replies=None):
        super().__init__(replies)
        self.by_op = by_op or {}

    def call(self, command, params=None):
        params = dict(params or {})
        self.calls.append((command, params))
        key = (command, params.get("op"))
        if key in self.by_op:
            r = self.by_op[key]
            if isinstance(r, list):
                return r.pop(0) if len(r) > 1 else r[0]
            return dict(r) if isinstance(r, dict) else r
        r = self.replies.get(command)
        if r is None:
            return {}
        if isinstance(r, list):
            return r.pop(0) if len(r) > 1 else r[0]
        return dict(r) if isinstance(r, dict) else r


async def _call(tool, arguments):
    async with Client(build_server()) as client:
        return (await client.call_tool(tool, arguments)).data


@pytest.fixture
def bridge(monkeypatch):
    b = OpBridge()
    for module in (preset, probe, undo, color):
        monkeypatch.setattr(module, "get_bridge", lambda: b)
    return b


# -- color reads -------------------------------------------------------------

@pytest.mark.asyncio
async def test_color_readers_call_the_existing_commands(bridge):
    bridge.replies[protocol.CMD_CHANNEL_GET_COLOR] = {
        "channel": 3, "color": {"int": 0x14FF14, "hex": "#14FF14",
                                "r": 20, "g": 255, "b": 20}}
    bridge.replies[protocol.CMD_MIXER_GET_COLOR] = {
        "track": 1, "color": {"int": 0xE53935, "hex": "#E53935",
                              "r": 229, "g": 57, "b": 53}}
    ch = await _call("fl_get_channel_color", {"channel": 3})
    tr = await _call("fl_get_track_color", {"track": 1})
    assert ch["color"]["hex"] == "#14FF14"
    assert tr["color"]["hex"] == "#E53935"
    assert bridge.calls_to(protocol.CMD_CHANNEL_GET_COLOR) == [{"channel": 3}]
    assert bridge.calls_to(protocol.CMD_MIXER_GET_COLOR) == [{"track": 1}]


# -- preset navigation -------------------------------------------------------

@pytest.mark.asyncio
async def test_preset_info_is_a_single_read(bridge):
    bridge.replies[protocol.CMD_PLUGIN_PRESET] = {
        "preset_count": 13, "plugin_name": "Fruity Parametric EQ 2",
        "name_f3": "", "name_f6": "Mix EQ"}
    out = await _call("fl_plugin_preset", {"track": 1, "slot": 0})
    assert out["preset_count"] == 13
    assert out["name_f6"] == "Mix EQ"
    assert len(bridge.calls_to(protocol.CMD_PLUGIN_PRESET)) == 1


@pytest.mark.asyncio
async def test_preset_nav_has_no_rollback_and_re_reads(bridge):
    bridge.by_op = {
        (protocol.CMD_PLUGIN_PRESET, "next"): {"track": 1, "slot": 0,
                                              "op": "next", "preset_count": 13},
        (protocol.CMD_PLUGIN_PRESET, "info"): {"track": 1, "slot": 0,
                                               "op": "info", "name_f6": "Bass"},
    }
    out = await _call("fl_plugin_preset", {"track": 1, "slot": 0, "op": "next"})
    assert out["ok"] is True
    assert out["rollback"] == "none"
    assert "NOT covered" in out["warning"]
    assert out["current"]["name_f6"] == "Bass"
    ops = [p["op"] for p in bridge.calls_to(protocol.CMD_PLUGIN_PRESET)]
    assert ops == ["next", "info"]


@pytest.mark.asyncio
async def test_preset_nav_error_is_soft(bridge):
    bridge.replies[protocol.CMD_PLUGIN_PRESET] = {
        "track": 1, "slot": 0, "op": "prev",
        "nav_error": "prevPreset: walled off"}
    out = await _call("fl_plugin_preset", {"track": 1, "slot": 0, "op": "prev"})
    assert out["ok"] is False
    assert out["nav"]["nav_error"].startswith("prevPreset")
    assert "warning" in out
    assert len(bridge.calls_to(protocol.CMD_PLUGIN_PRESET)) == 1


# -- undo --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_undo_surfaces_last_rollback_and_warning(bridge, changelog):
    changelog.append({"tool": "mixer_set_volume", "scope": "mixer:5",
                      "ts": 1000.0})
    bridge.replies[protocol.CMD_UNDO] = {"ok": True, "undid": True}
    out = await _call("fl_undo", {})
    assert out["ok"] is True
    assert "do NOT commute" in out["warning"]
    assert out["last_rollback"]["tool"] == "mixer_set_volume"
    assert out["last_rollback"]["scope"] == "mixer:5"
    assert out["last_rollback"]["age_s"] > 0
    assert bridge.calls_to(protocol.CMD_UNDO) == [{}]


@pytest.mark.asyncio
async def test_undo_with_empty_changelog_has_no_last_rollback(bridge, changelog):
    bridge.replies[protocol.CMD_UNDO] = {"ok": False, "error": "undoUp: nope"}
    out = await _call("fl_undo", {})
    assert out["ok"] is False
    assert out["last_rollback"] is None
    assert "error" in out


# -- api_probe ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_probe_without_pattern_passes_one_page(bridge):
    bridge.replies[protocol.CMD_API_PROBE] = {
        "module": "plugins", "total": 3, "start": 0,
        "next_start": None, "names": ["getPresetCount", "nextPreset"]}
    out = await _call("fl_api_probe", {"module": "plugins"})
    assert out["names"] == ["getPresetCount", "nextPreset"]
    assert bridge.calls_to(protocol.CMD_API_PROBE) == [
        {"op": "dir", "module": "plugins", "start": 0}]


@pytest.mark.asyncio
async def test_probe_pattern_walks_every_page_and_filters(bridge):
    bridge.replies[protocol.CMD_API_PROBE] = [
        {"total": 5, "names": ["alpha", "setPreset"], "next_start": 2},
        {"total": 5, "names": ["nextPreset", "beta"], "next_start": 4},
        {"total": 5, "names": ["gamma"], "next_start": None},
    ]
    out = await _call("fl_api_probe", {"module": "plugins",
                                       "pattern": "preset"})
    assert out["match_count"] == 2
    assert out["names"] == ["setPreset", "nextPreset"]
    assert out["truncated"] is False
    starts = [p["start"] for p in bridge.calls_to(protocol.CMD_API_PROBE)]
    assert starts == [0, 2, 4]


@pytest.mark.asyncio
async def test_probe_filter_budgets_the_whole_envelope(bridge):
    long_names = ["preset" + "x" * 40 for _ in range(40)]
    bridge.replies[protocol.CMD_API_PROBE] = {
        "total": 40, "names": long_names, "next_start": None}
    out = await _call("fl_api_probe", {"module": "plugins",
                                       "pattern": "preset"})
    assert out["truncated"] is True
    assert 0 < len(out["names"]) < 40
    assert out["match_count"] == 40
    envelope = dict(out)
    assert len(json.dumps(envelope, separators=(",", ":"))) <= 600
