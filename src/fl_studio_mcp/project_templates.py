"""Read-only project template topology classification.

The classifier turns raw mixer/routing/channel readbacks into conservative
metadata that product workflows can use before making judgement calls. It does
not create executable operations and it does not mutate FL Studio state.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

ELECTRO_TEMPLATE_NAME = "Electro"

ROLE_MASTER = "master"
ROLE_PREMASTER = "premaster"
ROLE_STEM_BUS = "stem_bus"
ROLE_SOURCE = "source"
ROLE_SIDECHAIN_CONTROL = "sidechain_control"
ROLE_RESERVED_PLACEHOLDER = "template_reserved_placeholder"
ROLE_UTILITY = "utility"
ROLE_UNKNOWN = "unknown"

PROFILE_RESERVED_ROLE = "reserved_placeholder"
PROFILE_KIND = "fl_studio_template_profile"

ROOT_DIR = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT_DIR / "knowledgebase" / "templates" / "profiles"

_DEFAULT_INSERT_RE = re.compile(r"^\s*insert\s+(\d+)\s*$", re.I)
_POLICY_KEYS = {
    "suppress_missing_hpf",
    "suppress_unused_track",
    "suppress_ungrouped",
    "suppress_low_end_width",
    "suppress_offcenter_bass",
    "suppress_layering_warning_without_audio",
}


def classify_topology(
    mixer_tracks: Iterable[Mapping[str, Any]],
    routing_rows: Iterable[Mapping[str, Any]] | None = None,
    channel_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify a known mixer template from read-only project data.

    ``mixer_tracks`` may be rows from ``mixer_list_tracks``, routing rows, or
    the normalised Mix Review snapshot. ``routing_rows`` may be rows from
    ``mixer_get_routing_all``; when omitted, per-track ``routes_to`` fields from
    ``mixer_tracks`` are used.
    """
    tracks = [_normalise_track(row) for row in mixer_tracks]
    tracks = [row for row in tracks if row.get("index") is not None]
    route_source = list(routing_rows) if routing_rows is not None else tracks
    route_by = {
        int(row.get("i", row.get("index"))): list(row.get("routes_to") or [])
        for row in route_source
        if row.get("i", row.get("index")) is not None
    }
    name_by = {int(row["index"]): str(row.get("name") or "") for row in tracks}
    profiles = load_profiles()
    channel_by = _channels_by_index(channel_rows or [])
    matches = [_score_profile(profile, name_by, route_by, channel_by) for profile in profiles]
    matches = [match for match in matches if match["matched"]]
    if not matches:
        return unmatched_context()

    matches.sort(
        key=lambda match: (
            match["score"],
            match["channel_matches"],
            match["source_name_matches"],
            match["route_matches"],
            match["placeholder_matches"],
        ),
        reverse=True,
    )
    best = matches[0]
    tied = [
        match
        for match in matches
        if (
            match["score"] == best["score"]
            and match["channel_matches"] == best["channel_matches"]
            and match["source_name_matches"] == best["source_name_matches"]
            and match["route_matches"] == best["route_matches"]
            and match["placeholder_matches"] == best["placeholder_matches"]
        )
    ]
    context = _context_from_match(best, tied, name_by, route_by)
    if channel_rows is not None:
        context["channel_summary"] = _channel_summary(channel_rows, context)
    return context


@lru_cache(maxsize=1)
def load_profiles() -> tuple[dict[str, Any], ...]:
    """Load compact template profiles from the Knowledgebase."""
    if not PROFILE_DIR.exists():
        return ()
    profiles = []
    for path in sorted(PROFILE_DIR.glob("*.json")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if profile.get("profile_kind") != PROFILE_KIND:
            continue
        profile = dict(profile)
        try:
            profile["_profile_path"] = str(path.relative_to(ROOT_DIR))
        except ValueError:
            profile["_profile_path"] = str(path)
        profiles.append(profile)
    return tuple(profiles)


def unmatched_context() -> dict[str, Any]:
    return {
        "matched": False,
        "template_name": None,
        "template_slug": None,
        "confidence_level": None,
        "ambiguous": False,
        "candidate_templates": [],
        "candidate_slugs": [],
        "track_roles": {},
        "known_control_routes": [],
        "summary": {
            "template_name": None,
            "matched": False,
            "reserved_placeholders": 0,
            "premaster_tracks": 0,
            "stem_bus_tracks": 0,
            "source_tracks": 0,
            "sidechain_control_tracks": 0,
        },
        "notes": [],
    }


def annotate_tracks(
    tracks: Iterable[Mapping[str, Any]],
    template_context: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return track rows with template metadata attached."""
    roles = _roles(template_context)
    out: list[dict[str, Any]] = []
    for row in tracks:
        item = dict(row)
        idx = _track_index(item)
        role = roles.get(idx)
        if role:
            item["template_role"] = role.get("role")
            item["template_name"] = role.get("template")
            item["template_reason"] = role.get("reason")
            item["template_tool_policy"] = dict(role.get("tool_policy") or {})
        out.append(item)
    return out


def compact_context(template_context: Mapping[str, Any]) -> dict[str, Any] | None:
    """Compact user-facing template context."""
    if not template_context.get("matched"):
        return None
    summary = dict(template_context.get("summary") or {})
    return {
        "template_name": template_context.get("template_name"),
        "template_slug": template_context.get("template_slug"),
        "confidence_level": template_context.get("confidence_level"),
        "ambiguous": bool(template_context.get("ambiguous")),
        "candidate_templates": list(template_context.get("candidate_templates") or []),
        "candidate_slugs": list(template_context.get("candidate_slugs") or []),
        "summary": summary,
        "notes": list(template_context.get("notes") or []),
        "kb_refs": list(template_context.get("kb_refs") or []),
    }


def role_for(template_context: Mapping[str, Any], track: int | None) -> str | None:
    """Return the classified role for a track, if any."""
    if track is None:
        return None
    role = _roles(template_context).get(int(track))
    return str(role.get("role")) if role else None


def policy_for(template_context: Mapping[str, Any], track: int | None) -> dict[str, bool]:
    """Return the profile-derived tool policy for a track."""
    if track is None:
        return {}
    role = _roles(template_context).get(int(track))
    if not role:
        return {}
    policy = role.get("tool_policy")
    return dict(policy) if isinstance(policy, Mapping) else {}


def suppresses(template_context: Mapping[str, Any], track: int | None, key: str) -> bool:
    """Whether the matched template profile suppresses a tool warning."""
    if key not in _POLICY_KEYS:
        return False
    return bool(policy_for(template_context, track).get(key))


def is_reserved_placeholder(template_context: Mapping[str, Any], track: int | None) -> bool:
    return role_for(template_context, track) == ROLE_RESERVED_PLACEHOLDER


def is_template_bus(template_context: Mapping[str, Any], track: int | None) -> bool:
    return role_for(template_context, track) in {
        ROLE_PREMASTER,
        ROLE_STEM_BUS,
        ROLE_SIDECHAIN_CONTROL,
    }


def is_template_control_route(
    template_context: Mapping[str, Any],
    src: int | None,
    dst: int | None,
    level: Any = None,
) -> bool:
    """Whether a route is a known non-audio/control route in a matched template."""
    if src is None or dst is None:
        return False
    src_i = int(src)
    dst_i = int(dst)
    val = _as_float(level)
    for route in template_context.get("known_control_routes") or []:
        if _as_int(route.get("source")) != src_i:
            continue
        targets = {_as_int(target) for target in route.get("targets", [])}
        if dst_i not in targets:
            continue
        expected = _as_float(route.get("level"))
        if expected is None or val is None:
            return True
        if abs(val - expected) <= 0.0001:
            return True
    return False


def _score_profile(
    profile: Mapping[str, Any],
    name_by: Mapping[int, str],
    route_by: Mapping[int, list],
    channel_by: Mapping[int, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    profile_tracks = [
        row for row in profile.get("mixer_tracks", []) if isinstance(row, Mapping)
    ]
    non_reserved = [
        row
        for row in profile_tracks
        if _profile_role(row.get("role")) != ROLE_RESERVED_PLACEHOLDER
        and _as_int(row.get("index")) is not None
        and row.get("name") is not None
    ]
    source_named = [
        row
        for row in non_reserved
        if _profile_role(row.get("role")) in {ROLE_SOURCE, ROLE_UTILITY}
    ]
    anchor_named = [
        row
        for row in non_reserved
        if _profile_role(row.get("role"))
        in {ROLE_MASTER, ROLE_PREMASTER, ROLE_STEM_BUS, ROLE_SIDECHAIN_CONTROL}
    ]

    source_name_matches = _name_matches(source_named, name_by)
    anchor_name_matches = _name_matches(anchor_named, name_by)
    all_name_matches = _name_matches(non_reserved, name_by)

    required_routes = profile.get("template_detection", {}).get("required_routes") or []
    route_matches = 0
    for row in required_routes:
        source = _as_int(row.get("source"))
        targets = {_as_int(target) for target in row.get("targets", [])}
        targets.discard(None)
        if source is not None and targets.issubset(_route_dests(route_by.get(source, []))):
            route_matches += 1

    channel_total, channel_matches = _channel_matches(profile, channel_by or {})
    placeholder_matches = _placeholder_matches(profile, name_by, route_by)
    min_placeholders = _as_int(
        profile.get("template_detection", {}).get("reserved_placeholder_min_count")
    ) or 0
    placeholder_ok = placeholder_matches >= min_placeholders
    anchor_total = max(1, len(anchor_named))
    route_total = max(1, len(required_routes))
    source_total = max(1, len(source_named))
    source_required = max(1, min(source_total, int(source_total * 0.75)))
    anchor_required = max(3, min(anchor_total, int(anchor_total * 0.75)))
    route_required = max(3, min(route_total, int(route_total * 0.75)))
    matched = (
        anchor_name_matches >= anchor_required
        and route_matches >= route_required
        and source_name_matches >= source_required
        and placeholder_ok
    )
    score = (
        anchor_name_matches * 12
        + route_matches * 8
        + source_name_matches * 10
        + channel_matches * 20
        + all_name_matches
        + min(placeholder_matches, 20)
    )
    return {
        "matched": matched,
        "score": score,
        "profile": profile,
        "anchor_name_matches": anchor_name_matches,
        "source_name_matches": source_name_matches,
        "all_name_matches": all_name_matches,
        "route_matches": route_matches,
        "channel_matches": channel_matches,
        "channel_total": channel_total,
        "placeholder_matches": placeholder_matches,
        "profile_track_count": len(profile_tracks),
    }


def _context_from_match(
    best: Mapping[str, Any],
    tied: Iterable[Mapping[str, Any]],
    name_by: Mapping[int, str],
    route_by: Mapping[int, list],
) -> dict[str, Any]:
    profile = best["profile"]
    tied_profiles = [match["profile"] for match in tied]
    candidate_names = _unique_values(p.get("template_name") for p in tied_profiles)
    candidate_slugs = _unique_values(p.get("template_slug") for p in tied_profiles)
    roles = _track_roles_from_profile(profile, name_by, route_by)
    role_counts: dict[str, int] = {}
    for row in roles.values():
        role = str(row.get("role") or "")
        role_counts[role] = role_counts.get(role, 0) + 1

    reserved_placeholders = role_counts.get(ROLE_RESERVED_PLACEHOLDER, 0)
    summary = {
        "template_name": profile.get("template_name"),
        "template_slug": profile.get("template_slug"),
        "matched": True,
        "reserved_placeholders": reserved_placeholders,
        "reserved_placeholder_ranges": [
            [row.get("from"), row.get("to")] for row in profile.get("reserved_ranges", [])
        ],
        "premaster_tracks": role_counts.get(ROLE_PREMASTER, 0),
        "stem_bus_tracks": role_counts.get(ROLE_STEM_BUS, 0),
        "source_tracks": role_counts.get(ROLE_SOURCE, 0),
        "sidechain_control_tracks": role_counts.get(ROLE_SIDECHAIN_CONTROL, 0),
    }

    notes = [
        f"{profile.get('template_name')} template profile detected; preserve its mixer topology.",
        "Template-reserved placeholders are reservations, not cleanup targets.",
    ]
    ambiguous = len(candidate_names) > 1
    if ambiguous:
        notes.append(
            "Multiple template profiles share this mixer topology; exact template "
            "name is ambiguous from mixer/routing/channel readbacks alone."
        )

    kb_refs = [
        str(profile.get("_profile_path"))
        for profile in tied_profiles
        if profile.get("_profile_path")
    ]
    if profile.get("template_name") == ELECTRO_TEMPLATE_NAME:
        kb_refs.append("knowledgebase/templates/electro_template_mixer_setup.json")

    return {
        "matched": True,
        "template_name": profile.get("template_name"),
        "template_slug": profile.get("template_slug"),
        "confidence_level": (profile.get("source") or {}).get("confidence"),
        "ambiguous": ambiguous,
        "candidate_templates": candidate_names,
        "candidate_slugs": candidate_slugs,
        "track_roles": roles,
        "known_control_routes": list(profile.get("known_control_routes") or []),
        "summary": summary,
        "notes": notes,
        "evidence": {
            "score": best["score"],
            "anchor_name_matches": best["anchor_name_matches"],
            "source_name_matches": best["source_name_matches"],
            "route_matches": best["route_matches"],
            "channel_matches": best["channel_matches"],
            "placeholder_matches": best["placeholder_matches"],
        },
        "kb_refs": _unique_values(kb_refs),
    }


def _track_roles_from_profile(
    profile: Mapping[str, Any],
    name_by: Mapping[int, str],
    route_by: Mapping[int, list],
) -> dict[int, dict[str, Any]]:
    roles: dict[int, dict[str, Any]] = {}
    template = str(profile.get("template_name") or "")
    for row in profile.get("mixer_tracks") or []:
        if not isinstance(row, Mapping):
            continue
        idx = _as_int(row.get("index"))
        if idx is None:
            continue
        role = _profile_role(row.get("role"))
        if role == ROLE_RESERVED_PLACEHOLDER:
            if not _live_track_matches_reserved_profile(row, name_by, route_by):
                continue
        elif name_by.get(idx) != str(row.get("name") or ""):
            continue
        roles[idx] = _role(
            role,
            template,
            f"{template} profile role: {row.get('role')}",
            row.get("tool_policy"),
        )

    for reserved_range in profile.get("reserved_ranges") or []:
        start = _as_int(reserved_range.get("from"))
        end = _as_int(reserved_range.get("to"))
        if start is None or end is None:
            continue
        targets = {_as_int(target) for target in reserved_range.get("default_routes_to", [])}
        targets.discard(None)
        for idx in range(start, end + 1):
            if not _is_default_insert_name(idx, name_by.get(idx)):
                continue
            if targets and not targets.issubset(_route_dests(route_by.get(idx, []))):
                continue
            roles[idx] = _role(
                ROLE_RESERVED_PLACEHOLDER,
                template,
                reserved_range.get("reason") or f"{template} reserved placeholder",
                _reserved_policy(),
            )
    return roles


def _live_track_matches_reserved_profile(
    row: Mapping[str, Any],
    name_by: Mapping[int, str],
    route_by: Mapping[int, list],
) -> bool:
    idx = _as_int(row.get("index"))
    if idx is None:
        return False
    if name_by.get(idx) != str(row.get("name") or ""):
        return False
    targets = {_as_int(route.get("target")) for route in row.get("routes_to", [])}
    targets.discard(None)
    return targets.issubset(_route_dests(route_by.get(idx, [])))


def _profile_role(role: Any) -> str:
    if role == PROFILE_RESERVED_ROLE:
        return ROLE_RESERVED_PLACEHOLDER
    if role in {
        ROLE_MASTER,
        ROLE_PREMASTER,
        ROLE_STEM_BUS,
        ROLE_SOURCE,
        ROLE_SIDECHAIN_CONTROL,
        ROLE_UTILITY,
        ROLE_UNKNOWN,
    }:
        return str(role)
    return ROLE_UNKNOWN


def _role(
    role: str,
    template: str,
    reason: str,
    tool_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "role": role,
        "template": template,
        "reason": reason,
        "tool_policy": _normalise_policy(tool_policy, role),
    }


def _normalise_policy(policy: Mapping[str, Any] | None, role: str) -> dict[str, bool]:
    out = {key: False for key in _POLICY_KEYS}
    if isinstance(policy, Mapping):
        for key in _POLICY_KEYS:
            out[key] = bool(policy.get(key))
    if role == ROLE_RESERVED_PLACEHOLDER:
        out.update(_reserved_policy())
    return out


def _reserved_policy() -> dict[str, bool]:
    return {key: True for key in _POLICY_KEYS}


def _name_matches(profile_tracks: Iterable[Mapping[str, Any]], name_by: Mapping[int, str]) -> int:
    matches = 0
    for row in profile_tracks:
        idx = _as_int(row.get("index"))
        if idx is not None and name_by.get(idx) == str(row.get("name") or ""):
            matches += 1
    return matches


def _channel_matches(
    profile: Mapping[str, Any],
    channel_by: Mapping[int, Mapping[str, Any]],
) -> tuple[int, int]:
    rows = [
        row
        for row in profile.get("channel_routes", [])
        if isinstance(row, Mapping) and _as_int(row.get("channel_index")) is not None
    ]
    if not rows or not channel_by:
        return len(rows), 0
    matches = 0
    for row in rows:
        idx = _as_int(row.get("channel_index"))
        live = channel_by.get(idx)
        if not live:
            continue
        if str(live.get("name") or "") != str(row.get("channel_name") or ""):
            continue
        if _as_int(live.get("target_mixer_track")) != _as_int(row.get("target_mixer_track")):
            continue
        matches += 1
    return len(rows), matches


def _placeholder_matches(
    profile: Mapping[str, Any],
    name_by: Mapping[int, str],
    route_by: Mapping[int, list],
) -> int:
    matched: set[int] = set()
    for row in profile.get("reserved_ranges") or []:
        start = _as_int(row.get("from"))
        end = _as_int(row.get("to"))
        if start is None or end is None:
            continue
        targets = {_as_int(target) for target in row.get("default_routes_to", [])}
        targets.discard(None)
        for idx in range(start, end + 1):
            if not _is_default_insert_name(idx, name_by.get(idx)):
                continue
            if targets and not targets.issubset(_route_dests(route_by.get(idx, []))):
                continue
            matched.add(idx)
    for row in profile.get("mixer_tracks") or []:
        if _profile_role(row.get("role")) != ROLE_RESERVED_PLACEHOLDER:
            continue
        idx = _as_int(row.get("index"))
        if idx is not None and _live_track_matches_reserved_profile(row, name_by, route_by):
            matched.add(idx)
    return len(matched)


def _channels_by_index(
    channel_rows: Iterable[Mapping[str, Any]],
) -> dict[int, Mapping[str, Any]]:
    out = {}
    for row in channel_rows:
        idx = _as_int(row.get("channel", row.get("channel_index")))
        if idx is None:
            continue
        item = dict(row)
        if "name" not in item and "channel_name" in item:
            item["name"] = item.get("channel_name")
        out[idx] = item
    return out


def _normalise_track(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    idx = _track_index(out)
    out["index"] = idx
    return out


def _track_index(row: Mapping[str, Any]) -> int | None:
    idx = row.get("i", row.get("index", row.get("track")))
    return _as_int(idx)


def _route_dests(routes: Iterable[Any]) -> set[int]:
    out: set[int] = set()
    for route in routes or []:
        dst = route.get("dst", route.get("target")) if isinstance(route, Mapping) else route
        parsed = _as_int(dst)
        if parsed is not None:
            out.add(parsed)
    return out


def _is_default_insert_name(index: int, name: str | None) -> bool:
    match = _DEFAULT_INSERT_RE.match(str(name or ""))
    return bool(match and int(match.group(1)) == int(index))


def _roles(template_context: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    raw = template_context.get("track_roles") or {}
    out: dict[int, Mapping[str, Any]] = {}
    for key, value in raw.items():
        parsed = _as_int(key)
        if parsed is not None:
            out[parsed] = value
    return out


def _channel_summary(
    channel_rows: Iterable[Mapping[str, Any]],
    template_context: Mapping[str, Any],
) -> dict[str, Any]:
    by_role: dict[str, int] = {}
    for row in channel_rows:
        track = row.get("target_mixer_track")
        role = role_for(template_context, int(track)) if isinstance(track, int) else None
        if role:
            by_role[role] = by_role.get(role, 0) + 1
    return {"target_roles": by_role}


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


def _unique_values(values: Iterable[Any]) -> list[Any]:
    out = []
    seen = set()
    for value in values:
        if value in (None, "") or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
