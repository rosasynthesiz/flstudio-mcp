"""Bulk mute/solo -- server-side orchestration over the existing per-track
mute/solo commands. No new controller handlers.

"Solo a group" is implemented as muting the COMPLEMENT (mute every other track):
reliable and reversible, where FL's multi-track solo is inconsistent. Bulk writes
go through safety.safe_write_group as ONE rollback unit; fl_clear_mute_solo is the
universal reset.
"""
from __future__ import annotations

from typing import Annotated, List, Optional, Union

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from ..music.mix_doctor import FAMILIES


def _tracks(bridge):
    raw = (fetch_all_pages(bridge, protocol.CMD_MIXER_LIST_TRACKS, "tracks") or {}).get("tracks", [])
    return [{"index": t.get("i", t.get("index")), "name": t.get("name") or "",
             "mute": bool(t.get("mute")), "solo": bool(t.get("solo"))} for t in raw]


def resolve_targets(tracks, category=None, names=None):
    """Track indices matching a category (a FAMILIES role, or any name substring)
    and/or an explicit list of names/indices. Master (0) is excluded. PURE."""
    out = set()
    if category:
        c = str(category).lower()
        keywords = FAMILIES.get(c, (c,))           # known role -> its keywords; else literal
        for t in tracks:
            if t["index"] != 0 and any(k in t["name"].lower() for k in keywords):
                out.add(t["index"])
    for spec in (names or []):
        if isinstance(spec, int):
            if spec != 0:
                out.add(spec)
        else:
            s = str(spec).lower()
            for t in tracks:
                if t["index"] != 0 and s in t["name"].lower():
                    out.add(t["index"])
    return out


def _mute_writes(indices, state):
    return [{"snap_scope": "mixer_track:%d" % i, "command": protocol.CMD_MIXER_SET_MUTE,
             "params": {"track": i, "state": state},
             "restore": (lambda b, i=i: {"command": protocol.CMD_MIXER_SET_MUTE,
                                         "params": {"track": i, "state": b["mute"]}})}
            for i in sorted(indices)]


def register(mcp: FastMCP) -> None:
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": False, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Solo a group of tracks", **_WR})
    def fl_solo_tracks(
        category: Annotated[Optional[str], Field(description="Role to isolate: 'drums', 'vocals', 'bass', 'synth', 'guitar' (or any track-name substring).")] = None,
        tracks: Annotated[Optional[List[Union[int, str]]], Field(description="Explicit track indices or name substrings to keep audible.")] = None,
    ) -> dict:
        """Isolate a group so only it is audible -- mutes every OTHER (non-Master)
        track. Use category ('drums', etc.) or explicit tracks. Implemented as
        mute-the-rest (reliable; FL's multi-solo is inconsistent). Reverse with
        fl_clear_mute_solo. One rollback unit."""
        if not category and not tracks:
            return {"ok": False, "error": "give a category or a tracks list"}
        b = get_bridge()
        ts = _tracks(b)
        keep = resolve_targets(ts, category, tracks)
        if not keep:
            return {"ok": False, "error": "no tracks matched", "category": category, "tracks": tracks}
        to_mute = [t["index"] for t in ts if t["index"] != 0 and not t["mute"] and t["index"] not in keep]
        if not to_mute:
            return {"ok": True, "kept": sorted(keep), "muted": [], "note": "everything else was already muted"}
        try:
            safety.safe_write_group(b, tool="bulk_solo", scope="mixer:bulk", writes=_mute_writes(to_mute, True))
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        return {"ok": True, "kept": sorted(keep), "muted": to_mute,
                "undo": "fl_clear_mute_solo to restore"}

    @mcp.tool(annotations={"title": "Mute a group of tracks", **_WR})
    def fl_mute_tracks(
        category: Annotated[Optional[str], Field(description="Role to mute (or any track-name substring).")] = None,
        tracks: Annotated[Optional[List[Union[int, str]]], Field(description="Explicit track indices or name substrings to mute.")] = None,
    ) -> dict:
        """Mute a group of tracks (leaves the others as they are). Use category or
        explicit tracks. One rollback unit; reverse with fl_clear_mute_solo."""
        if not category and not tracks:
            return {"ok": False, "error": "give a category or a tracks list"}
        b = get_bridge()
        ts = _tracks(b)
        targets = resolve_targets(ts, category, tracks)
        muted_now = {t["index"] for t in ts if t["mute"]}
        to_mute = [i for i in sorted(targets) if i not in muted_now]
        if not to_mute:
            return {"ok": True, "muted": [], "note": "matched tracks already muted, or none matched"}
        try:
            safety.safe_write_group(b, tool="bulk_mute", scope="mixer:bulk", writes=_mute_writes(to_mute, True))
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        return {"ok": True, "muted": to_mute, "undo": "fl_clear_mute_solo to restore"}

    @mcp.tool(annotations={"title": "Clear all mutes + solos", **_WR})
    def fl_clear_mute_solo() -> dict:
        """Unmute and unsolo every mixer track (reset). The universal undo for the
        bulk solo/mute tools."""
        b = get_bridge()
        ts = _tracks(b)
        writes = []
        for t in ts:
            i = t["index"]
            if t["mute"]:
                writes.append({"snap_scope": "mixer_track:%d" % i, "command": protocol.CMD_MIXER_SET_MUTE,
                               "params": {"track": i, "state": False},
                               "restore": (lambda b, i=i: {"command": protocol.CMD_MIXER_SET_MUTE,
                                                           "params": {"track": i, "state": b["mute"]}})})
            if t["solo"]:
                writes.append({"snap_scope": "mixer_track:%d" % i, "command": protocol.CMD_MIXER_SET_SOLO,
                               "params": {"track": i, "state": False},
                               "restore": (lambda b, i=i: {"command": protocol.CMD_MIXER_SET_SOLO,
                                                           "params": {"track": i, "state": b["solo"]}})})
        if not writes:
            return {"ok": True, "cleared": 0, "note": "no mutes or solos were set"}
        try:
            safety.safe_write_group(b, tool="clear_mute_solo", scope="mixer:bulk", writes=writes)
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        return {"ok": True, "cleared": len(writes)}
