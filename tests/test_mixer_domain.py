#!/usr/bin/env python3
"""Focused tests for the consolidated mixer domain tool (Slice 06)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol, safety  # noqa: E402
from fl_studio_mcp.tools import mixer as mixer_tools  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal fake bridge
# ---------------------------------------------------------------------------


class FakeBridge:
    def __init__(self) -> None:
        self.tracks: dict[int, dict] = {
            0: {
                "name": "Master",
                "vol_norm": 0.8,
                "pan": 0.0,
                "mute": False,
                "solo": False,
                "track": 0,
            },
            1: {
                "name": "Track 1",
                "vol_norm": 0.8,
                "pan": 0.0,
                "mute": False,
                "solo": False,
                "track": 1,
            },
        }
        self.selected_track = 0
        self.routes: dict[tuple[int, int], bool] = {}
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((command, params))

        if command == protocol.CMD_GET_PROJECT_STATE:
            return {"mixer_track_count": len(self.tracks)}

        if command == protocol.CMD_MIXER_LIST_TRACKS:
            tracks = list(self.tracks.values())
            return {"total": len(tracks), "tracks": tracks, "next_start": None}

        if command == protocol.CMD_MIXER_GET_TRACK:
            idx = params.get("index", 0)
            if idx not in self.tracks:
                raise RuntimeError(f"track {idx} not found")
            t = dict(self.tracks[idx])
            return t

        if command == protocol.CMD_MIXER_SELECTED:
            return {"track": self.selected_track}

        if command == protocol.CMD_MIXER_SELECT_TRACK:
            self.selected_track = params["track"]
            return {"track": self.selected_track}

        if command == protocol.CMD_MIXER_SET_NAME:
            track = params["track"]
            self.tracks[track]["name"] = params["name"]
            return {"name": self.tracks[track]["name"]}

        if command == protocol.CMD_MIXER_SET_VOLUME:
            track = params["track"]
            self.tracks[track]["vol_norm"] = params["value"]
            return {"vol_norm": self.tracks[track]["vol_norm"]}

        if command == protocol.CMD_MIXER_SET_PAN:
            track = params["track"]
            self.tracks[track]["pan"] = params["value"]
            return {"pan": self.tracks[track]["pan"]}

        if command == protocol.CMD_MIXER_SET_MUTE:
            track = params["track"]
            self.tracks[track]["mute"] = params["state"]
            return {"mute": self.tracks[track]["mute"]}

        if command == protocol.CMD_MIXER_SET_SOLO:
            track = params["track"]
            self.tracks[track]["solo"] = params["state"]
            return {"solo": self.tracks[track]["solo"]}

        if command == protocol.CMD_MIXER_GET_ROUTING:
            track = params.get("track", 0)
            routes = [
                {"dst": dst, "enabled": enabled}
                for (src, dst), enabled in self.routes.items()
                if src == track
            ]
            return {"track": track, "routes_to": routes}

        if command == protocol.CMD_MIXER_SET_ROUTE:
            key = (params["src"], params["dst"])
            self.routes[key] = params["enabled"]
            return {"src": params["src"], "dst": params["dst"], "enabled": params["enabled"]}

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
def mixer_mcp(monkeypatch, tmp_path):
    bridge = FakeBridge()
    monkeypatch.setattr(mixer_tools, "get_bridge", lambda: bridge)
    monkeypatch.setattr(mixer_tools, "mixer_track_error", lambda *a, **kw: None)
    safety._log = safety.ChangeLog(tmp_path / "changes.jsonl")
    mcp = FastMCP(name="mixer-test")
    mixer_tools.register(mcp)
    return mcp, bridge


def _call(mcp: FastMCP, action: str, params: dict | None = None):
    args = {"action": action}
    if params is not None:
        args["params"] = params
    return _unwrap(asyncio.run(mcp.call_tool("fl_mixer", args)))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mixer_domain_read_list(mixer_mcp) -> None:
    mcp, bridge = mixer_mcp

    result = _call(mcp, "list")

    assert "tracks" in result
    assert result["total"] == 2
    # The list action must have issued CMD_MIXER_LIST_TRACKS.
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_MIXER_LIST_TRACKS in commands


def test_mixer_domain_read_get(mixer_mcp) -> None:
    mcp, bridge = mixer_mcp

    result = _call(mcp, "get", {"track": 1})

    assert result["name"] == "Track 1"
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_MIXER_GET_TRACK in commands


def test_mixer_domain_write_single_property(mixer_mcp) -> None:
    mcp, bridge = mixer_mcp

    result = _call(mcp, "set_name", {"track": 1, "name": "Kick"})

    assert result["ok"] is True
    assert bridge.tracks[1]["name"] == "Kick"


def test_mixer_domain_write_volume(mixer_mcp) -> None:
    mcp, bridge = mixer_mcp

    result = _call(mcp, "set_volume", {"track": 1, "value": 0.5, "unit": "normalized"})

    assert result["ok"] is True
    assert bridge.tracks[1]["vol_norm"] == pytest.approx(0.5)


def test_mixer_domain_route_read(mixer_mcp) -> None:
    mcp, bridge = mixer_mcp

    result = _call(mcp, "get_route", {"track": 0})

    assert "routes_to" in result
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_MIXER_GET_ROUTING in commands


def test_mixer_domain_route_write(mixer_mcp) -> None:
    mcp, bridge = mixer_mcp

    result = _call(mcp, "set_route", {"src": 1, "dst": 0, "enabled": True})

    assert result["ok"] is True
    assert bridge.routes.get((1, 0)) is True


def test_mixer_domain_rejects_invalid_action(mixer_mcp) -> None:
    mcp, _bridge = mixer_mcp

    with pytest.raises(Exception, match="unknown operation: mixer.not_an_action"):
        _call(mcp, "not_an_action")


def test_mixer_domain_rejects_invalid_parameters(mixer_mcp) -> None:
    mcp, _bridge = mixer_mcp

    with pytest.raises(Exception, match="mixer pan value must be -1..1"):
        _call(mcp, "set_pan", {"track": 1, "value": 99.0})
