#!/usr/bin/env python3
"""Focused tests for the consolidated channel domain tool (Slice 07)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol, safety  # noqa: E402
from fl_studio_mcp.tools import channel as channel_domain_tools  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal fake bridge
# ---------------------------------------------------------------------------


class FakeBridge:
    def __init__(self) -> None:
        self.channels: dict[int, dict] = {
            0: {
                "name": "Kick",
                "vol_norm": 0.8,
                "pan": 0.0,
                "mute": False,
                "solo": False,
                "target_fx_track": 1,
                "color": {"int": 0xFF0000},
                "type": {"label": "sampler"},
            },
            1: {
                "name": "Snare",
                "vol_norm": 0.6,
                "pan": 0.0,
                "mute": False,
                "solo": False,
                "target_fx_track": 2,
                "color": {"int": 0x00FF00},
                "type": {"label": "sampler"},
            },
        }
        self.selected_channel = 0
        self.steps: dict[tuple[int, int], dict] = {}
        self.selected_pattern = 1
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((command, params))

        if command == protocol.CMD_CHANNEL_LIST:
            channels = [{"i": i, "name": c["name"]} for i, c in self.channels.items()]
            return {"total": len(channels), "channels": channels, "next_start": None}

        if command == protocol.CMD_CHANNEL_GET:
            idx = params.get("index", 0)
            if idx not in self.channels:
                raise RuntimeError(f"channel {idx} not found")
            return dict(self.channels[idx])

        if command == protocol.CMD_CHANNEL_SELECTED:
            return {"selected": self.selected_channel}

        if command == protocol.CMD_CHANNEL_SELECT:
            self.selected_channel = params["channel"]
            return {"selected": self.selected_channel}

        if command == protocol.CMD_CHANNEL_SET_NAME:
            ch = params["channel"]
            self.channels[ch]["name"] = params["name"]
            return {"name": self.channels[ch]["name"]}

        if command == protocol.CMD_CHANNEL_SET_VOLUME:
            ch = params["channel"]
            self.channels[ch]["vol_norm"] = params["value"]
            return {"vol_norm": self.channels[ch]["vol_norm"]}

        if command == protocol.CMD_CHANNEL_SET_PAN:
            ch = params["channel"]
            self.channels[ch]["pan"] = params["value"]
            return {"pan": self.channels[ch]["pan"]}

        if command == protocol.CMD_CHANNEL_SET_MUTE:
            ch = params["channel"]
            self.channels[ch]["mute"] = params["state"]
            return {"mute": self.channels[ch]["mute"]}

        if command == protocol.CMD_CHANNEL_SET_SOLO:
            ch = params["channel"]
            self.channels[ch]["solo"] = params["state"]
            return {"solo": self.channels[ch]["solo"]}

        if command == protocol.CMD_CHANNEL_SET_COLOR:
            ch = params["channel"]
            color_int = params.get("color")
            if color_int is None:
                r, g, b = params["r"], params["g"], params["b"]
                color_int = (r << 16) | (g << 8) | b
            self.channels[ch]["color"] = {"int": color_int}
            return {"color": {"int": color_int}}

        if command == protocol.CMD_CHANNEL_SET_TARGET:
            ch = params["channel"]
            self.channels[ch]["target_fx_track"] = params["track"]
            return {"target_fx_track": self.channels[ch]["target_fx_track"]}

        if command == protocol.CMD_CHANNEL_GET_STEPS:
            ch = params.get("channel", 0)
            pat = params.get("pattern", self.selected_pattern)
            stored = self.steps.get((ch, pat), {})
            n = params.get("steps", 4)
            grid = stored.get("grid", [False] * n)
            return {
                "channel": ch,
                "pattern": pat,
                "grid": grid,
                "vel": stored.get("vel", [1.0] * len(grid)),
                "pan": stored.get("pan", [0.0] * len(grid)),
                "shift": stored.get("shift", [0.0] * len(grid)),
                "rep": stored.get("rep", [0] * len(grid)),
            }

        if command == protocol.CMD_CHANNEL_SET_STEPS:
            ch = params["channel"]
            pat = params.get("pattern", self.selected_pattern)
            steps_input = params.get("steps", [])
            size = max((s.get("step", 0) for s in steps_input), default=0) + 1
            existing = self.steps.get((ch, pat), {})
            grid = list(existing.get("grid", [False] * size))
            vel = list(existing.get("vel", [1.0] * size))
            pan_list = list(existing.get("pan", [0.0] * size))
            shift = list(existing.get("shift", [0.0] * size))
            rep = list(existing.get("rep", [0] * size))
            # Extend to size
            while len(grid) < size:
                grid.append(False)
                vel.append(1.0)
                pan_list.append(0.0)
                shift.append(0.0)
                rep.append(0)
            for s in steps_input:
                idx = s.get("step", 0)
                if "value" in s:
                    grid[idx] = s["value"]
                if "velocity" in s:
                    vel[idx] = s["velocity"]
                if "pan" in s:
                    pan_list[idx] = s["pan"]
                if "shift" in s:
                    shift[idx] = s["shift"]
                if "repeat" in s:
                    rep[idx] = s["repeat"]
            self.steps[(ch, pat)] = {
                "grid": grid,
                "vel": vel,
                "pan": pan_list,
                "shift": shift,
                "rep": rep,
                "pattern": pat,
            }
            return {"ok": True, "channel": ch, "pattern": pat}

        if command == protocol.CMD_PATTERN_SELECTED:
            return {"selected": self.selected_pattern}

        if command == protocol.CMD_CHANNEL_ROUTING_SUMMARY:
            channels = [
                {
                    "channel": i,
                    "name": c["name"],
                    "type": c.get("type", {"label": "unknown"}),
                    "target_mixer_track": c.get("target_fx_track"),
                }
                for i, c in self.channels.items()
            ]
            return {"total": len(channels), "channels": channels, "next_start": None}

        raise AssertionError(f"unexpected command: {command!r} params={params!r}")


def _unwrap(result):
    for attr in ("data", "structured_content", "structuredContent"):
        value = getattr(result, attr, None)
        if value is not None:
            return value
    if isinstance(result, (list, tuple)) and result:
        first = result[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return json.loads(text)
        return _unwrap(first)
    return result


@pytest.fixture
def channel_mcp(monkeypatch, tmp_path):
    bridge = FakeBridge()
    monkeypatch.setattr(channel_domain_tools, "get_bridge", lambda: bridge)
    safety._log = safety.ChangeLog(tmp_path / "changes.jsonl")
    mcp = FastMCP(name="channel-test")
    channel_domain_tools.register(mcp)
    return mcp, bridge


def _call(mcp: FastMCP, action: str, params: dict | None = None):
    args = {"action": action}
    if params is not None:
        args["params"] = params
    return _unwrap(asyncio.run(mcp.call_tool("fl_channel", args)))


# ---------------------------------------------------------------------------
# Tests: read-only actions
# ---------------------------------------------------------------------------


def test_channel_domain_read_list(channel_mcp) -> None:
    mcp, bridge = channel_mcp

    result = _call(mcp, "list")

    assert "channels" in result
    assert result["total"] == 2
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_CHANNEL_LIST in commands


def test_channel_domain_read_get(channel_mcp) -> None:
    mcp, bridge = channel_mcp

    result = _call(mcp, "get", {"channel": 0})

    assert result["name"] == "Kick"
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_CHANNEL_GET in commands


def test_channel_domain_read_get_selected(channel_mcp) -> None:
    mcp, bridge = channel_mcp

    result = _call(mcp, "get_selected")

    assert "selected" in result
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_CHANNEL_SELECTED in commands


def test_channel_domain_classify(channel_mcp) -> None:
    mcp, bridge = channel_mcp

    result = _call(mcp, "classify")

    assert "summary" in result
    assert "groups" in result
    # All test channels are "sampler" type.
    assert "sampler" in result["groups"]
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_CHANNEL_ROUTING_SUMMARY in commands


def test_channel_domain_read_get_steps(channel_mcp) -> None:
    mcp, bridge = channel_mcp

    result = _call(mcp, "get_steps", {"channel": 0, "steps": 4, "pattern": 1})

    assert "grid" in result
    assert len(result["grid"]) == 4
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_CHANNEL_GET_STEPS in commands


# ---------------------------------------------------------------------------
# Tests: safe write actions
# ---------------------------------------------------------------------------


def test_channel_domain_write_set_name(channel_mcp) -> None:
    mcp, bridge = channel_mcp

    result = _call(mcp, "set_name", {"channel": 0, "name": "Bass Drum"})

    assert result["ok"] is True
    assert bridge.channels[0]["name"] == "Bass Drum"


def test_channel_domain_write_set_mixer_target(channel_mcp) -> None:
    mcp, bridge = channel_mcp

    result = _call(mcp, "set_mixer_target", {"channel": 0, "track": 5})

    assert result["ok"] is True
    assert bridge.channels[0]["target_fx_track"] == 5


def test_channel_domain_write_set_steps(channel_mcp) -> None:
    mcp, bridge = channel_mcp

    steps = [{"step": 0, "value": True, "velocity": 0.9}]
    result = _call(mcp, "set_steps", {"channel": 0, "pattern": 1, "steps": steps})

    assert result["ok"] is True
    assert bridge.steps[(0, 1)]["grid"][0] is True
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_CHANNEL_SET_STEPS in commands


# ---------------------------------------------------------------------------
# Tests: invalid action and invalid parameters
# ---------------------------------------------------------------------------


def test_channel_domain_rejects_invalid_action(channel_mcp) -> None:
    mcp, _bridge = channel_mcp

    with pytest.raises(Exception, match="unknown operation: channel.not_an_action"):
        _call(mcp, "not_an_action")


def test_channel_domain_rejects_invalid_parameters(channel_mcp) -> None:
    mcp, _bridge = channel_mcp

    with pytest.raises(Exception, match="channel pan value must be -1..1"):
        _call(mcp, "set_pan", {"channel": 0, "value": 5.0})
