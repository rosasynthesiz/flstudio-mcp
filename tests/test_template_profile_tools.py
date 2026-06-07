#!/usr/bin/env python3
"""Tests for compact FL Studio template profile tooling."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _route(*targets: int, level: float = 0.8):
    return [{"dst": target, "dst_name": f"Track {target}", "level": level} for target in targets]


def _dump() -> dict:
    routing = [
        {"i": 0, "name": "Master", "routes_to": []},
        {"i": 1, "name": "PreMaster MS", "routes_to": _route(0)},
        {"i": 2, "name": "PreMaster M", "routes_to": _route(1)},
        {"i": 3, "name": "PreMaster S", "routes_to": _route(1)},
        {"i": 4, "name": "Kick 1", "routes_to": _route(117)},
        {"i": 116, "name": "Drums \u25ba Mix", "routes_to": _route(2, 3)},
        {"i": 117, "name": "Kick \u25ba Mix", "routes_to": _route(116, 124)},
        {
            "i": 124,
            "name": "SideChain",
            "routes_to": _route(123, 125, level=0.0),
        },
    ]
    routing.extend(
        {"i": index, "name": f"Insert {index}", "routes_to": _route(120)}
        for index in range(22, 34)
    )
    return {
        "date": "2026-06-07",
        "template_name": "Electro",
        "bridge": {
            "ping": {
                "ok": True,
                "data": {
                    "fl_version": "Producer Edition v25.2.5 [build 5055]",
                    "build": "channels-v38",
                },
            }
        },
        "project": {"ok": True, "data": {"fl_version": "Producer Edition v25.2.5 [build 5055]"}},
        "mixer_all_first_page": {
            "ok": True,
            "data": {
                "tracks": [
                    {
                        "i": 0,
                        "name": "Master",
                        "pan": 0.0,
                        "vol_db": 0.0,
                        "vol_norm": 0.8,
                    }
                ]
            },
        },
        "routing_all": {"ok": True, "data": {"routing": routing}},
        "channel_routing": {
            "ok": True,
            "data": {
                "channels": [
                    {
                        "channel": 0,
                        "name": "Kick",
                        "target_mixer_track": 4,
                        "target_name": "Kick 1",
                        "type": {"label": "genplug"},
                    }
                ]
            },
        },
        "tracks": {
            "124": {
                "track": 124,
                "mixer_track": {
                    "ok": True,
                    "data": {
                        "i": 124,
                        "name": "SideChain",
                        "pan": 0.0,
                        "stereo_sep": 0.0,
                        "vol_db": 0.0,
                        "vol_norm": 0.8,
                    },
                },
                "routing": {"ok": True, "data": {"routes_to": _route(123, 125, level=0.0)}},
                "effect_slots": [
                    {
                        "ok": True,
                        "data": {
                            "slot": 0,
                            "name": "Fruity peak controller",
                            "enabled": True,
                            "mix": 1.0,
                            "valid": True,
                        },
                    }
                ],
                "plugins": [
                    {
                        "slot": 0,
                        "name": "Fruity peak controller",
                        "params": {
                            "ok": True,
                            "params": [
                                {"i": 0, "name": "Base", "v": 0.5, "s": "50%"},
                                {"i": 1, "name": "Vol", "v": 0.25, "s": "25%"},
                            ],
                        },
                    }
                ],
            }
        },
    }


def test_normalizer_produces_compact_template_profile() -> None:
    normalizer = _load_script("normalize_template_dump")
    profile = normalizer.normalize_dump(
        _dump(),
        template_name="Electro",
        template_slug="electro",
        max_params_per_plugin=1,
    )

    assert profile["profile_kind"] == "fl_studio_template_profile"
    assert profile["source"]["controller_build"] == "channels-v38"
    assert profile["reserved_ranges"] == [
        {
            "default_routes_to": [120],
            "from": 22,
            "reason": "Default-named consecutive inserts routed to a template bus.",
            "role": "reserved_placeholder",
            "route_level": 0.8,
            "to": 33,
        }
    ]
    tracks = {track["index"]: track for track in profile["mixer_tracks"]}
    assert 22 not in tracks
    assert tracks[124]["role"] == "sidechain_control"
    assert tracks[124]["is_intentionally_silent"] is True
    assert tracks[124]["plugins"][0]["parameter_count"] == 2
    assert len(tracks[124]["plugins"][0]["parameter_signature"]) == 1
    assert profile["known_control_routes"] == [
        {"level": 0.0, "meaning": "sidechain_control", "source": 124, "targets": [123, 125]}
    ]


def test_reference_electro_profile_validates_against_schema() -> None:
    validator = _load_script("validate_template_profiles")
    schema = json.loads(
        (ROOT / "knowledgebase" / "templates" / "template_profile.schema.json").read_text()
    )
    profile = json.loads(
        (ROOT / "knowledgebase" / "templates" / "profiles" / "electro.json").read_text()
    )

    assert validator.validate_profile(profile, schema) == []
