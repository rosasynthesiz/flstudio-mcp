"""Exercise real registered tools with a substitute for the external DAW only."""
from copy import deepcopy

from fastmcp import Client
import pytest

from fl_studio_mcp import connection, safety
from fl_studio_mcp.server import build_server


class OfflineDaw:
    def __init__(self):
        self.commands = []

    def call(self, command, params=None, **kwargs):
        self.commands.append((command, params))
        return {"bpm": 130.0, "playing": False, "recording": False,
                "position_beats": 0.0, "pan": 0.0, "ok": True}

    def apply_notes(self, notes, mode="replace", **kwargs):
        self.commands.append(("apply_notes", {"notes": notes, "mode": mode, **kwargs}))
        return {"ok": True, "triggered": True, "note_count": len(notes)}

@pytest.fixture
def offline_daw(monkeypatch, tmp_path):
    daw = OfflineDaw()
    monkeypatch.setattr(connection, "_bridge", daw)
    monkeypatch.setattr(safety, "_DIR", tmp_path)
    monkeypatch.setattr(safety, "_PATH", tmp_path / "changelog.jsonl")
    monkeypatch.setattr(safety, "_log", safety.ChangeLog())
    safety.get_changelog().append({
        "tool": "mixer_set_pan", "scope": "mixer_track:3",
        "restore": {"command": "mixer_set_pan", "params": {"track": 3, "value": 0.0}},
    })
    safety.set_dry_run(False)
    yield daw
    safety.set_dry_run(False)


_NOTE = {"pitch": 60, "time_bars": 0.0, "length_bars": 0.25, "velocity": 0.8}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("fl_set_tempo", {"bpm": 128}),
    ("fl_set_song_position", {"beats": 4}),
    ("fl_play", {}), ("fl_stop", {}), ("fl_toggle_play", {}), ("fl_record", {}),
    ("fl_arrange_new_pattern", {"name": "test"}),
    ("fl_arrange_clone_pattern", {"src": 1, "new_name": "test clone"}),
    ("fl_arrange_select_channel", {"channel": 1}),
    ("fl_arrange_add_marker", {"bar": 2, "name": "test"}),
    ("fl_write_piano_roll_notes", {"notes": [_NOTE]}),
    ("fl_quantize_pattern", {"grid_bars": 0.0625}),
    ("fl_write_raga_melody", {"notes": [_NOTE], "channel": 1}),
    ("fl_write_raga_chords", {"notes": [_NOTE], "channel": 1}),
    ("fl_rollback_last_change", {}),
])
async def test_dry_run_previews_without_any_daw_action(offline_daw, tool, arguments):
    before_log = deepcopy(safety.get_changelog().recent())
    async with Client(build_server()) as client:
        await client.call_tool("fl_set_dry_run", {"enabled": True})
        result = await client.call_tool(tool, arguments)
    assert result.data.get("dry_run") is True, result.data
    assert result.data.get("planned"), result.data
    assert "wrote" not in result.data
    assert not offline_daw.commands, "Dry-run must not send transport, selection, or script actions"
    assert safety.get_changelog().recent() == before_log, "Dry-run must not consume undo entries"


@pytest.mark.asyncio
async def test_live_mode_still_dispatches_transport_once(offline_daw):
    async with Client(build_server()) as client:
        result = await client.call_tool("fl_set_tempo", {"bpm": 130})
        assert result.data == {"bpm": 130.0}
    assert offline_daw.commands == [("set_tempo", {"bpm": 130.0})]


@pytest.mark.asyncio
async def test_reads_are_available_in_dry_run(offline_daw):
    async with Client(build_server()) as client:
        await client.call_tool("fl_set_dry_run", {"enabled": True})
        result = await client.call_tool("fl_get_tempo", {})
    assert result.data == {"bpm": 130.0}
    assert offline_daw.commands == [("get_tempo", None)]
