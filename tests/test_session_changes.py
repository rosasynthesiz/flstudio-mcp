"""Session history: fl_list_changes + fl_rollback_changes (no live FL).

The changelog is written by the safety layer in real use; here entries are
appended by hand so each contract can be checked exactly: ordering, project
marking, pagination, the summary, and bulk rollback stopping honestly.
"""

from __future__ import annotations

import time

import pytest
from fastmcp import Client

from fl_studio_mcp import protocol, safety
from fl_studio_mcp.server import build_server
from fl_studio_mcp.tools import changes
from tests.conftest import FakeBridge

TOKEN = "fake-project"


def _entry(tool, scope, *, before=None, after=None, restore=None,
           token=TOKEN, ts=None, **extra):
    entry = {"tool": tool, "scope": scope,
             "command": (restore or {}).get("command", tool),
             "params": extra.pop("params", {}),
             "before": before, "after": after,
             "restore": restore, "project_token": token,
             "pattern": None, "incomplete": False,
             "ts": time.time() if ts is None else ts}
    entry.update(extra)
    return entry


def _mixer_entry(value=0.8, ts=None):
    before = {"i": 15, "name": "Insert 15", "pan": 0.0, "mute": False,
              "solo": False, "vol_norm": value,
              "color": {"int": 1, "hex": "#010101"}}
    return _entry("mixer_set_volume", "mixer_track:15", before=before,
                  after=dict(before, vol_norm=0.7),
                  restore={"command": "mixer_set_volume",
                           "params": {"track": 15, "value": value}},
                  params={"track": 15, "value": 0.7, "_project_token": TOKEN},
                  ts=ts)


def _pan_entry(ts=None):
    before = {"index": 2, "name": "Clap", "pan": -0.5, "vol_norm": 0.8,
              "mute": False, "solo": False}
    return _entry("channel_set_pan", "channel:2", before=before,
                  after=dict(before, pan=0.25),
                  restore={"command": "channel_set_pan",
                           "params": {"channel": 2, "value": -0.5}},
                  params={"channel": 2, "value": 0.25}, ts=ts)


@pytest.fixture
def bridge(monkeypatch):
    b = FakeBridge()
    monkeypatch.setattr(changes, "get_bridge", lambda: b)
    return b


async def _call(tool, arguments=None):
    async with Client(build_server()) as client:
        return (await client.call_tool(tool, arguments or {})).data


# -- fl_list_changes ---------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_log(bridge, changelog):
    out = await _call("fl_list_changes")
    assert out["ok"] and out["total"] == 0
    assert out["changes"] == [] and out["next_start"] is None
    assert "fl_rollback_changes" in out["hint"]


@pytest.mark.asyncio
async def test_newest_first_with_project_and_summary(bridge, changelog):
    now = time.time()
    changelog.append(_mixer_entry(ts=now - 30))
    changelog.append(_entry("tempo_set", "tempo", before={"bpm": 120},
                            after={"bpm": 140},
                            params={"bpm": 140}, ts=now - 5))
    out = await _call("fl_list_changes")
    assert out["total"] == 2
    newest, oldest = out["changes"]
    assert newest["tool"] == "tempo_set" and newest["n"] == 1
    assert newest["summary"] == "tempo_set(bpm=140)"
    assert newest["changed"] == ["bpm"]
    assert newest["project"] == "current" and newest["undoable"] is True
    assert oldest["tool"] == "mixer_set_volume"
    assert "track=15" in oldest["summary"] and "value=0.7" in oldest["summary"]
    assert "_project_token" not in oldest["summary"]
    assert oldest["changed"] == ["vol_norm"]
    assert 25 <= oldest["age_s"] <= 40


@pytest.mark.asyncio
async def test_other_project_and_incomplete_are_not_undoable(bridge, changelog):
    changelog.append(_entry("pattern_rename", "pattern:2", token="old-session"))
    changelog.append(_entry("pattern_rename", "pattern:3", incomplete=True))
    out = await _call("fl_list_changes")
    incomplete, other = out["changes"]
    assert other["project"] == "other" and other["undoable"] is False
    assert incomplete["project"] == "current" and incomplete["undoable"] is False


@pytest.mark.asyncio
async def test_group_entry_summary_and_changed(bridge, changelog):
    changelog.append({
        "tool": "plugin_set_params", "scope": "plugin:1:0", "group": True,
        "snap_scopes": ["plugin_param:1:0:3", "plugin_param:1:0:4"],
        "befores": [{"v": 0.1}, {"v": 0.2}],
        "afters": [{"v": 0.5}, {"v": 0.2}],
        "params": {}, "project_token": TOKEN, "incomplete": False,
        "ts": time.time()})
    out = await _call("fl_list_changes")
    entry = out["changes"][0]
    assert entry["summary"] == "plugin_set_params (2 writes)"
    assert entry["changed"] == ["plugin_param:1:0:3:v"]
    assert entry["undoable"] is True


@pytest.mark.asyncio
async def test_pagination(bridge, changelog):
    for i in range(3):
        changelog.append(_entry(f"tool_{i}", f"scope:{i}"))
    first = await _call("fl_list_changes", {"limit": 2})
    assert [c["tool"] for c in first["changes"]] == ["tool_2", "tool_1"]
    assert first["next_start"] == 2
    second = await _call("fl_list_changes", {"limit": 2, "start": 2})
    assert [c["tool"] for c in second["changes"]] == ["tool_0"]
    assert second["next_start"] is None


@pytest.mark.asyncio
async def test_fl_closed_marks_project_unknown(monkeypatch, changelog):
    class Closed(FakeBridge):
        def call(self, command, params=None):
            if command == "get_project_state":
                raise RuntimeError("FL closed")
            return super().call(command, params)

    b = Closed()
    monkeypatch.setattr(changes, "get_bridge", lambda: b)
    changelog.append(_entry("tempo_set", "tempo"))
    out = await _call("fl_list_changes")
    assert out["changes"][0]["project"] == "unknown"
    assert out["changes"][0]["undoable"] is False


# -- fl_rollback_changes -----------------------------------------------------

def _rollback_bridge():
    b = FakeBridge()
    b.replies[protocol.CMD_MIXER_GET_TRACK] = {
        "i": 15, "vol_norm": 0.8, "pan": 0.0, "mute": False,
        "solo": False, "name": "Insert 15"}
    b.replies[protocol.CMD_CHANNEL_GET] = {
        "index": 2, "pan": -0.5, "vol_norm": 0.8, "mute": False,
        "solo": False, "name": "Clap"}
    return b


@pytest.mark.asyncio
async def test_bulk_rollback_restores_newest_first(monkeypatch, changelog):
    b = _rollback_bridge()
    monkeypatch.setattr(changes, "get_bridge", lambda: b)
    changelog.append(_mixer_entry())
    changelog.append(_pan_entry())
    out = await _call("fl_rollback_changes", {"count": 2})
    assert out["ok"] is True and out["rolled_back"] == 2
    assert [c["tool"] for c in out["changes"]] == [
        "channel_set_pan", "mixer_set_volume"]
    assert changelog.recent() == []
    order = [c for c, _ in b.calls]
    assert order.index("channel_set_pan") < order.index("mixer_set_volume")
    assert "redo is not scriptable" in out["warning"]


@pytest.mark.asyncio
async def test_bulk_rollback_stops_at_first_failure(monkeypatch, changelog):
    b = _rollback_bridge()
    b.replies["channel_set_pan"] = {"ok": False, "error": "refused"}
    monkeypatch.setattr(changes, "get_bridge", lambda: b)
    changelog.append(_pan_entry())
    changelog.append(_mixer_entry())
    out = await _call("fl_rollback_changes", {"count": 2})
    assert out["ok"] is False and out["rolled_back"] == 1
    assert out["changes"] == [{"tool": "mixer_set_volume",
                               "scope": "mixer_track:15"}]
    assert "refused" in out["error"]
    remaining = changelog.recent()
    assert len(remaining) == 1 and remaining[0]["tool"] == "channel_set_pan"


@pytest.mark.asyncio
async def test_bulk_rollback_refuses_other_project(monkeypatch, changelog):
    b = _rollback_bridge()
    monkeypatch.setattr(changes, "get_bridge", lambda: b)
    changelog.append(_entry("tempo_set", "tempo", token="old-session",
                            before={"bpm": 120},
                            restore={"command": "set_tempo",
                                     "params": {"bpm": 120}}))
    out = await _call("fl_rollback_changes", {"count": 1})
    assert out["ok"] is False and out["rolled_back"] == 0
    assert "another project" in out["error"]
    assert len(changelog.recent()) == 1


@pytest.mark.asyncio
async def test_bulk_rollback_dry_run_changes_nothing(monkeypatch, changelog):
    b = _rollback_bridge()
    monkeypatch.setattr(changes, "get_bridge", lambda: b)
    changelog.append(_mixer_entry())
    safety.set_dry_run(True)
    try:
        out = await _call("fl_rollback_changes", {"count": 2})
    finally:
        safety.set_dry_run(False)
    assert out["dry_run"] is True
    assert out["planned"]["params"] == {"count": 2}
    assert b.calls == []
    assert len(changelog.recent()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, -1, 21])
async def test_bulk_rollback_validates_count(monkeypatch, changelog, count):
    b = _rollback_bridge()
    monkeypatch.setattr(changes, "get_bridge", lambda: b)
    out = await _call("fl_rollback_changes", {"count": count})
    assert out["ok"] is False and "between 1 and 20" in out["error"]
    assert b.calls == []
