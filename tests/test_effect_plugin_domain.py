#!/usr/bin/env python3
"""Focused tests for consolidated effect and plugin domain tools (Slice 09)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol, safety  # noqa: E402
from fl_studio_mcp.tools import effect as effect_domain_tools  # noqa: E402
from fl_studio_mcp.tools import plugin_domain as plugin_domain_tools  # noqa: E402


class FakeBridge:
    def __init__(self) -> None:
        self.slots: dict[tuple[int, int], dict] = {
            (1, 0): {"track": 1, "slot": 0, "plugin": "Fruity EQ 2", "mix": 0.8, "enabled": True},
            (1, 1): {
                "track": 1,
                "slot": 1,
                "plugin": "Fruity Limiter",
                "mix": 0.7,
                "enabled": True,
            },
        }
        self.track_slots_enabled = {1: True}
        self.eq = {
            1: {
                "track": 1,
                "bands": [
                    {"band": 0, "gain": 0.5, "frequency": 0.25, "bandwidth": 0.5, "type": 0},
                    {"band": 1, "gain": 0.5, "frequency": 0.5, "bandwidth": 0.5, "type": 0},
                    {"band": 2, "gain": 0.5, "frequency": 0.75, "bandwidth": 0.5, "type": 0},
                ],
            }
        }
        self.params = {
            (1, 0, 2): {"i": 2, "name": "Band 4 level", "v": 0.5, "s": "0.0 dB"},
            (1, 0, 3): {"i": 3, "name": "Band 4 freq", "v": 0.4, "s": "500 Hz"},
        }
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((command, params))

        if command == protocol.CMD_GET_PROJECT_STATE:
            return {"mixer_track_count": 2}

        if command == protocol.CMD_MIXER_GET_SLOT:
            return dict(
                self.slots.get(
                    (params["track"], params["slot"]),
                    {
                        "track": params["track"],
                        "slot": params["slot"],
                        "plugin": "",
                        "mix": 0.8,
                        "enabled": True,
                    },
                )
            )

        if command == protocol.CMD_MIXER_SET_SLOT_MIX:
            slot = self.slots[(params["track"], params["slot"])]
            slot["mix"] = params["mix"]
            return {"track": params["track"], "slot": params["slot"], "mix": slot["mix"]}

        if command == protocol.CMD_MIXER_SET_SLOT_ENABLED:
            slot = self.slots[(params["track"], params["slot"])]
            slot["enabled"] = params["enabled"]
            return {"track": params["track"], "slot": params["slot"], "enabled": slot["enabled"]}

        if command == protocol.CMD_MIXER_GET_TRACK_SLOTS:
            return {"track": params["track"], "enabled": self.track_slots_enabled[params["track"]]}

        if command == protocol.CMD_MIXER_SET_TRACK_SLOTS:
            self.track_slots_enabled[params["track"]] = params["enabled"]
            return {"track": params["track"], "enabled": params["enabled"]}

        if command == protocol.CMD_MIXER_GET_EQ:
            return json.loads(json.dumps(self.eq[params["track"]]))

        if command == protocol.CMD_MIXER_SET_EQ:
            eq_state = self.eq[params["track"]]
            band = next(row for row in eq_state["bands"] if row["band"] == params["band"])
            for key in ("gain", "frequency", "bandwidth", "type"):
                if key in params:
                    band[key] = params[key]
            return dict(band)

        if command == protocol.CMD_PLUGIN_LIST:
            return {
                "track": params["track"],
                "slots": [{"slot": 0, "name": "Fruity Parametric EQ 2"}],
            }

        if command == protocol.CMD_PLUGIN_GET_PARAMS:
            rows = [
                dict(row)
                for (track, slot, _idx), row in self.params.items()
                if track == params["track"] and slot == params["slot"]
            ]
            return {"total": len(rows), "params": rows, "next_start": None}

        if command == protocol.CMD_PLUGIN_GET_PARAM:
            return dict(self.params[(params["track"], params["slot"], params["param"])])

        if command == protocol.CMD_PLUGIN_SET_PARAM:
            row = self.params[(params["track"], params["slot"], params["param"])]
            row["v"] = round(float(params["value"]), 4)
            row["s"] = f"{row['v']:.4f}"
            return dict(row)

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
def domain_mcp(monkeypatch, tmp_path):
    bridge = FakeBridge()
    monkeypatch.setattr(effect_domain_tools, "get_bridge", lambda: bridge)
    monkeypatch.setattr(plugin_domain_tools, "get_bridge", lambda: bridge)
    safety._log = safety.ChangeLog(tmp_path / "changes.jsonl")
    mcp = FastMCP(name="effect-plugin-test")
    effect_domain_tools.register(mcp)
    plugin_domain_tools.register(mcp)
    return mcp, bridge


def _call_effect(mcp: FastMCP, action: str, params: dict | None = None):
    args = {"action": action}
    if params is not None:
        args["params"] = params
    return _unwrap(asyncio.run(mcp.call_tool("fl_effect", args)))


def _call_plugin(mcp: FastMCP, action: str, params: dict | None = None):
    args = {"action": action}
    if params is not None:
        args["params"] = params
    return _unwrap(asyncio.run(mcp.call_tool("fl_plugin", args)))


def test_effect_domain_reads_slot_and_native_eq(domain_mcp) -> None:
    mcp, bridge = domain_mcp

    slot = _call_effect(mcp, "get_slot", {"track": 1, "slot": 0})
    eq = _call_effect(mcp, "get_eq", {"track": 1})

    assert slot["plugin"] == "Fruity EQ 2"
    assert eq["bands"][1]["frequency"] == pytest.approx(0.5)
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_MIXER_GET_SLOT in commands
    assert protocol.CMD_MIXER_GET_EQ in commands


def test_effect_domain_writes_slot_mix_and_eq_band(domain_mcp) -> None:
    mcp, bridge = domain_mcp

    mix = _call_effect(mcp, "set_slot_mix", {"track": 1, "slot": 0, "mix": 0.25})
    eq = _call_effect(mcp, "set_eq_band", {"track": 1, "band": 1, "gain": 0.6})

    assert mix["ok"] is True
    assert mix["before"]["mix"] == pytest.approx(0.8)
    assert mix["after"]["mix"] == pytest.approx(0.25)
    assert eq["ok"] is True
    assert bridge.eq[1]["bands"][1]["gain"] == pytest.approx(0.6)


def test_plugin_domain_lists_and_reads_params(domain_mcp) -> None:
    mcp, bridge = domain_mcp

    listed = _call_plugin(mcp, "list", {"track": 1})
    params = _call_plugin(mcp, "list_params", {"track": 1, "slot": 0})
    one = _call_plugin(mcp, "get_param", {"track": 1, "slot": 0, "param": "Band 4 level"})

    assert listed["slots"][0]["name"] == "Fruity Parametric EQ 2"
    assert params["total"] == 2
    assert one["param_index"] == 2
    assert one["value"] == pytest.approx(0.5)
    commands = [cmd for cmd, _ in bridge.calls]
    assert protocol.CMD_PLUGIN_LIST in commands
    assert protocol.CMD_PLUGIN_GET_PARAMS in commands
    assert protocol.CMD_PLUGIN_GET_PARAM in commands


def test_plugin_domain_writes_concrete_param_with_rollback(domain_mcp) -> None:
    mcp, bridge = domain_mcp

    result = _call_plugin(mcp, "set_param", {"track": 1, "slot": 0, "param": 2, "value": 0.75})

    assert result["ok"] is True
    assert result["before"]["v"] == pytest.approx(0.5)
    assert result["after"]["v"] == pytest.approx(0.75)
    assert result["resolved_param"] == {"index": 2, "name": "Band 4 level"}
    assert bridge.params[(1, 0, 2)]["v"] == pytest.approx(0.75)


def test_effect_and_plugin_domains_reject_invalid_actions(domain_mcp) -> None:
    mcp, _bridge = domain_mcp

    with pytest.raises(Exception, match="unknown operation: effect.not_an_action"):
        _call_effect(mcp, "not_an_action", {"track": 1})

    with pytest.raises(Exception, match="unknown operation: plugin.not_an_action"):
        _call_plugin(mcp, "not_an_action", {"track": 1})


def test_effect_and_plugin_domains_reject_invalid_parameters(domain_mcp) -> None:
    mcp, _bridge = domain_mcp

    with pytest.raises(Exception, match="mix must be 0..1"):
        _call_effect(mcp, "set_slot_mix", {"track": 1, "slot": 0, "mix": 1.5})

    with pytest.raises(Exception, match="value must be 0..1"):
        _call_plugin(mcp, "set_param", {"track": 1, "slot": 0, "param": 2, "value": 1.5})


def test_plugin_domain_rejects_plugin_loading(domain_mcp) -> None:
    mcp, _bridge = domain_mcp

    with pytest.raises(Exception, match="plugin loading or insertion is unsupported"):
        _call_plugin(mcp, "load", {"track": 1, "slot": 0, "plugin": "Fruity Limiter"})
