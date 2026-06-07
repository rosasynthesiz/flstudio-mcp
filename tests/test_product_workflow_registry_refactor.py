#!/usr/bin/env python3
"""Focused tests for product workflow registry-backed write preparation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol, safety  # noqa: E402
from fl_studio_mcp.tools import mix_doctor, project_organizer, routing  # noqa: E402

_P = _F = 0


class MockMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, annotations=None):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


class MixFixBridge:
    def __init__(self) -> None:
        self.track = {"index": 4, "name": "Lead", "vol_norm": 0.75, "vol_db": -1.0}
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((command, params))
        if command == protocol.CMD_MIXER_GET_TRACK:
            return dict(self.track)
        if command == protocol.CMD_MIXER_SET_VOLUME:
            assert params["track"] == 4
            self.track["vol_db"] = float(params["value"])
            self.track["vol_norm"] = 0.5
            return dict(self.track)
        raise AssertionError(f"unexpected command: {command!r} params={params!r}")


def check(label, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1
    else:
        _F += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{'  -- ' + detail if detail else ''}")


def _ref_ids(result):
    return {row.get("id") for row in result.get("kb_policy_refs", [])}


def test_routing_write_entries_are_registry_prepared() -> None:
    route = routing._route_write_entry(2, 0, False)
    assert route["snap_scope"] == "route:2:0"
    assert route["read_scope"] == "route:2:0"
    assert route["command"] == protocol.CMD_MIXER_SET_ROUTE
    assert route["params"] == {"src": 2, "dst": 0, "enabled": False}
    assert route["verify"] == ("enabled", False)
    assert route["restore"]({"enabled": True}) == {
        "command": protocol.CMD_MIXER_SET_ROUTE,
        "params": {"src": 2, "dst": 0, "enabled": True},
    }

    rename = routing._bus_rename_entry(8, "DRUM_BUS")
    assert rename["snap_scope"] == "mixer_track:8"
    assert rename["read_scope"] == "mixer_track:8"
    assert rename["command"] == protocol.CMD_MIXER_SET_NAME
    assert rename["params"] == {"track": 8, "name": "DRUM_BUS"}
    assert rename["verify"] is None
    assert rename["restore"]({"name": "Insert 8"}) == {
        "command": protocol.CMD_MIXER_SET_NAME,
        "params": {"track": 8, "name": "Insert 8"},
    }


def test_routing_plans_expose_kb_policy_boundaries() -> None:
    mcp = MockMCP()
    routing.register(mcp)

    plan = mcp.tools["fl_plan_routing_cleanup"](
        issues=["generators direct to Master"],
        proposed_buses=[{"track": 10, "name": "DRUM BUS", "sources": [1, 2]}],
    )
    rules = "\n".join(plan.get("rules", []))
    assert "Do not infer Playlist Track N maps to Mixer Track N." in rules
    assert "Keep plugin loading, external I/O, and broad UI routing manual." in rules
    assert {
        "preserve_existing_structure_first",
        "channel_rack_workflow_requires_routing_inference",
        "routing_ui_guidance_vs_mcp_write",
        "send_effects_for_shared_space",
    }.issubset(_ref_ids(plan))


def test_project_organizer_color_entries_are_registry_prepared() -> None:
    channel = project_organizer._color_write_entry(3, "#FF0080")
    assert channel["snap_scope"] == "channel:3"
    assert channel["read_scope"] == "channel:3"
    assert channel["command"] == protocol.CMD_CHANNEL_SET_COLOR
    assert channel["params"] == {"channel": 3, "r": 255, "g": 0, "b": 128}
    assert channel["verify"] is None
    assert channel["restore"]({"color": {"int": 0xABA362}}) == {
        "command": protocol.CMD_CHANNEL_SET_COLOR,
        "params": {"channel": 3, "color": 0xABA362},
    }

    mixer = project_organizer._mixer_color_entry(20, "magenta")
    assert mixer["snap_scope"] == "mixer_track:20"
    assert mixer["read_scope"] == "mixer_track:20"
    assert mixer["command"] == protocol.CMD_MIXER_SET_COLOR
    assert mixer["params"] == {"track": 20, "r": 216, "g": 27, "b": 96}
    assert mixer["restore"]({"color": {"int": 0xABA362}}) == {
        "command": protocol.CMD_MIXER_SET_COLOR,
        "params": {"track": 20, "color": 0xABA362},
    }

    try:
        project_organizer._mixer_color_entry(20, "not-a-color")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid color should fail before building a write entry")


def test_project_organizer_invalid_color_fails_before_mutation() -> None:
    mcp = MockMCP()
    project_organizer.register(mcp)
    original_get_bridge = project_organizer.get_bridge
    original_safe_write_group = project_organizer.safety.safe_write_group

    def fail_safe_write_group(*_args, **_kwargs):
        raise AssertionError("safe_write_group must not be called for invalid colors")

    try:
        project_organizer.get_bridge = lambda: object()
        project_organizer.safety.safe_write_group = fail_safe_write_group
        result = mcp.tools["fl_apply_color_standard"](
            "test", [{"type": "mixer", "index": 20, "hex": "not-a-color"}]
        )
    finally:
        project_organizer.get_bridge = original_get_bridge
        project_organizer.safety.safe_write_group = original_safe_write_group

    assert result.get("ok") is False
    assert "unknown color" in result.get("error", "")


def test_mix_doctor_trim_volume_uses_registry_safe_write(monkeypatch, tmp_path) -> None:
    _exercise_mix_doctor_trim_volume_uses_registry_safe_write(tmp_path, monkeypatch)


def _exercise_mix_doctor_trim_volume_uses_registry_safe_write(tmp_path, monkeypatch=None) -> None:
    bridge = MixFixBridge()
    mcp = MockMCP()
    mix_doctor.register(mcp)
    if monkeypatch is None:
        original_get_bridge = mix_doctor.get_bridge
        original_log = safety._log
        mix_doctor.get_bridge = lambda: bridge
        safety._log = safety.ChangeLog(tmp_path / "changes.jsonl")
    else:
        original_get_bridge = None
        original_log = None
        monkeypatch.setattr(mix_doctor, "get_bridge", lambda: bridge)
        monkeypatch.setattr(safety, "_log", safety.ChangeLog(tmp_path / "changes.jsonl"))

    try:
        result = mcp.tools["fl_apply_mix_adjustment"]("trim_volume", track=4, target_db=-3.0)
    finally:
        if monkeypatch is None:
            mix_doctor.get_bridge = original_get_bridge
            safety._log = original_log

    assert result["ok"] is True
    assert result["kind"] == "trim_volume"
    assert result["track"] == 4
    assert result["before_db"] == -1.0
    assert result["after_db"] == -3.0
    assert result["applied"] is True
    assert (
        protocol.CMD_MIXER_SET_VOLUME,
        {"track": 4, "value": -3.0, "unit": "db"},
    ) in bridge.calls


def main() -> int:
    test_routing_write_entries_are_registry_prepared()
    check("routing write entries use registry-prepared route/rename payloads", True)

    test_routing_plans_expose_kb_policy_boundaries()
    check("routing plans expose KB boundary refs and index policy", True)

    test_project_organizer_color_entries_are_registry_prepared()
    check("project organizer color entries use RGB registry payloads", True)

    test_project_organizer_invalid_color_fails_before_mutation()
    check("project organizer rejects invalid colors before mutation", True)

    with tempfile.TemporaryDirectory() as tmp:
        _exercise_mix_doctor_trim_volume_uses_registry_safe_write(Path(tmp))
    check("Mix Review trim volume still uses registry safe_write path", True)

    print(f"\nProduct workflow registry/KB tests: {_P} passed, {_F} failed.")
    return 1 if _F else 0


if __name__ == "__main__":
    raise SystemExit(main())
