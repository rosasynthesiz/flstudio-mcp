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

from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge


def _route_write_entry(src: int, dst: int, enabled: bool) -> dict:
    """One safe_write_group entry that sets a route and restores its prior state."""
    return {
        "snap_scope": "route:%d:%d" % (src, dst),
        "command": protocol.CMD_MIXER_SET_ROUTE,
        "params": {"src": src, "dst": dst, "enabled": enabled},
        "restore": lambda b: {"command": protocol.CMD_MIXER_SET_ROUTE,
                              "params": {"src": b["src"], "dst": b["dst"],
                                         "enabled": b["enabled"]}},
    }


def _bus_rename_entry(bus: int, name: str) -> dict:
    """One safe_write_group entry that renames a track and restores its old name."""
    return {
        "snap_scope": "mixer_track:%d" % bus,
        "command": protocol.CMD_MIXER_SET_NAME,
        "params": {"track": bus, "name": name},
        "restore": lambda b: {"command": protocol.CMD_MIXER_SET_NAME,
                              "params": {"track": bus, "name": b["name"]}},
    }


# --- server-side judgement helpers (pure) -----------------------------------
def _looks_default_channel_name(name) -> bool:
    if not name:
        return True
    return str(name).split(" ")[0] in ("Channel", "Sampler", "Insert")


def _is_default_mixer_name(i, name) -> bool:
    name = name or ""
    if i == 0:
        return name in ("", "Master")
    return name in ("", "Insert %d" % i)


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

    empty = [{"channel": c.get("channel"), "name": c.get("name")}
             for c in chans.get("channels", [])
             if _looks_default_channel_name(c.get("name"))]

    unused = []
    checks = 0
    truncated = False
    for r in tracks:
        i = r.get("i")
        if i == 0 or i in targeted:                 # Master, or a channel feeds it
            continue
        if not _is_default_mixer_name(i, r.get("name")):
            continue                                # named -> intentional
        if incoming.get(i):                         # a send feeds it -> a bus
            continue
        if checks >= max_plugin_checks:
            truncated = True
            break
        checks += 1
        if bridge.call(protocol.CMD_PLUGIN_LIST, {"track": i}).get("slots"):
            continue                                # has a plugin -> in use
        unused.append({"track": i, "name": r.get("name")})

    return {
        "channel_emptiness_reliable": False,
        "empty_channel_criteria": ["default-looking name "
                                   "(NAME heuristic -- clip/piano-roll content NOT checked)"],
        "empty_channel_candidates": empty,
        "unused_mixer_track_criteria": ["no channel linked", "default name",
                                        "no sends routed in", "no plugins"],
        "unused_mixer_tracks": unused,
        "unused_mixer_track_truncated": truncated,
        "note": "READ-ONLY. Judgement done server-side from cheap controller "
                "reads. Unused tracks reliable; channel emptiness is a name "
                "heuristic. Verify before any delete (Slice 2).",
    }


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Get mixer track routing", **_RO})
    def fl_get_routing(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
    ) -> dict:
        """Which destination tracks this mixer track sends to:
        {track, name, routes_to:[{dst, dst_name, level?}]}."""
        return get_bridge().call(protocol.CMD_MIXER_GET_ROUTING, {"track": track})

    @mcp.tool(annotations={"title": "Get full routing matrix", **_RO})
    def fl_get_routing_all() -> dict:
        """Routing for every mixer track (paginated under the hood, returned
        whole): {total, routing:[{i, name, routes_to:[...]}]}."""
        return fetch_all_pages(get_bridge(), protocol.CMD_MIXER_GET_ROUTING_ALL, "routing")

    @mcp.tool(annotations={"title": "Get channel->mixer routing", **_RO})
    def fl_get_channel_routing() -> dict:
        """Which mixer track each channel-rack channel is linked to:
        {total, channels:[{channel, name, target_mixer_track, target_name}]}."""
        return fetch_all_pages(get_bridge(), protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")

    @mcp.tool(annotations={"title": "Detect cleanup candidates (read-only)", **_RO})
    def fl_detect_cleanup_candidates() -> dict:
        """Flag (do NOT touch) empty channels + unused mixer tracks, each with a
        reason. Judgement is computed server-side from cheap controller reads.
        Channel emptiness is a name heuristic; unused-track detection is reliable."""
        return detect_cleanup(get_bridge())

    @mcp.tool(annotations={"title": "Set mixer routing (src -> dst)", **_WR})
    def fl_set_route(
        src: Annotated[int, Field(ge=0, description="Source mixer track.")],
        dst: Annotated[int, Field(ge=0, description="Destination mixer track (0 = Master).")],
        enabled: Annotated[bool, Field(description="True = route on, False = off.")] = True,
    ) -> dict:
        """Enable/disable a send from src -> dst (calls afterRoutingChanged on the
        FL side). Snapshot + readback; undo with fl_rollback_last_change."""
        return safety.safe_write(
            get_bridge(), tool="mixer_set_route", scope="route:%d:%d" % (src, dst),
            command=protocol.CMD_MIXER_SET_ROUTE,
            params={"src": src, "dst": dst, "enabled": enabled},
            verify=("enabled", enabled),
            build_restore=lambda b: {"command": protocol.CMD_MIXER_SET_ROUTE,
                                     "params": {"src": src, "dst": dst, "enabled": b["enabled"]}})

    @mcp.tool(annotations={"title": "Group tracks into a bus", **_WR})
    def fl_group_tracks(
        sources: Annotated[List[int], Field(description="Source mixer tracks to route into the bus.")],
        bus: Annotated[int, Field(ge=1, description="Destination bus mixer track (not Master).")],
        name: Annotated[Optional[str], Field(description="Optional new name for the bus track.")] = None,
    ) -> dict:
        """Group sources into a bus, EXCLUSIVELY: each source -> bus ON and its
        direct -> Master OFF; bus -> Master ON; optional bus rename. Applied as
        ONE rollback unit -- fl_rollback_last_change undoes the whole grouping."""
        bridge = get_bridge()
        srcs = [int(s) for s in sources if int(s) not in (bus, 0)]
        writes = []
        for s in srcs:
            writes.append(_route_write_entry(s, bus, True))    # source -> bus ON
            writes.append(_route_write_entry(s, 0, False))     # source -> Master OFF
        writes.append(_route_write_entry(bus, 0, True))        # bus -> Master ON
        if name:
            writes.append(_bus_rename_entry(bus, name))
        if not srcs:
            return {"ok": False, "error": "no valid source tracks (excluding bus and Master)"}
        res = safety.safe_write_group(bridge, tool="group_tracks",
                                      scope="group:bus%d" % bus, writes=writes)
        if res.get("dry_run"):
            res.update({"sources": srcs, "bus": bus, "name": name})
            return res
        return {"ok": True, "sources": srcs, "bus": bus, "name": name,
                "applied": res.get("after")}
