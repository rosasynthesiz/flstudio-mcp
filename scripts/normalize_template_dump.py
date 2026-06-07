#!/usr/bin/env python3
"""Normalize a large read-only FL Studio template dump into a compact profile."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "knowledgebase" / "templates" / "template_profile.schema.json"
DEFAULT_PROFILE_DIR = ROOT / "knowledgebase" / "templates" / "profiles"

ROLE_MASTER = "master"
ROLE_PREMASTER = "premaster"
ROLE_STEM_BUS = "stem_bus"
ROLE_SOURCE = "source"
ROLE_SIDECHAIN_CONTROL = "sidechain_control"
ROLE_RESERVED_PLACEHOLDER = "reserved_placeholder"
ROLE_UTILITY = "utility"
ROLE_UNKNOWN = "unknown"

CONFIDENCE_LEVELS = {
    "hypothesis",
    "user_reported",
    "docs_confirmed",
    "measured_once",
    "measured_repeated",
    "implementation_verified",
    "cross_platform_verified",
    "deprecated_or_rejected",
}

POLICY_KEYS = (
    "suppress_missing_hpf",
    "suppress_unused_track",
    "suppress_ungrouped",
    "suppress_low_end_width",
    "suppress_offcenter_bass",
    "suppress_layering_warning_without_audio",
)

_DEFAULT_INSERT_RE = re.compile(r"^\s*insert\s+(\d+)\s*$", re.I)
_BUS_MARKERS = (" mix", "\u25ba mix", "bus", "premaster", "master")
_SOURCE_WORDS = (
    "kick",
    "snare",
    "hat",
    "cymbal",
    "overhead",
    "sub",
    "bass",
    "synth",
    "pad",
    "string",
    "vocal",
    "riser",
    "lead",
)


def normalize_dump(
    dump: Mapping[str, Any],
    *,
    template_name: str | None = None,
    template_slug: str | None = None,
    source_path: Path | None = None,
    confidence: str = "measured_once",
    max_params_per_plugin: int = 24,
    include_reserved_tracks: bool = False,
) -> dict[str, Any]:
    """Return a compact template profile from a read-only live dump."""
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"invalid confidence level: {confidence}")

    name = template_name or str(dump.get("template_name") or "").strip()
    if not name:
        raise ValueError("template_name is required when the dump does not contain one")
    slug = template_slug or _slugify(name)

    routing_rows = _routing_rows(dump)
    details_by_track = _track_details(dump)
    first_page_by_track = _first_page_tracks(dump)
    routes_by_track = _routes_by_track(routing_rows, details_by_track)
    names_by_track = _names_by_track(routing_rows, details_by_track, first_page_by_track)
    receives_by_track = _receives_by_track(routes_by_track)
    reserved_ranges = _reserved_ranges(routing_rows)
    reserved_tracks = _reserved_track_set(reserved_ranges)
    known_control_routes = _known_control_routes(
        routes_by_track,
        names_by_track,
        details_by_track,
    )
    control_route_pairs = {
        (route["source"], target)
        for route in known_control_routes
        for target in route.get("targets", [])
    }

    indices = _profile_track_indices(
        names_by_track,
        routes_by_track,
        details_by_track,
        first_page_by_track,
        reserved_tracks,
        include_reserved_tracks,
    )

    mixer_tracks = []
    role_by_track: dict[int, str] = {}
    for index in indices:
        name_for_track = names_by_track.get(index, "")
        role = _infer_role(
            index,
            name_for_track,
            routes_by_track.get(index, []),
            receives_by_track.get(index, []),
            details_by_track.get(index, {}),
            reserved_tracks,
        )
        role_by_track[index] = role
        mixer_tracks.append(
            _profile_track(
                index,
                name_for_track,
                role,
                index in reserved_tracks,
                routes_by_track.get(index, []),
                receives_by_track.get(index, []),
                details_by_track.get(index, {}),
                first_page_by_track.get(index, {}),
                control_route_pairs,
                max_params_per_plugin=max_params_per_plugin,
            )
        )

    source = _source_metadata(
        dump,
        source_path=source_path,
        confidence=confidence,
    )

    profile = {
        "schema_version": 1,
        "profile_kind": "fl_studio_template_profile",
        "template_name": name,
        "template_slug": slug,
        "source": source,
        "mixer_tracks": mixer_tracks,
        "reserved_ranges": reserved_ranges,
        "known_control_routes": known_control_routes,
        "channel_routes": _channel_routes(dump),
        "template_detection": _template_detection(
            mixer_tracks,
            reserved_ranges,
            routes_by_track,
            role_by_track,
        ),
        "open_questions": _open_questions(mixer_tracks, reserved_ranges),
    }
    return profile


def _routing_rows(dump: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = _ok_data(dump.get("routing_all"))
    rows = data.get("routing") if isinstance(data, Mapping) else None
    if isinstance(rows, list):
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def _track_details(dump: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    raw_tracks = dump.get("tracks") or {}
    if not isinstance(raw_tracks, Mapping):
        return out
    for key, value in raw_tracks.items():
        if not isinstance(value, Mapping):
            continue
        index = _as_int(value.get("track", key))
        if index is not None:
            out[index] = dict(value)
    return out


def _first_page_tracks(dump: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    data = _ok_data(dump.get("mixer_all_first_page"))
    if not data:
        data = _ok_data(dump.get("mixer_all"))
    rows = data.get("tracks") if isinstance(data, Mapping) else None
    out: dict[int, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        index = _as_int(row.get("i", row.get("index")))
        if index is not None:
            out[index] = dict(row)
    return out


def _routes_by_track(
    routing_rows: Iterable[Mapping[str, Any]],
    details_by_track: Mapping[int, Mapping[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for row in routing_rows:
        index = _as_int(row.get("i", row.get("index", row.get("track"))))
        if index is None:
            continue
        out[index] = _normalise_routes(row.get("routes_to"))
    for index, detail in details_by_track.items():
        route_data = _ok_data(detail.get("routing"))
        if isinstance(route_data, Mapping) and "routes_to" in route_data:
            out[index] = _normalise_routes(route_data.get("routes_to"))
    return out


def _names_by_track(
    routing_rows: Iterable[Mapping[str, Any]],
    details_by_track: Mapping[int, Mapping[str, Any]],
    first_page_by_track: Mapping[int, Mapping[str, Any]],
) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in routing_rows:
        index = _as_int(row.get("i", row.get("index", row.get("track"))))
        if index is not None:
            out[index] = str(row.get("name") or "")
    for index, row in first_page_by_track.items():
        if row.get("name"):
            out[index] = str(row.get("name"))
    for index, detail in details_by_track.items():
        track_data = _ok_data(detail.get("mixer_track"))
        if isinstance(track_data, Mapping) and track_data.get("name"):
            out[index] = str(track_data.get("name"))
    return out


def _receives_by_track(
    routes_by_track: Mapping[int, Iterable[Mapping[str, Any]]],
) -> dict[int, list[int]]:
    receives: dict[int, list[int]] = defaultdict(list)
    for source, routes in routes_by_track.items():
        for route in routes:
            target = _as_int(route.get("target"))
            if target is not None:
                receives[target].append(source)
    return {target: sorted(set(sources)) for target, sources in receives.items()}


def _reserved_ranges(routing_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: list[int] = []
    current_signature: tuple[tuple[int, float | None], ...] | None = None

    rows = sorted(
        (
            (_as_int(row.get("i", row.get("index", row.get("track")))), row)
            for row in routing_rows
        ),
        key=lambda pair: -1 if pair[0] is None else pair[0],
    )
    for index, row in rows:
        name = str(row.get("name") or "")
        routes = _normalise_routes(row.get("routes_to"))
        signature = _route_signature(routes)
        is_candidate = (
            index is not None
            and _is_default_insert_name(index, name)
            and signature
            and any(target != 0 for target, _level in signature)
        )
        if not is_candidate:
            _flush_reserved_group(groups, current, current_signature)
            current = []
            current_signature = None
            continue
        if current and index == current[-1] + 1 and signature == current_signature:
            current.append(index)
            continue
        _flush_reserved_group(groups, current, current_signature)
        current = [index]
        current_signature = signature
    _flush_reserved_group(groups, current, current_signature)
    return groups


def _flush_reserved_group(
    groups: list[dict[str, Any]],
    indices: list[int],
    signature: tuple[tuple[int, float | None], ...] | None,
) -> None:
    if len(indices) < 3 or not signature:
        return
    targets = [target for target, _level in signature]
    levels = {level for _target, level in signature}
    groups.append(
        {
            "from": indices[0],
            "to": indices[-1],
            "role": ROLE_RESERVED_PLACEHOLDER,
            "default_routes_to": targets,
            "route_level": levels.pop() if len(levels) == 1 else None,
            "reason": "Default-named consecutive inserts routed to a template bus.",
        }
    )


def _reserved_track_set(ranges: Iterable[Mapping[str, Any]]) -> set[int]:
    out: set[int] = set()
    for row in ranges:
        start = _as_int(row.get("from"))
        end = _as_int(row.get("to"))
        if start is None or end is None:
            continue
        out.update(range(start, end + 1))
    return out


def _known_control_routes(
    routes_by_track: Mapping[int, Iterable[Mapping[str, Any]]],
    names_by_track: Mapping[int, str],
    details_by_track: Mapping[int, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source, routes in sorted(routes_by_track.items()):
        targets = []
        levels = []
        for route in routes:
            level = _as_float(route.get("level"))
            target = _as_int(route.get("target"))
            if target is None or level is None or abs(level) > 0.0001:
                continue
            targets.append(target)
            levels.append(level)
        if not targets:
            continue
        name = names_by_track.get(source, "").lower()
        plugin_names = " ".join(_plugin_names(details_by_track.get(source, {}))).lower()
        if "sidechain" not in name and "peak controller" not in plugin_names:
            continue
        out.append(
            {
                "source": source,
                "targets": sorted(set(targets)),
                "level": 0.0 if levels else None,
                "meaning": "sidechain_control",
            }
        )
    return out


def _profile_track_indices(
    names_by_track: Mapping[int, str],
    routes_by_track: Mapping[int, Iterable[Mapping[str, Any]]],
    details_by_track: Mapping[int, Mapping[str, Any]],
    first_page_by_track: Mapping[int, Mapping[str, Any]],
    reserved_tracks: set[int],
    include_reserved_tracks: bool,
) -> list[int]:
    indices = set(details_by_track) | set(first_page_by_track)
    for index, name in names_by_track.items():
        if index in reserved_tracks and not include_reserved_tracks:
            continue
        if index == 0:
            indices.add(index)
            continue
        if _is_default_insert_name(index, name):
            if include_reserved_tracks and index in reserved_tracks:
                indices.add(index)
            continue
        indices.add(index)
    for index, routes in routes_by_track.items():
        if index in reserved_tracks and not include_reserved_tracks:
            continue
        if index not in names_by_track:
            continue
        if routes and not _is_default_insert_name(index, names_by_track[index]):
            indices.add(index)
    return sorted(indices)


def _profile_track(
    index: int,
    name: str,
    role: str,
    is_reserved: bool,
    routes: Iterable[Mapping[str, Any]],
    receives_from: Iterable[int],
    detail: Mapping[str, Any],
    first_page: Mapping[str, Any],
    control_route_pairs: set[tuple[int, int]],
    *,
    max_params_per_plugin: int,
) -> dict[str, Any]:
    track_data = _track_data(detail) or first_page
    normalised_routes = []
    for route in routes:
        target = _as_int(route.get("target"))
        if target is None:
            continue
        normalised_routes.append(
            {
                "target": target,
                "target_name": route.get("target_name"),
                "level": _as_float(route.get("level")),
                "meaning": "sidechain_control"
                if (index, target) in control_route_pairs
                else route.get("meaning"),
            }
        )

    return {
        "index": index,
        "name": name,
        "role": role,
        "is_reserved": is_reserved,
        "is_intentionally_silent": role == ROLE_SIDECHAIN_CONTROL
        and bool(normalised_routes)
        and all(abs(route.get("level") or 0.0) <= 0.0001 for route in normalised_routes),
        "routes_to": normalised_routes,
        "receives_from": sorted(set(int(value) for value in receives_from)),
        "pan": _as_float(track_data.get("pan")),
        "stereo_separation": _as_float(track_data.get("stereo_sep")),
        "volume": {
            "normalized": _as_float(track_data.get("vol_norm")),
            "db": _as_float(track_data.get("vol_db")),
        },
        "plugins": _plugins(detail, max_params_per_plugin=max_params_per_plugin),
        "tool_policy": _tool_policy(role, is_reserved),
    }


def _infer_role(
    index: int,
    name: str,
    routes: Iterable[Mapping[str, Any]],
    receives_from: Iterable[int],
    detail: Mapping[str, Any],
    reserved_tracks: set[int],
) -> str:
    if index in reserved_tracks:
        return ROLE_RESERVED_PLACEHOLDER
    lowered = name.lower()
    plugin_names = " ".join(_plugin_names(detail)).lower()
    if index == 0 or lowered == "master":
        return ROLE_MASTER
    if "sidechain" in lowered or "peak controller" in plugin_names:
        return ROLE_SIDECHAIN_CONTROL
    if "premaster" in lowered:
        return ROLE_PREMASTER
    if any(marker in lowered for marker in _BUS_MARKERS) and receives_from:
        return ROLE_STEM_BUS
    if any(word in lowered for word in _SOURCE_WORDS):
        return ROLE_SOURCE
    if routes and receives_from:
        return ROLE_UTILITY
    if routes:
        return ROLE_SOURCE
    return ROLE_UNKNOWN


def _tool_policy(role: str, is_reserved: bool) -> dict[str, bool]:
    policy = {key: False for key in POLICY_KEYS}
    if is_reserved or role == ROLE_RESERVED_PLACEHOLDER:
        return {
            "suppress_missing_hpf": True,
            "suppress_unused_track": True,
            "suppress_ungrouped": True,
            "suppress_low_end_width": True,
            "suppress_offcenter_bass": True,
            "suppress_layering_warning_without_audio": True,
        }
    if role in {ROLE_PREMASTER, ROLE_STEM_BUS, ROLE_SIDECHAIN_CONTROL}:
        policy.update(
            {
                "suppress_missing_hpf": True,
                "suppress_ungrouped": True,
                "suppress_low_end_width": True,
                "suppress_offcenter_bass": True,
                "suppress_layering_warning_without_audio": True,
            }
        )
    elif role == ROLE_SOURCE:
        policy["suppress_layering_warning_without_audio"] = True
    return policy


def _plugins(detail: Mapping[str, Any], *, max_params_per_plugin: int) -> list[dict[str, Any]]:
    effect_slot_by_index = {
        int(slot_data.get("slot")): slot_data
        for slot_data in (_effect_slot_data(row) for row in detail.get("effect_slots", []))
        if isinstance(slot_data, Mapping) and _as_int(slot_data.get("slot")) is not None
    }
    out = []
    for plugin in detail.get("plugins", []):
        if not isinstance(plugin, Mapping):
            continue
        slot = _as_int(plugin.get("slot"))
        if slot is None:
            continue
        slot_data = effect_slot_by_index.get(slot, {})
        params = _params(plugin.get("params"))
        out.append(
            {
                "slot": slot,
                "name": str(plugin.get("name") or slot_data.get("name") or ""),
                "enabled": slot_data.get("enabled") if "enabled" in slot_data else None,
                "mix": _as_float(slot_data.get("mix")),
                "parameter_count": len(params),
                "parameter_signature": params[:max(0, max_params_per_plugin)],
            }
        )
    if out:
        return sorted(out, key=lambda row: row["slot"])

    plugin_list = _ok_data(detail.get("plugin_list"))
    for plugin in plugin_list.get("slots", []) if isinstance(plugin_list, Mapping) else []:
        if not isinstance(plugin, Mapping):
            continue
        slot = _as_int(plugin.get("slot"))
        if slot is None:
            continue
        slot_data = effect_slot_by_index.get(slot, {})
        out.append(
            {
                "slot": slot,
                "name": str(plugin.get("name") or slot_data.get("name") or ""),
                "enabled": slot_data.get("enabled") if "enabled" in slot_data else None,
                "mix": _as_float(slot_data.get("mix")),
                "parameter_count": 0,
                "parameter_signature": [],
            }
        )
    return sorted(out, key=lambda row: row["slot"])


def _params(raw: Any) -> list[dict[str, Any]]:
    data = _ok_data(raw)
    if data:
        rows = data.get("params", [])
    elif isinstance(raw, Mapping):
        rows = raw.get("params", [])
    else:
        rows = []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        index = _as_int(row.get("i", row.get("index")))
        if index is None:
            continue
        value = row.get("v", row.get("value"))
        out.append(
            {
                "index": index,
                "name": row.get("name"),
                "value": value,
                "normalized": _as_float(value),
                "display": row.get("s", row.get("display")),
            }
        )
    return sorted(out, key=lambda row: row["index"])


def _channel_routes(dump: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = _ok_data(dump.get("channel_routing"))
    rows = data.get("channels") if isinstance(data, Mapping) else []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        index = _as_int(row.get("channel", row.get("channel_index")))
        if index is None:
            continue
        type_value = row.get("type")
        if isinstance(type_value, Mapping):
            type_value = type_value.get("label")
        out.append(
            {
                "channel_index": index,
                "channel_name": str(row.get("name") or ""),
                "target_mixer_track": _as_int(row.get("target_mixer_track")),
                "target_name": row.get("target_name"),
                "type": type_value,
            }
        )
    return sorted(out, key=lambda row: row["channel_index"])


def _template_detection(
    mixer_tracks: list[Mapping[str, Any]],
    reserved_ranges: list[Mapping[str, Any]],
    routes_by_track: Mapping[int, Iterable[Mapping[str, Any]]],
    role_by_track: Mapping[int, str],
) -> dict[str, Any]:
    detection_roles = {ROLE_PREMASTER, ROLE_STEM_BUS, ROLE_SIDECHAIN_CONTROL}
    required_track_names = [
        {"track": int(track["index"]), "name": str(track["name"])}
        for track in mixer_tracks
        if role_by_track.get(int(track["index"])) in detection_roles
    ]
    required_routes = []
    for source, role in sorted(role_by_track.items()):
        if role not in detection_roles:
            continue
        targets = sorted(
            target
            for target in (
                _as_int(route.get("target")) for route in routes_by_track.get(source, [])
            )
            if target is not None
        )
        if targets:
            required_routes.append({"source": source, "targets": targets})

    reserved_count = sum(
        max(0, int(row["to"]) - int(row["from"]) + 1)
        for row in reserved_ranges
        if _as_int(row.get("from")) is not None and _as_int(row.get("to")) is not None
    )
    return {
        "required_track_names": required_track_names,
        "required_routes": required_routes,
        "reserved_placeholder_min_count": min(reserved_count, 12) if reserved_count else 0,
        "confidence_notes": [
            "Generated from read-only dump data; validate against the original dump.",
            "Combine names, routes, and placeholder count to avoid false positives.",
        ],
    }


def _open_questions(
    mixer_tracks: Iterable[Mapping[str, Any]],
    reserved_ranges: Iterable[Mapping[str, Any]],
) -> list[str]:
    questions = ["Verify this profile with a second live read before raising confidence."]
    if any(track.get("stereo_separation") is None for track in mixer_tracks):
        questions.append(
            "Some tracks do not include stereo-separation readback in the source dump."
        )
    if any(track.get("pan") is None for track in mixer_tracks):
        questions.append("Some tracks do not include pan readback in the source dump.")
    if not list(reserved_ranges):
        questions.append(
            "No reserved placeholder range was inferred; confirm whether the template uses one."
        )
    return questions


def _source_metadata(
    dump: Mapping[str, Any],
    *,
    source_path: Path | None,
    confidence: str,
) -> dict[str, Any]:
    bridge = dump.get("bridge") if isinstance(dump.get("bridge"), Mapping) else {}
    ping = _ok_data(bridge.get("ping"))
    project = _ok_data(dump.get("project"))
    date = str(dump.get("date") or "") or "1970-01-01"
    return {
        "type": "normalized_live_dump",
        "date": date,
        "confidence": confidence,
        "fl_version": ping.get("fl_version") or project.get("fl_version"),
        "controller_build": ping.get("build"),
        "source_dump_path": str(source_path) if source_path else None,
        "generated_by": "scripts/normalize_template_dump.py",
    }


def _normalise_routes(raw_routes: Any) -> list[dict[str, Any]]:
    out = []
    for row in raw_routes or []:
        if not isinstance(row, Mapping):
            target = _as_int(row)
            if target is None:
                continue
            out.append({"target": target, "target_name": None, "level": None, "meaning": None})
            continue
        target = _as_int(row.get("dst", row.get("target")))
        if target is None:
            continue
        out.append(
            {
                "target": target,
                "target_name": row.get("dst_name", row.get("target_name")),
                "level": _as_float(row.get("level")),
                "meaning": row.get("meaning"),
            }
        )
    return out


def _route_signature(routes: Iterable[Mapping[str, Any]]) -> tuple[tuple[int, float | None], ...]:
    signature = []
    for route in routes:
        target = _as_int(route.get("target"))
        if target is None:
            continue
        level = _as_float(route.get("level"))
        signature.append((target, round(level, 4) if level is not None else None))
    return tuple(sorted(signature))


def _track_data(detail: Mapping[str, Any]) -> dict[str, Any]:
    data = _ok_data(detail.get("mixer_track"))
    return dict(data) if isinstance(data, Mapping) else {}


def _effect_slot_data(row: Any) -> dict[str, Any]:
    data = _ok_data(row)
    return dict(data) if isinstance(data, Mapping) else {}


def _plugin_names(detail: Mapping[str, Any]) -> list[str]:
    return [
        str(plugin.get("name") or "")
        for plugin in detail.get("plugins", [])
        if isinstance(plugin, Mapping)
    ]


def _ok_data(wrapper: Any) -> dict[str, Any]:
    if (
        isinstance(wrapper, Mapping)
        and wrapper.get("ok") is True
        and isinstance(wrapper.get("data"), Mapping)
    ):
        return dict(wrapper["data"])
    return {}


def _is_default_insert_name(index: int, name: str | None) -> bool:
    match = _DEFAULT_INSERT_RE.match(str(name or ""))
    return bool(match and int(match.group(1)) == int(index))


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "template"


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path, help="Path to a read-only FL template dump JSON.")
    parser.add_argument("--template-name", help="Override the template name from the dump.")
    parser.add_argument("--template-slug", help="Override the generated template slug.")
    parser.add_argument("--confidence", default="measured_once", choices=sorted(CONFIDENCE_LEVELS))
    parser.add_argument("--max-params-per-plugin", type=int, default=24)
    parser.add_argument(
        "--include-reserved-tracks",
        action="store_true",
        help="Include individual reserved placeholder tracks in mixer_tracks.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output profile path. Defaults to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    dump = json.loads(args.dump.read_text(encoding="utf-8"))
    profile = normalize_dump(
        dump,
        template_name=args.template_name,
        template_slug=args.template_slug,
        source_path=args.dump,
        confidence=args.confidence,
        max_params_per_plugin=args.max_params_per_plugin,
        include_reserved_tracks=args.include_reserved_tracks,
    )
    if args.output:
        _write_json(args.output, profile)
    else:
        print(json.dumps(profile, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
