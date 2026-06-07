#!/usr/bin/env python3
"""Validate compact FL Studio template profile JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "knowledgebase" / "templates" / "template_profile.schema.json"
DEFAULT_PROFILE_DIR = ROOT / "knowledgebase" / "templates" / "profiles"

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

ROLES = {
    "master",
    "premaster",
    "stem_bus",
    "source",
    "sidechain_control",
    "reserved_placeholder",
    "utility",
    "unknown",
}

POLICY_KEYS = {
    "suppress_missing_hpf",
    "suppress_unused_track",
    "suppress_ungrouped",
    "suppress_low_end_width",
    "suppress_offcenter_bass",
    "suppress_layering_warning_without_audio",
}

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "profile_kind",
    "template_name",
    "template_slug",
    "source",
    "mixer_tracks",
    "reserved_ranges",
    "known_control_routes",
    "channel_routes",
    "template_detection",
    "open_questions",
}


def validate_profile(
    profile: Mapping[str, Any],
    schema: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return validation errors for a compact template profile."""
    errors: list[str] = []
    if schema is not None:
        errors.extend(_json_schema_errors(profile, schema))
    errors.extend(_structural_errors(profile))
    return errors


def _json_schema_errors(profile: Mapping[str, Any], schema: Mapping[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except Exception:
        return []

    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(profile), key=lambda item: list(item.path)):
        path = ".".join(str(part) for part in error.path) or "<root>"
        errors.append(f"{path}: {error.message}")
    return errors


def _structural_errors(profile: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL - set(profile))
    if missing:
        errors.append(f"<root>: missing required keys: {', '.join(missing)}")
        return errors

    if profile.get("profile_kind") != "fl_studio_template_profile":
        errors.append("profile_kind: must be fl_studio_template_profile")
    if not isinstance(profile.get("template_name"), str) or not profile.get("template_name"):
        errors.append("template_name: must be a non-empty string")
    source = profile.get("source")
    if not isinstance(source, Mapping):
        errors.append("source: must be an object")
    else:
        confidence = source.get("confidence")
        if confidence not in CONFIDENCE_LEVELS:
            errors.append(f"source.confidence: invalid confidence level {confidence!r}")

    tracks = profile.get("mixer_tracks")
    if not isinstance(tracks, list):
        errors.append("mixer_tracks: must be a list")
        tracks = []
    track_errors, track_indices, routes_by_source = _track_errors(tracks)
    errors.extend(track_errors)

    ranges = profile.get("reserved_ranges")
    if not isinstance(ranges, list):
        errors.append("reserved_ranges: must be a list")
        ranges = []
    range_errors, reserved_count = _reserved_range_errors(ranges)
    errors.extend(range_errors)

    control_routes = profile.get("known_control_routes")
    if not isinstance(control_routes, list):
        errors.append("known_control_routes: must be a list")
        control_routes = []
    errors.extend(_control_route_errors(control_routes, routes_by_source))

    channel_routes = profile.get("channel_routes")
    if not isinstance(channel_routes, list):
        errors.append("channel_routes: must be a list")
    else:
        errors.extend(_channel_route_errors(channel_routes))

    detection = profile.get("template_detection")
    if not isinstance(detection, Mapping):
        errors.append("template_detection: must be an object")
    else:
        errors.extend(_detection_errors(detection, tracks, track_indices, reserved_count))

    open_questions = profile.get("open_questions")
    if not isinstance(open_questions, list) or not all(isinstance(q, str) for q in open_questions):
        errors.append("open_questions: must be a list of strings")

    return errors


def _track_errors(
    tracks: Iterable[Any],
) -> tuple[list[str], set[int], dict[int, set[int]]]:
    errors: list[str] = []
    indices: set[int] = set()
    routes_by_source: dict[int, set[int]] = {}
    for pos, track in enumerate(tracks):
        path = f"mixer_tracks[{pos}]"
        if not isinstance(track, Mapping):
            errors.append(f"{path}: must be an object")
            continue
        index = _as_int(track.get("index"))
        if index is None:
            errors.append(f"{path}.index: must be an integer")
            continue
        if index in indices:
            errors.append(f"{path}.index: duplicate track index {index}")
        indices.add(index)
        if track.get("role") not in ROLES:
            errors.append(f"{path}.role: invalid role {track.get('role')!r}")
        if track.get("is_reserved") is True and track.get("role") != "reserved_placeholder":
            errors.append(f"{path}: reserved tracks must use role reserved_placeholder")
        if not isinstance(track.get("plugins"), list):
            errors.append(f"{path}.plugins: must be a list")
        policy = track.get("tool_policy")
        if not isinstance(policy, Mapping):
            errors.append(f"{path}.tool_policy: must be an object")
        else:
            missing_policy = sorted(POLICY_KEYS - set(policy))
            if missing_policy:
                errors.append(f"{path}.tool_policy: missing {', '.join(missing_policy)}")
            for key in POLICY_KEYS & set(policy):
                if not isinstance(policy.get(key), bool):
                    errors.append(f"{path}.tool_policy.{key}: must be boolean")
        route_targets = set()
        routes = track.get("routes_to")
        if not isinstance(routes, list):
            errors.append(f"{path}.routes_to: must be a list")
        else:
            for route_pos, route in enumerate(routes):
                if not isinstance(route, Mapping):
                    errors.append(f"{path}.routes_to[{route_pos}]: must be an object")
                    continue
                target = _as_int(route.get("target"))
                if target is None:
                    errors.append(f"{path}.routes_to[{route_pos}].target: must be an integer")
                else:
                    route_targets.add(target)
        routes_by_source[index] = route_targets
    return errors, indices, routes_by_source


def _reserved_range_errors(ranges: Iterable[Any]) -> tuple[list[str], int]:
    errors: list[str] = []
    total = 0
    seen: set[int] = set()
    for pos, row in enumerate(ranges):
        path = f"reserved_ranges[{pos}]"
        if not isinstance(row, Mapping):
            errors.append(f"{path}: must be an object")
            continue
        start = _as_int(row.get("from"))
        end = _as_int(row.get("to"))
        if start is None or end is None:
            errors.append(f"{path}: from/to must be integers")
            continue
        if start > end:
            errors.append(f"{path}: from must be <= to")
            continue
        current = set(range(start, end + 1))
        overlap = seen & current
        if overlap:
            errors.append(f"{path}: overlaps reserved tracks {sorted(overlap)[:5]}")
        seen.update(current)
        total += len(current)
        if row.get("role") != "reserved_placeholder":
            errors.append(f"{path}.role: must be reserved_placeholder")
        if not isinstance(row.get("default_routes_to"), list) or not row.get("default_routes_to"):
            errors.append(f"{path}.default_routes_to: must be a non-empty list")
    return errors, total


def _control_route_errors(
    routes: Iterable[Any],
    routes_by_source: Mapping[int, set[int]],
) -> list[str]:
    errors: list[str] = []
    for pos, route in enumerate(routes):
        path = f"known_control_routes[{pos}]"
        if not isinstance(route, Mapping):
            errors.append(f"{path}: must be an object")
            continue
        source = _as_int(route.get("source"))
        targets = route.get("targets")
        if source is None:
            errors.append(f"{path}.source: must be an integer")
            continue
        if not isinstance(targets, list) or not targets:
            errors.append(f"{path}.targets: must be a non-empty list")
            continue
        missing_targets = sorted(
            target
            for target in (_as_int(value) for value in targets)
            if target is not None and target not in routes_by_source.get(source, set())
        )
        if missing_targets:
            errors.append(f"{path}: targets not present in mixer route list: {missing_targets}")
    return errors


def _channel_route_errors(routes: Iterable[Any]) -> list[str]:
    errors: list[str] = []
    seen: set[int] = set()
    for pos, row in enumerate(routes):
        path = f"channel_routes[{pos}]"
        if not isinstance(row, Mapping):
            errors.append(f"{path}: must be an object")
            continue
        index = _as_int(row.get("channel_index"))
        if index is None:
            errors.append(f"{path}.channel_index: must be an integer")
            continue
        if index in seen:
            errors.append(f"{path}.channel_index: duplicate channel index {index}")
        seen.add(index)
    return errors


def _detection_errors(
    detection: Mapping[str, Any],
    tracks: Iterable[Any],
    track_indices: set[int],
    reserved_count: int,
) -> list[str]:
    errors: list[str] = []
    names_by_track = {
        int(track["index"]): track.get("name")
        for track in tracks
        if isinstance(track, Mapping) and _as_int(track.get("index")) is not None
    }
    for pos, item in enumerate(detection.get("required_track_names") or []):
        path = f"template_detection.required_track_names[{pos}]"
        if not isinstance(item, Mapping):
            errors.append(f"{path}: must be an object")
            continue
        track = _as_int(item.get("track"))
        if track is None:
            errors.append(f"{path}.track: must be an integer")
            continue
        if track not in track_indices:
            errors.append(f"{path}.track: {track} is not present in mixer_tracks")
        elif names_by_track.get(track) != item.get("name"):
            errors.append(f"{path}.name: does not match mixer_tracks[{track}]")
    min_count = _as_int(detection.get("reserved_placeholder_min_count"))
    if min_count is None:
        errors.append("template_detection.reserved_placeholder_min_count: must be an integer")
    elif min_count > reserved_count:
        errors.append(
            "template_detection.reserved_placeholder_min_count: "
            f"{min_count} exceeds reserved range count {reserved_count}"
        )
    return errors


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _profile_paths(args: argparse.Namespace) -> list[Path]:
    paths = list(args.profile or [])
    if paths:
        return paths
    profile_dir = args.profile_dir
    return sorted(profile_dir.glob("*.json"))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help=f"Template profile JSON Schema. Default: {DEFAULT_SCHEMA}",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        action="append",
        help="Profile JSON to validate. May be passed multiple times.",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help=(
            "Directory of profiles to validate when --profile is omitted. "
            f"Default: {DEFAULT_PROFILE_DIR}"
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    paths = _profile_paths(args)
    if not paths:
        print(f"No template profiles found in {args.profile_dir}", file=sys.stderr)
        return 1

    failed = False
    for path in paths:
        profile = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_profile(profile, schema)
        if errors:
            failed = True
            print(f"FAIL {path}")
            for error in errors:
                print(f"- {error}")
        elif not args.quiet:
            print(f"PASS {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
