"""Track / channel coloring.

The controller applies a raw color (FL builds the int via utils.RGBToColor);
the judgement -- turning "red" or "#33A1FF" into r,g,b and picking which tracks
to paint -- lives here, server-side. Targets reuse resolve_targets (from the
bulk tools) so "color my drums red" / "bass blue" hit families or name
substrings. Every write goes through safe_write_group as ONE rollback unit, so
fl_rollback_last_change restores the previous colors in a single step.
"""
from __future__ import annotations

from typing import Annotated, List, Optional, Union

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from .bulk import resolve_targets


# A small, clear palette -- (R, G, B), 0-255. Lowercased name -> rgb. Anything
# not here can still be given as a hex string.
COLOR_NAMES = {
    "red": (229, 57, 53),
    "orange": (251, 140, 0),
    "amber": (255, 179, 0),
    "yellow": (253, 216, 53),
    "lime": (192, 202, 51),
    "green": (67, 160, 71),
    "teal": (0, 150, 136),
    "cyan": (0, 188, 212),
    "blue": (33, 150, 243),
    "indigo": (57, 73, 171),
    "purple": (156, 39, 176),
    "violet": (149, 117, 205),
    "magenta": (216, 27, 96),
    "pink": (236, 64, 122),
    "brown": (121, 85, 72),
    "gray": (158, 158, 158),
    "grey": (158, 158, 158),
    "white": (255, 255, 255),
    "black": (33, 33, 33),
}

_HEXCHARS = set("0123456789abcdef")


def parse_color(spec):
    """'red' | '#33A1FF' | '33A1FF' | '#F0A' (3-digit) -> (r, g, b) 0-255, or None. PURE."""
    if spec is None:
        return None
    s = str(spec).strip().lower()
    if s in COLOR_NAMES:
        return COLOR_NAMES[s]
    h = s[1:] if s.startswith("#") else s
    if len(h) == 3 and all(ch in _HEXCHARS for ch in h):
        h = "".join(ch * 2 for ch in h)
    if len(h) == 6 and all(ch in _HEXCHARS for ch in h):
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return None


def _mixer_tracks(bridge):
    raw = (fetch_all_pages(bridge, protocol.CMD_MIXER_LIST_TRACKS, "tracks") or {}).get("tracks", [])
    return [{"index": t.get("i", t.get("index")), "name": t.get("name") or ""} for t in raw]


def _rack_channels(bridge):
    raw = (fetch_all_pages(bridge, protocol.CMD_CHANNEL_LIST, "channels") or {}).get("channels", [])
    return [{"index": c.get("i", c.get("index")), "name": c.get("name") or ""} for c in raw]


def _resolve_channels(chans, specs):
    """Channel indices from explicit indices and/or name substrings. PURE.
    (Channel 0 is a real channel -- unlike Master on the mixer -- so nothing is
    excluded.)"""
    out = set()
    for spec in (specs or []):
        if isinstance(spec, int):
            out.add(spec)
        else:
            s = str(spec).lower()
            for c in chans:
                if s in c["name"].lower():
                    out.add(c["index"])
    return out


def _before_int(before):
    return (before.get("color") or {}).get("int", 0) if isinstance(before, dict) else 0


def register(mcp: FastMCP) -> None:
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": False, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Color mixer tracks", **_WR})
    def fl_set_track_color(
        color: Annotated[str, Field(description="Color name (red, orange, amber, yellow, lime, green, teal, cyan, blue, indigo, purple, violet, magenta, pink, brown, gray, white, black) or a hex like '#33A1FF'.")],
        category: Annotated[Optional[str], Field(description="Group to color: 'drums', 'vocals', 'bass', 'synth', 'guitar' (or any mixer-track name substring).")] = None,
        tracks: Annotated[Optional[List[Union[int, str]]], Field(description="Explicit mixer-track indices or name substrings.")] = None,
    ) -> dict:
        """Set the color of mixer tracks. Pick targets by category ('drums',
        'bass', ...) or an explicit tracks list; choose a color by name or hex.
        All writes are ONE rollback unit -- fl_rollback_last_change reverts them.
        (Master is never colored.)"""
        rgb = parse_color(color)
        if rgb is None:
            return {"ok": False, "error": "unknown color %r" % color,
                    "valid_names": sorted(COLOR_NAMES), "hint": "or pass a hex like '#33A1FF'"}
        if not category and not tracks:
            return {"ok": False, "error": "give a category (e.g. 'drums') or a tracks list"}
        b = get_bridge()
        targets = sorted(resolve_targets(_mixer_tracks(b), category, tracks))
        if not targets:
            return {"ok": False, "error": "no tracks matched", "category": category, "tracks": tracks}
        r, g, bl = rgb
        writes = [{
            "snap_scope": "mixer_track:%d" % i,
            "command": protocol.CMD_MIXER_SET_COLOR,
            "params": {"track": i, "r": r, "g": g, "b": bl},
            "restore": (lambda before, i=i: {
                "command": protocol.CMD_MIXER_SET_COLOR,
                "params": {"track": i, "color": _before_int(before)},
            }),
        } for i in targets]
        try:
            res = safety.safe_write_group(b, tool="set_track_color", scope="mixer:color", writes=writes)
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        return {"ok": True, "color": color, "rgb": list(rgb), "tracks": targets,
                "result": res, "undo": "fl_rollback_last_change"}

    @mcp.tool(annotations={"title": "Color channels", **_WR})
    def fl_set_channel_color(
        color: Annotated[str, Field(description="Color name or hex (same set as fl_set_track_color).")],
        channels: Annotated[Optional[List[Union[int, str]]], Field(description="Channel-rack indices or name substrings to color.")] = None,
    ) -> dict:
        """Set the color of channel-rack channels (separate from mixer-track
        color). Target by index or name substring. ONE rollback unit --
        fl_rollback_last_change reverts it."""
        rgb = parse_color(color)
        if rgb is None:
            return {"ok": False, "error": "unknown color %r" % color,
                    "valid_names": sorted(COLOR_NAMES), "hint": "or pass a hex like '#33A1FF'"}
        if not channels:
            return {"ok": False, "error": "give a channels list (indices or name substrings)"}
        b = get_bridge()
        targets = sorted(_resolve_channels(_rack_channels(b), channels))
        if not targets:
            return {"ok": False, "error": "no channels matched", "channels": channels}
        r, g, bl = rgb
        writes = [{
            "snap_scope": "channel:%d" % i,
            "command": protocol.CMD_CHANNEL_SET_COLOR,
            "params": {"channel": i, "r": r, "g": g, "b": bl},
            "restore": (lambda before, i=i: {
                "command": protocol.CMD_CHANNEL_SET_COLOR,
                "params": {"channel": i, "color": _before_int(before)},
            }),
        } for i in targets]
        try:
            res = safety.safe_write_group(b, tool="set_channel_color", scope="channels:color", writes=writes)
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        return {"ok": True, "color": color, "rgb": list(rgb), "channels": targets,
                "result": res, "undo": "fl_rollback_last_change"}
