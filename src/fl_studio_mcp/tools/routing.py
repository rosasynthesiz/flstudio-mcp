"""Routing / grouping / cleanup tools -- Slice 1: READ ONLY.

Reports the mixer routing matrix, channel->mixer assignments, and flags
cleanup candidates (empty channels / unused mixer tracks). No writes, no
renames, no deletes -- that's a later slice.

Design: the CONTROLLER only returns cheap RAW data (per-channel name+target,
per-track name+routes, per-track plugin slots). All empty/unused JUDGEMENT
happens HERE on the server (plain Python, no sandbox loop limit), aggregating
several cheap controller reads -- instead of asking the controller to scan
everything in a single OnSysEx tick (which stalls FL).
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import kb_policy, operations, protocol, safety
from .. import project_templates as templates
from ..connection import fetch_all_pages, get_bridge
from .targets import mixer_track_error


def _route_write_entry(src: int, dst: int, enabled: bool) -> dict:
    """One safe_write_group entry that sets a route and restores its prior state."""
    return operations.prepare_operation(
        "mixer", "set_route", {"src": src, "dst": dst, "enabled": enabled}
    ).safe_write_group_entry()


def _bus_rename_entry(bus: int, name: str) -> dict:
    """One safe_write_group entry that renames a track and restores its old name."""
    return operations.prepare_operation(
        "mixer", "set_name", {"track": bus, "name": name}
    ).safe_write_group_entry()


# --- server-side judgement helpers (pure) -----------------------------------
def _looks_default_channel_name(name) -> bool:
    if not name:
        return True
    return str(name).split(" ")[0] in ("Channel", "Sampler", "Insert")


def _is_default_mixer_name(i, name) -> bool:
    name = name or ""
    if i == 0:
        return name in ("", "Master")
    return name in ("", f"Insert {i}")


def detect_cleanup(bridge, *, max_plugin_checks: int = 60) -> dict:
    """Aggregate cheap controller reads and decide cleanup candidates here.

    Steps (all cheap controller calls, each its own round trip):
      1. channel_routing_summary -> which mixer tracks have a channel feeding them
      2. mixer_get_routing_all   -> track names + who routes INTO each (derived)
      3. plugin_list(track)      -> ONLY for surviving candidate tracks
    Empty-channel detection is a name heuristic (the API can't cheaply see
    clip/piano-roll content); unused-mixer-track detection is reliable.
    """
    chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")
    routing = fetch_all_pages(bridge, protocol.CMD_MIXER_GET_ROUTING_ALL, "routing")
    tracks = routing.get("routing", [])
    template_context = templates.classify_topology(
        tracks, tracks, chans.get("channels", [])
    )

    targeted = set()
    for c in chans.get("channels", []):
        tgt = c.get("target_mixer_track")
        if isinstance(tgt, int):
            targeted.add(tgt)

    # incoming routes derived from the matrix -- no extra controller calls.
    incoming: dict = {}
    for r in tracks:
        for d in r.get("routes_to", []):
            incoming.setdefault(d.get("dst"), []).append(r.get("i"))

    empty = [
        {"channel": c.get("channel"), "name": c.get("name")}
        for c in chans.get("channels", [])
        if _looks_default_channel_name(c.get("name"))
    ]

    unused = []
    checks = 0
    truncated = False
    for r in tracks:
        i = r.get("i")
        if i == 0 or i in targeted:  # Master, or a channel feeds it
            continue
        if templates.is_reserved_placeholder(template_context, i):
            continue
        if not _is_default_mixer_name(i, r.get("name")):
            continue  # named -> intentional
        if incoming.get(i):  # a send feeds it -> a bus
            continue
        if checks >= max_plugin_checks:
            truncated = True
            break
        checks += 1
        if bridge.call(protocol.CMD_PLUGIN_LIST, {"track": i}).get("slots"):
            continue  # has a plugin -> in use
        unused.append({"track": i, "name": r.get("name")})

    return {
        "channel_emptiness_reliable": False,
        "empty_channel_criteria": [
            "default-looking name (NAME heuristic -- clip/piano-roll content NOT checked)"
        ],
        "empty_channel_candidates": empty,
        "unused_mixer_track_criteria": [
            "no channel linked",
            "default name",
            "no sends routed in",
            "no plugins",
            "not a recognized template-reserved placeholder",
        ],
        "unused_mixer_tracks": unused,
        "unused_mixer_track_truncated": truncated,
        "template_context": templates.compact_context(template_context),
        "note": "READ-ONLY. Judgement done server-side from cheap controller "
        "reads. Unused tracks reliable; channel emptiness is a name "
        "heuristic. Recognized template reservations are preserved. Verify "
        "before any delete (Slice 2).",
    }


def register(mcp: FastMCP) -> None:
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }
    _WR = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "write-safe",
    }

    @mcp.tool(annotations={"title": "Get mixer track routing", **_RO})
    def fl_get_routing(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
    ) -> dict:
        """Which destination tracks this mixer track sends to:
        {track, name, routes_to:[{dst, dst_name, level?}]}.

        Safety: Read-Only.
        """
        return get_bridge().call(protocol.CMD_MIXER_GET_ROUTING, {"track": track})

    @mcp.tool(annotations={"title": "Get full routing matrix", **_RO})
    def fl_get_routing_all() -> dict:
        """Routing for every mixer track (paginated under the hood, returned
        whole): {total, routing:[{i, name, routes_to:[...]}]}.

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_MIXER_GET_ROUTING_ALL, "routing")

    @mcp.tool(annotations={"title": "Get channel->mixer routing", **_RO})
    def fl_get_channel_routing() -> dict:
        """Which mixer track each channel-rack channel is linked to:
        {total, channels:[{channel, name, target_mixer_track, target_name}]}.

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")

    @mcp.tool(annotations={"title": "Detect cleanup candidates (read-only)", **_RO})
    def fl_detect_cleanup_candidates() -> dict:
        """Flag (do NOT touch) empty channels + unused mixer tracks, each with a
        reason. Judgement is computed server-side from cheap controller reads.
        Channel emptiness is a name heuristic; unused-track detection is reliable.

        Safety: Read-Only.
        """
        return detect_cleanup(get_bridge())

    @mcp.tool(annotations={"title": "Set mixer routing (src -> dst)", **_WR})
    def fl_set_route(
        src: Annotated[int, Field(ge=0, description="Source mixer track.")],
        dst: Annotated[int, Field(ge=0, description="Destination mixer track (0 = Master).")],
        enabled: Annotated[bool, Field(description="True = route on, False = off.")] = True,
    ) -> dict:
        """Enable/disable a send from src -> dst (calls afterRoutingChanged on the
        FL side). Snapshot + readback; undo with fl_rollback_last_change.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        for track, purpose in ((src, "mixer route source"), (dst, "mixer route destination")):
            error = mixer_track_error(bridge, track, purpose=purpose)
            if error is not None:
                return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_route",
            scope=f"route:{src}:{dst}",
            command=protocol.CMD_MIXER_SET_ROUTE,
            params={"src": src, "dst": dst, "enabled": enabled},
            verify=("enabled", enabled),
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_ROUTE,
                "params": {"src": src, "dst": dst, "enabled": b["enabled"]},
            },
        )

    @mcp.tool(annotations={"title": "Group tracks into a bus", **_WR})
    def fl_group_tracks(
        sources: Annotated[
            list[int], Field(description="Source mixer tracks to route into the bus.")
        ],
        bus: Annotated[int, Field(ge=1, description="Destination bus mixer track (not Master).")],
        name: Annotated[
            str | None, Field(description="Optional new name for the bus track.")
        ] = None,
    ) -> dict:
        """Group sources into a bus, EXCLUSIVELY: each source -> bus ON and its
        direct -> Master OFF; bus -> Master ON; optional bus rename. Applied as
        ONE rollback unit -- fl_rollback_last_change undoes the whole grouping.

        Safety: Write-Safe with Rollback. The routing and optional rename are
        persisted as one named rollback unit.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, bus, allow_master=False, purpose="group bus track")
        if error is not None:
            return error
        srcs = [int(s) for s in sources if int(s) not in (bus, 0)]
        for src in srcs:
            error = mixer_track_error(bridge, src, allow_master=False, purpose="group source track")
            if error is not None:
                return error
        writes = []
        for s in srcs:
            writes.append(_route_write_entry(s, bus, True))  # source -> bus ON
            writes.append(_route_write_entry(s, 0, False))  # source -> Master OFF
        writes.append(_route_write_entry(bus, 0, True))  # bus -> Master ON
        if name:
            writes.append(_bus_rename_entry(bus, name))
        if not srcs:
            return {"ok": False, "error": "no valid source tracks (excluding bus and Master)"}
        res = safety.safe_write_group(
            bridge,
            tool="group_tracks",
            scope=f"group:bus{bus}",
            writes=writes,
            rollback_unit=f"group_tracks_bus_{bus}",
        )
        if res.get("dry_run"):
            res.update({"sources": srcs, "bus": bus, "name": name})
            return res
        return {"ok": True, "sources": srcs, "bus": bus, "name": name, "applied": res.get("after")}

    # --- Phase 1: Routing Review 2.0 ---

    @mcp.tool(annotations={"title": "Review routing", **_RO})
    def fl_review_routing() -> dict:
        """Analyze project routing to find structural issues like generators routed to Master,
        unrouted channels, or missing bus structures.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")
        routing = fetch_all_pages(bridge, protocol.CMD_MIXER_GET_ROUTING_ALL, "routing")
        tracks = routing.get("routing", [])
        template_context = templates.classify_topology(
            tracks, tracks, chans.get("channels", [])
        )

        unrouted = []
        direct_to_master = []

        # Track routing map
        track_to_master = {}
        for t in tracks:
            routes = t.get("routes_to", [])
            track_to_master[t.get("i")] = any(r.get("dst") == 0 for r in routes)

        for c in chans.get("channels", []):
            tgt = c.get("target_mixer_track")
            ctype = c.get("type", {}).get("label")

            if not isinstance(tgt, int) or tgt == 0:
                if ctype != "unknown":
                    unrouted.append(
                        {"channel": c.get("channel"), "name": c.get("name"), "type": ctype}
                    )
            else:
                if (
                    track_to_master.get(tgt)
                    and ctype == "genplug"
                    and not templates.is_template_bus(template_context, tgt)
                ):
                    direct_to_master.append(
                        {
                            "channel": c.get("channel"),
                            "name": c.get("name"),
                            "mixer_track": tgt,
                            "mixer_name": next(
                                (t.get("name") for t in tracks if t.get("i") == tgt),
                                f"Insert {tgt}",
                            ),
                        }
                    )

        return {
            "unrouted_channels": unrouted,
            "generators_direct_to_master": direct_to_master,
            "template_context": templates.compact_context(template_context),
            "note": "Use this data to plan bus structures or correct routing.",
            "policy_notes": [
                "Preserve recognizable existing routing structure before proposing cleanup.",
                "Infer Channel Rack to Mixer relationships from channel target tracks, not playlist indices.",
                "Treat plugin insertion, external inputs, and UI drag-and-drop routing as manual guidance.",
            ],
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "channel_rack_workflow_requires_routing_inference",
                    "routing_ui_guidance_vs_mcp_write",
                ]
            ),
        }

    @mcp.tool(annotations={"title": "Plan routing cleanup", **_RO})
    def fl_plan_routing_cleanup(
        issues: Annotated[list[str], Field(description="List of issues identified to fix")],
        proposed_buses: Annotated[
            list[dict], Field(description="Buses to create (track, name, sources)")
        ],
    ) -> dict:
        """Create a dry-run plan for routing fixes.

        Safety: Read-Only (Dry-run).
        """
        return {
            "status": "Plan created. Please review and apply using fl_apply_routing_cleanup.",
            "issues": issues,
            "proposed_buses": proposed_buses,
            "rules": [
                "Preserve existing structure when it is recognizable.",
                "Do not infer Playlist Track N maps to Mixer Track N.",
                "Prefer bus placement before the group when it fits the current project.",
                "Use one named rollback unit for approved grouped routing writes.",
                "Keep plugin loading, external I/O, and broad UI routing manual.",
            ],
            "supported_bus_placement_policy": [
                "before_group",
                "after_group",
                "central_front",
                "central_end",
                "preserve_existing",
            ],
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "channel_rack_workflow_requires_routing_inference",
                    "routing_ui_guidance_vs_mcp_write",
                    "send_effects_for_shared_space",
                ]
            ),
        }

    @mcp.tool(annotations={"title": "Apply routing cleanup", **_WR})
    def fl_apply_routing_cleanup(
        routes: Annotated[
            list[dict], Field(description="List of route writes: {src, dst, enabled}")
        ],
        renames: Annotated[
            list[dict], Field(description="List of bus renames: {track, name}")
        ] = None,
    ) -> dict:
        """Apply multiple routing changes and track renames in one rollback unit.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        writes = []

        for r in routes:
            writes.append(_route_write_entry(r["src"], r["dst"], r.get("enabled", True)))

        if renames:
            for r in renames:
                writes.append(_bus_rename_entry(r["track"], r["name"]))

        if not writes:
            return {"status": "No writes specified."}

        res = safety.safe_write_group(
            bridge,
            tool="apply_routing_cleanup",
            scope="routing_review",
            writes=writes,
            rollback_unit="routing_cleanup_batch",
        )
        if isinstance(res, dict):
            res["kb_policy_refs"] = kb_policy.rule_refs(
                ["routing_ui_guidance_vs_mcp_write", "send_effects_for_shared_space"]
            )
        return res

    @mcp.tool(annotations={"title": "Apply bus layout", **_WR})
    def fl_apply_bus_layout(
        buses: Annotated[
            list[dict],
            Field(
                description="List of bus configs: {bus_track: int, name: str, source_tracks: list[int]}"
            ),
        ],
    ) -> dict:
        """Create multiple group buses at once. Ensures each source track sends exclusively to its assigned bus,
        and the bus routes to the Master.

        Policy:
        - Preserve existing structure where recognizable.
        - Prefer buses before their group when that fits the project.
        - Keep UI-only routing and plugin insertion manual.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        writes = []

        for b in buses:
            bus = b["bus_track"]
            name = b.get("name")
            srcs = [int(s) for s in b.get("source_tracks", []) if int(s) not in (bus, 0)]

            for s in srcs:
                writes.append(_route_write_entry(s, bus, True))  # source -> bus ON
                writes.append(_route_write_entry(s, 0, False))  # source -> Master OFF
            writes.append(_route_write_entry(bus, 0, True))  # bus -> Master ON

            if name:
                writes.append(_bus_rename_entry(bus, name))

        if not writes:
            return {"status": "No bus writes specified."}

        res = safety.safe_write_group(
            bridge,
            tool="create_bus_layout",
            scope="bus_layout",
            writes=writes,
            rollback_unit="bus_layout_creation",
        )
        if isinstance(res, dict):
            res["kb_policy_refs"] = kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "routing_ui_guidance_vs_mcp_write",
                    "send_effects_for_shared_space",
                ]
            )
        return res
