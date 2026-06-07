#!/usr/bin/env python3
"""Focused tests for the internal operation registry."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from fl_studio_mcp import operations, protocol  # noqa: E402


def _restore(prepared: operations.PreparedOperation, before: dict) -> dict:
    return prepared.build_restore(before)


def test_registry_covers_transport_mixer_and_channel_specs() -> None:
    ids = {(spec.domain, spec.action) for spec in operations.list_operations()}
    assert {
        ("channel", "get"),
        ("channel", "get_selected"),
        ("channel", "get_steps"),
        ("channel", "list"),
        ("channel", "select"),
        ("channel", "set_color"),
        ("channel", "set_mixer_target"),
        ("channel", "set_mute"),
        ("channel", "set_name"),
        ("channel", "set_pan"),
        ("channel", "set_solo"),
        ("channel", "set_steps"),
        ("channel", "set_volume"),
        ("mixer", "get"),
        ("mixer", "get_route"),
        ("mixer", "get_selected"),
        ("mixer", "list"),
        ("mixer", "select"),
        ("mixer", "set_color"),
        ("mixer", "set_mute"),
        ("mixer", "set_name"),
        ("mixer", "set_pan"),
        ("mixer", "set_route"),
        ("mixer", "set_solo"),
        ("mixer", "set_stereo_separation"),
        ("mixer", "set_volume"),
        ("effect", "get_slot"),
        ("effect", "get_track_slots_enabled"),
        ("effect", "set_slot_enabled"),
        ("effect", "set_slot_mix"),
        ("effect", "set_track_slots_enabled"),
        ("eq", "get"),
        ("eq", "set_band"),
        ("pattern", "find_empty"),
        ("pattern", "get"),
        ("pattern", "get_length"),
        ("pattern", "get_selected"),
        ("pattern", "list"),
        ("pattern", "rename"),
        ("pattern", "select"),
        ("pattern", "set_color"),
        ("pattern", "set_length"),
        ("playlist", "get"),
        ("playlist", "list"),
        ("playlist", "select"),
        ("playlist", "set_color"),
        ("playlist", "set_mute"),
        ("playlist", "set_name"),
        ("playlist", "set_solo"),
        ("plugin", "get_param"),
        ("plugin", "list"),
        ("plugin", "list_params"),
        ("plugin", "set_param"),
        ("transport", "get_play_state"),
        ("transport", "get_song_position"),
        ("transport", "get_tempo"),
        ("transport", "get_time_signature"),
        ("transport", "play"),
        ("transport", "record"),
        ("transport", "set_tempo"),
        ("transport", "set_song_position"),
        ("transport", "set_time_signature"),
        ("transport", "stop"),
        ("transport", "toggle_play"),
    }.issubset(ids)
    classes = {
        (spec.domain, spec.action): spec.safety_class for spec in operations.list_operations()
    }
    assert classes[("transport", "play")] == "transient"
    assert classes[("transport", "get_tempo")] == "read-only"
    assert classes[("mixer", "set_volume")] == "write-safe"
    assert classes[("plugin", "set_param")] == "write-safe"


def test_batch_categories_keep_transient_controls_out_of_persistent_batches() -> None:
    read = operations.get_operation("transport", "get_tempo")
    transient = operations.get_operation("transport", "set_song_position")
    write = operations.get_operation("transport", "set_time_signature")

    assert read.batch_eligible is True
    assert read.batch_category == "read_only"
    assert transient.batch_eligible is False
    assert transient.batch_category == "transient"
    assert write.batch_eligible is True
    assert write.batch_category == "persistent_write"


def test_mixer_volume_spec_builds_command_scope_and_restore() -> None:
    prepared = operations.prepare_operation(
        "mixer", "set_volume", {"track": 3, "value": -6, "unit": "db"}
    )
    assert prepared.command.as_dict() == {
        "command": protocol.CMD_MIXER_SET_VOLUME,
        "params": {"track": 3, "value": -6.0, "unit": "db"},
    }
    assert prepared.snapshot_scope == "mixer_track:3"
    assert prepared.readback_scope == "mixer_track:3"
    assert _restore(prepared, {"vol_norm": 0.8}) == {
        "command": protocol.CMD_MIXER_SET_VOLUME,
        "params": {"track": 3, "value": 0.8, "unit": "normalized"},
    }
    entry = prepared.safe_write_group_entry()
    assert entry["snap_scope"] == "mixer_track:3"
    assert entry["read_scope"] == "mixer_track:3"
    assert entry["command"] == protocol.CMD_MIXER_SET_VOLUME
    assert entry["params"] == {"track": 3, "value": -6.0, "unit": "db"}
    assert entry["restore"]({"vol_norm": 0.8}) == {
        "command": protocol.CMD_MIXER_SET_VOLUME,
        "params": {"track": 3, "value": 0.8, "unit": "normalized"},
    }
    assert entry["verify"] is None


def test_mixer_pan_and_name_specs_match_existing_safe_payloads() -> None:
    pan = operations.prepare_operation("mixer", "set_pan", {"track": 4, "value": 0.25})
    assert pan.command.as_dict() == {
        "command": protocol.CMD_MIXER_SET_PAN,
        "params": {"track": 4, "value": 0.25},
    }
    assert _restore(pan, {"pan": -0.5}) == {
        "command": protocol.CMD_MIXER_SET_PAN,
        "params": {"track": 4, "value": -0.5},
    }

    name = operations.prepare_operation("mixer", "set_name", {"track": 4, "name": "Drums"})
    assert name.command.as_dict() == {
        "command": protocol.CMD_MIXER_SET_NAME,
        "params": {"track": 4, "name": "Drums"},
    }
    assert _restore(name, {"name": "Insert 4"}) == {
        "command": protocol.CMD_MIXER_SET_NAME,
        "params": {"track": 4, "name": "Insert 4"},
    }


def test_mixer_mute_solo_select_route_color_and_stereo_specs_match_payloads() -> None:
    mute = operations.prepare_operation("mixer", "set_mute", {"track": 2, "state": True})
    assert mute.command.as_dict() == {
        "command": protocol.CMD_MIXER_SET_MUTE,
        "params": {"track": 2, "state": True},
    }
    assert mute.verify == ("mute", True)
    assert _restore(mute, {"mute": False}) == {
        "command": protocol.CMD_MIXER_SET_MUTE,
        "params": {"track": 2, "state": False},
    }

    solo = operations.prepare_operation("mixer", "set_solo", {"track": 2, "state": False})
    assert solo.verify == ("solo", False)
    assert _restore(solo, {"solo": True}) == {
        "command": protocol.CMD_MIXER_SET_SOLO,
        "params": {"track": 2, "state": True},
    }

    select = operations.prepare_operation("mixer", "select", {"track": 7})
    assert select.snapshot_scope == "mixer_selection"
    assert select.verify == ("track", 7)
    assert _restore(select, {"track": 3}) == {
        "command": protocol.CMD_MIXER_SELECT_TRACK,
        "params": {"track": 3},
    }

    route = operations.prepare_operation(
        "mixer", "set_route", {"src": 8, "dst": 1, "enabled": True}
    )
    assert route.snapshot_scope == "route:8:1"
    assert route.verify == ("enabled", True)
    assert _restore(route, {"enabled": False}) == {
        "command": protocol.CMD_MIXER_SET_ROUTE,
        "params": {"src": 8, "dst": 1, "enabled": False},
    }

    color = operations.prepare_operation("mixer", "set_color", {"track": 6, "r": 1, "g": 2, "b": 3})
    assert color.command.as_dict() == {
        "command": protocol.CMD_MIXER_SET_COLOR,
        "params": {"track": 6, "r": 1, "g": 2, "b": 3},
    }
    assert _restore(color, {"color": {"int": 0x334455}}) == {
        "command": protocol.CMD_MIXER_SET_COLOR,
        "params": {"track": 6, "color": 0x334455},
    }

    stereo = operations.prepare_operation(
        "mixer", "set_stereo_separation", {"track": 9, "value": -0.25}
    )
    assert stereo.command.as_dict() == {
        "command": protocol.CMD_MIXER_SET_STEREO_SEP,
        "params": {"track": 9, "value": -0.25},
    }
    assert _restore(stereo, {"stereo_sep": 0.1}) == {
        "command": protocol.CMD_MIXER_SET_STEREO_SEP,
        "params": {"track": 9, "value": 0.1},
    }


def test_mixer_read_specs_match_existing_payloads() -> None:
    listed = operations.prepare_operation("mixer", "list", {"start": 10})
    assert listed.safety_class == "read-only"
    assert listed.command.as_dict() == {
        "command": protocol.CMD_MIXER_LIST_TRACKS,
        "params": {"start": 10},
    }

    detail = operations.prepare_operation("mixer", "get", {"track": 4})
    assert detail.command.as_dict() == {
        "command": protocol.CMD_MIXER_GET_TRACK,
        "params": {"index": 4},
    }

    route = operations.prepare_operation("mixer", "get_route", {"track": 4})
    assert route.command.as_dict() == {
        "command": protocol.CMD_MIXER_GET_ROUTING,
        "params": {"track": 4},
    }


def test_channel_basic_write_specs_match_existing_safe_payloads() -> None:
    name = operations.prepare_operation("channel", "set_name", {"channel": 1, "name": "Lead"})
    assert name.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_SET_NAME,
        "params": {"channel": 1, "name": "Lead"},
    }
    assert name.snapshot_scope == "channel:1"
    assert _restore(name, {"name": "Sampler"}) == {
        "command": protocol.CMD_CHANNEL_SET_NAME,
        "params": {"channel": 1, "name": "Sampler"},
    }

    target = operations.prepare_operation("channel", "set_mixer_target", {"channel": 1, "track": 8})
    assert target.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_SET_TARGET,
        "params": {"channel": 1, "track": 8},
    }
    assert target.verify == ("target_fx_track", 8)
    assert _restore(target, {"target_fx_track": 2}) == {
        "command": protocol.CMD_CHANNEL_SET_TARGET,
        "params": {"channel": 1, "track": 2},
    }

    volume = operations.prepare_operation(
        "channel", "set_volume", {"channel": 1, "value": -3, "unit": "db"}
    )
    assert volume.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_SET_VOLUME,
        "params": {"channel": 1, "value": -3.0, "unit": "db"},
    }
    assert _restore(volume, {"vol_norm": 0.7}) == {
        "command": protocol.CMD_CHANNEL_SET_VOLUME,
        "params": {"channel": 1, "value": 0.7, "unit": "normalized"},
    }

    pan = operations.prepare_operation("channel", "set_pan", {"channel": 1, "value": -0.5})
    assert pan.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_SET_PAN,
        "params": {"channel": 1, "value": -0.5},
    }
    assert _restore(pan, {"pan": 0.25}) == {
        "command": protocol.CMD_CHANNEL_SET_PAN,
        "params": {"channel": 1, "value": 0.25},
    }


def test_channel_mute_solo_select_color_and_steps_specs_match_payloads() -> None:
    mute = operations.prepare_operation("channel", "set_mute", {"channel": 2, "state": True})
    assert mute.verify == ("mute", True)
    assert _restore(mute, {"mute": False}) == {
        "command": protocol.CMD_CHANNEL_SET_MUTE,
        "params": {"channel": 2, "state": False},
    }

    solo = operations.prepare_operation("channel", "set_solo", {"channel": 2, "state": False})
    assert solo.verify == ("solo", False)
    assert _restore(solo, {"solo": True}) == {
        "command": protocol.CMD_CHANNEL_SET_SOLO,
        "params": {"channel": 2, "state": True},
    }

    select = operations.prepare_operation("channel", "select", {"channel": 5})
    assert select.snapshot_scope == "selected_channel"
    assert _restore(select, {"selected": 1}) == {
        "command": protocol.CMD_CHANNEL_SELECT,
        "params": {"channel": 1},
    }

    color = operations.prepare_operation("channel", "set_color", {"channel": 3, "color": 0x112233})
    assert color.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_SET_COLOR,
        "params": {"channel": 3, "color": 0x112233},
    }
    assert _restore(color, {"color": {"int": 0x445566}}) == {
        "command": protocol.CMD_CHANNEL_SET_COLOR,
        "params": {"channel": 3, "color": 0x445566},
    }

    steps = operations.prepare_operation(
        "channel",
        "set_steps",
        {
            "channel": 4,
            "pattern": 2,
            "steps": [{"step": 0, "value": True, "velocity": 0.75, "pan": -0.25}],
        },
    )
    assert steps.snapshot_scope == "channel_steps:4:2"
    assert steps.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_SET_STEPS,
        "params": {
            "channel": 4,
            "pattern": 2,
            "steps": [{"step": 0, "value": True, "velocity": 0.75, "pan": -0.25}],
        },
    }
    assert _restore(
        steps,
        {
            "pattern": 2,
            "grid": [False],
            "vel": [0.8],
            "pan": [0.0],
            "shift": [0.0],
            "rep": [0],
            "release": [None],
            "mod": [None],
            "pitch": [None],
        },
    ) == {
        "command": protocol.CMD_CHANNEL_SET_STEPS,
        "params": {
            "channel": 4,
            "pattern": 2,
            "steps": [
                {"step": 0, "value": False, "velocity": 0.8, "pan": 0.0, "shift": 0.0, "repeat": 0}
            ],
        },
    }


def test_channel_read_specs_match_existing_payloads() -> None:
    listed = operations.prepare_operation("channel", "list", {"start": 2})
    assert listed.safety_class == "read-only"
    assert listed.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_LIST,
        "params": {"start": 2},
    }

    detail = operations.prepare_operation("channel", "get", {"channel": 3})
    assert detail.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_GET,
        "params": {"index": 3},
    }

    steps = operations.prepare_operation("channel", "get_steps", {"channel": 3, "pattern": 2})
    assert steps.command.as_dict() == {
        "command": protocol.CMD_CHANNEL_GET_STEPS,
        "params": {"channel": 3, "pattern": 2},
    }


def test_pattern_specs_match_existing_safe_payloads() -> None:
    listed = operations.prepare_operation("pattern", "list", {"start": 8})
    assert listed.safety_class == "read-only"
    assert listed.command.as_dict() == {
        "command": protocol.CMD_PATTERN_LIST,
        "params": {"start": 8},
    }

    detail = operations.prepare_operation("pattern", "get", {"index": 2})
    assert detail.command.as_dict() == {
        "command": protocol.CMD_PATTERN_GET,
        "params": {"index": 2},
    }

    selected = operations.prepare_operation("pattern", "select", {"index": 3})
    assert selected.snapshot_scope == "patterns_selected"
    assert selected.verify == ("selected", 3)
    assert _restore(selected, {"selected": 1}) == {
        "command": protocol.CMD_PATTERN_SELECT,
        "params": {"index": 1},
    }

    rename = operations.prepare_operation("pattern", "rename", {"index": 2, "name": "Chorus"})
    assert rename.command.as_dict() == {
        "command": protocol.CMD_PATTERN_RENAME,
        "params": {"index": 2, "name": "Chorus"},
    }
    assert _restore(rename, {"name": "Verse"}) == {
        "command": protocol.CMD_PATTERN_RENAME,
        "params": {"index": 2, "name": "Verse"},
    }

    color = operations.prepare_operation("pattern", "set_color", {"index": 2, "color": 0x102030})
    assert color.snapshot_scope == "pattern:2"
    assert _restore(color, {"color": {"int": 0x405060}}) == {
        "command": protocol.CMD_PATTERN_SET_COLOR,
        "params": {"index": 2, "color": 0x405060},
    }

    length = operations.prepare_operation("pattern", "set_length", {"index": 2, "beats": 12.5})
    assert length.command.as_dict() == {
        "command": protocol.CMD_PATTERN_SET_LENGTH,
        "params": {"index": 2, "beats": 12.5},
    }
    assert _restore(length, {"length": 16}) == {
        "command": protocol.CMD_PATTERN_SET_LENGTH,
        "params": {"index": 2, "beats": 16.0},
    }

    find_empty = operations.prepare_operation("pattern", "find_empty", {})
    assert find_empty.command.as_dict() == {
        "command": protocol.CMD_PATTERN_FIND_EMPTY,
        "params": {},
    }


def test_playlist_specs_match_existing_safe_payloads() -> None:
    listed = operations.prepare_operation("playlist", "list", {"start": 4})
    assert listed.safety_class == "read-only"
    assert listed.command.as_dict() == {
        "command": protocol.CMD_PLAYLIST_LIST_TRACKS,
        "params": {"start": 4},
    }

    detail = operations.prepare_operation("playlist", "get", {"index": 2})
    assert detail.command.as_dict() == {
        "command": protocol.CMD_PLAYLIST_GET_TRACK,
        "params": {"index": 2},
    }

    select = operations.prepare_operation("playlist", "select", {"index": 3})
    assert select.command.as_dict() == {
        "command": protocol.CMD_PLAYLIST_SELECT_TRACK,
        "params": {"index": 3, "state": True},
    }
    assert select.snapshot_scope == "playlist_track:3"
    assert select.verify == ("selected", True)
    assert _restore(select, {"selected": False}) == {
        "command": protocol.CMD_PLAYLIST_SELECT_TRACK,
        "params": {"index": 3, "state": False},
    }

    mute = operations.prepare_operation("playlist", "set_mute", {"index": 3, "state": True})
    assert mute.verify == ("mute", True)
    assert _restore(mute, {"mute": False}) == {
        "command": protocol.CMD_PLAYLIST_SET_MUTE,
        "params": {"index": 3, "state": False},
    }

    solo = operations.prepare_operation("playlist", "set_solo", {"index": 3, "state": False})
    assert solo.verify == ("solo", False)
    assert _restore(solo, {"solo": True}) == {
        "command": protocol.CMD_PLAYLIST_SET_SOLO,
        "params": {"index": 3, "state": True},
    }

    name = operations.prepare_operation("playlist", "set_name", {"index": 3, "name": "Vocals"})
    assert _restore(name, {"name": "Track 3"}) == {
        "command": protocol.CMD_PLAYLIST_SET_NAME,
        "params": {"index": 3, "name": "Track 3"},
    }

    color = operations.prepare_operation(
        "playlist", "set_color", {"index": 3, "r": 1, "g": 2, "b": 3}
    )
    assert color.command.as_dict() == {
        "command": protocol.CMD_PLAYLIST_SET_COLOR,
        "params": {"index": 3, "r": 1, "g": 2, "b": 3},
    }
    assert _restore(color, {"color": {"int": 0xAABBCC}}) == {
        "command": protocol.CMD_PLAYLIST_SET_COLOR,
        "params": {"index": 3, "color": 0xAABBCC},
    }


def test_effect_and_eq_specs_match_existing_safe_payloads() -> None:
    slot = operations.prepare_operation("effect", "get_slot", {"track": 5, "slot": 2})
    assert slot.command.as_dict() == {
        "command": protocol.CMD_MIXER_GET_SLOT,
        "params": {"track": 5, "slot": 2},
    }

    mix = operations.prepare_operation(
        "effect", "set_slot_mix", {"track": 5, "slot": 2, "mix": 0.25}
    )
    assert mix.snapshot_scope == "effect_slot:5:2"
    assert _restore(mix, {"mix": 0.8}) == {
        "command": protocol.CMD_MIXER_SET_SLOT_MIX,
        "params": {"track": 5, "slot": 2, "mix": 0.8},
    }

    enabled = operations.prepare_operation(
        "effect", "set_slot_enabled", {"track": 5, "slot": 2, "enabled": False}
    )
    assert enabled.verify == ("enabled", False)
    assert _restore(enabled, {"enabled": True}) == {
        "command": protocol.CMD_MIXER_SET_SLOT_ENABLED,
        "params": {"track": 5, "slot": 2, "enabled": True},
    }

    track_slots = operations.prepare_operation(
        "effect", "set_track_slots_enabled", {"track": 5, "enabled": False}
    )
    assert track_slots.snapshot_scope == "track_slots:5"
    assert _restore(track_slots, {"enabled": True}) == {
        "command": protocol.CMD_MIXER_SET_TRACK_SLOTS,
        "params": {"track": 5, "enabled": True},
    }

    eq_read = operations.prepare_operation("eq", "get", {"track": 5})
    assert eq_read.command.as_dict() == {
        "command": protocol.CMD_MIXER_GET_EQ,
        "params": {"track": 5},
    }

    eq = operations.prepare_operation(
        "eq", "set_band", {"track": 5, "band": 1, "gain": 0.4, "frequency": 0.6}
    )
    assert eq.snapshot_scope == "mixer_eq:5"
    assert _restore(
        eq,
        {"bands": [{"band": 1, "gain": 0.1, "frequency": 0.2, "bandwidth": 0.3, "type": 2}]},
    ) == {
        "command": protocol.CMD_MIXER_SET_EQ,
        "params": {
            "track": 5,
            "band": 1,
            "gain": 0.1,
            "frequency": 0.2,
            "bandwidth": 0.3,
            "type": 2,
        },
    }


def test_plugin_specs_match_existing_safe_payloads() -> None:
    listed = operations.prepare_operation("plugin", "list", {"track": 5})
    assert listed.safety_class == "read-only"
    assert listed.command.as_dict() == {
        "command": protocol.CMD_PLUGIN_LIST,
        "params": {"track": 5},
    }

    params = operations.prepare_operation(
        "plugin", "list_params", {"track": 5, "slot": 2, "start": 150}
    )
    assert params.command.as_dict() == {
        "command": protocol.CMD_PLUGIN_GET_PARAMS,
        "params": {"track": 5, "slot": 2, "start": 150},
    }

    one = operations.prepare_operation("plugin", "get_param", {"track": 5, "slot": 2, "param": 7})
    assert one.command.as_dict() == {
        "command": protocol.CMD_PLUGIN_GET_PARAM,
        "params": {"track": 5, "slot": 2, "param": 7},
    }

    write = operations.prepare_operation(
        "plugin", "set_param", {"track": 5, "slot": 2, "param": 7, "value": 0.45678}
    )
    assert write.snapshot_scope == "plugin_param:5:2:7"
    assert write.verify == ("v", 0.4568)
    assert write.command.as_dict() == {
        "command": protocol.CMD_PLUGIN_SET_PARAM,
        "params": {"track": 5, "slot": 2, "param": 7, "value": 0.45678},
    }
    assert _restore(write, {"v": 0.125}) == {
        "command": protocol.CMD_PLUGIN_SET_PARAM,
        "params": {"track": 5, "slot": 2, "param": 7, "value": 0.125},
    }


def test_tempo_spec_builds_command_scope_and_restore() -> None:
    prepared = operations.prepare_operation("transport", "set_tempo", {"bpm": 128})
    assert prepared.command.as_dict() == {
        "command": protocol.CMD_SET_TEMPO,
        "params": {"bpm": 128.0},
    }
    assert prepared.snapshot_scope == "tempo"
    assert prepared.readback_scope == "tempo"
    assert _restore(prepared, {"bpm": 120.0}) == {
        "command": protocol.CMD_SET_TEMPO,
        "params": {"bpm": 120.0},
    }


def test_transport_time_signature_reads_and_transients_match_payloads() -> None:
    signature = operations.prepare_operation(
        "transport", "set_time_signature", {"numerator": 3, "denominator": 4}
    )
    assert signature.command.as_dict() == {
        "command": protocol.CMD_SET_TIME_SIG,
        "params": {"numerator": 3, "denominator": 4},
    }
    assert signature.snapshot_scope == "time_signature"
    assert _restore(signature, {"numerator": 4, "denominator": 4}) == {
        "command": protocol.CMD_SET_TIME_SIG,
        "params": {"numerator": 4, "denominator": 4},
    }

    get_tempo = operations.prepare_operation("transport", "get_tempo", {})
    assert get_tempo.command.as_dict() == {"command": protocol.CMD_GET_TEMPO, "params": {}}

    play = operations.prepare_operation("transport", "play", {})
    assert play.safety_class == "transient"
    assert play.batch_eligible is False
    assert play.command.as_dict() == {"command": protocol.CMD_PLAY, "params": {}}

    position = operations.prepare_operation("transport", "set_song_position", {"beats": 4})
    assert position.command.as_dict() == {
        "command": protocol.CMD_SET_SONG_POS,
        "params": {"beats": 4.0},
    }


@pytest.mark.parametrize(
    ("domain", "action", "params"),
    [
        ("not_a_domain", "set_volume", {"track": 1, "value": 0.7}),
        ("mixer", "not_an_action", {"track": 1, "value": 0.7}),
        ("mixer", "set_volume", {"track": 1, "value": 2.0, "unit": "normalized"}),
        ("mixer", "set_volume", {"track": 1, "value": 0.5, "unit": "percent"}),
        ("mixer", "set_pan", {"track": 1, "value": 1.5}),
        ("mixer", "set_mute", {"track": 1, "state": 1}),
        ("mixer", "set_name", {"track": True, "name": "Bus"}),
        ("mixer", "set_color", {"track": 1, "r": 1, "g": 2}),
        ("mixer", "set_route", {"src": 1, "dst": 2, "enabled": "yes"}),
        ("channel", "set_name", {"channel": 0, "name": ""}),
        ("channel", "set_pan", {"channel": 0, "value": -1.5}),
        ("channel", "set_mixer_target", {"channel": 0, "track": -1}),
        ("channel", "set_steps", {"channel": 0, "steps": [{"step": 0, "value": True}]}),
        ("channel", "set_steps", {"channel": 0, "pattern": 1, "steps": [{"step": 64}]}),
        ("pattern", "get", {"index": 0}),
        ("pattern", "set_length", {"index": 1, "beats": 0}),
        ("pattern", "set_color", {"index": 1, "color": 0xFFFFFF + 1}),
        ("playlist", "set_mute", {"index": 1, "state": 1}),
        ("playlist", "set_color", {"index": 1, "r": 1, "g": 2}),
        ("effect", "get_slot", {"track": 1, "slot": 10}),
        ("effect", "set_slot_mix", {"track": 1, "slot": 0, "mix": 1.5}),
        ("effect", "set_slot_enabled", {"track": 1, "slot": 0, "enabled": "no"}),
        ("eq", "set_band", {"track": 1, "band": 3, "gain": 0.5}),
        ("eq", "set_band", {"track": 1, "band": 1}),
        ("eq", "set_band", {"track": 1, "band": 1, "gain": -0.1}),
        ("plugin", "list_params", {"track": 1, "slot": 10}),
        ("plugin", "get_param", {"track": 1, "slot": 0, "param": "decay"}),
        ("plugin", "set_param", {"track": 1, "slot": 0, "param": 2, "value": 2.0}),
        ("transport", "set_tempo", {"bpm": 1000}),
        ("transport", "set_time_signature", {"numerator": 3, "denominator": 16}),
        ("transport", "set_song_position", {"beats": 1, "ticks": 2}),
    ],
)
def test_invalid_operation_ids_and_parameters_are_rejected(
    domain: str, action: str, params: dict
) -> None:
    with pytest.raises(operations.OperationValidationError):
        operations.prepare_operation(domain, action, params)


def test_duplicate_operation_specs_are_rejected() -> None:
    spec = operations.get_operation("mixer", "set_pan")
    with pytest.raises(operations.OperationValidationError):
        operations.OperationRegistry([spec, spec])


def test_prepared_operation_exports_safe_write_kwargs() -> None:
    prepared = operations.prepare_operation(
        "channel", "set_mixer_target", {"channel": 2, "track": 5}
    )
    kwargs = prepared.safe_write_kwargs(tool="channel_set_target")
    assert kwargs["tool"] == "channel_set_target"
    assert kwargs["scope"] == "channel:2"
    assert kwargs["command"] == protocol.CMD_CHANNEL_SET_TARGET
    assert kwargs["params"] == {"channel": 2, "track": 5}
    assert kwargs["verify"] == ("target_fx_track", 5)
    assert kwargs["build_restore"]({"target_fx_track": 1}) == {
        "command": protocol.CMD_CHANNEL_SET_TARGET,
        "params": {"channel": 2, "track": 1},
    }
