"""Playlist track control (Tier 1) + arrangement read.

Playlist tracks are 1-based. Mute/solo/rename/color route through the safety
layer (snapshot -> write -> readback -> rollback) using the ``playlist_track``
snapshot scope. Arrangement selection/markers are read-only.

FL API limit (confirmed): the playlist timeline can't be authored via scripting
(no addClip/placeClip), so this controls TRACK state + reads the timeline; it
does not place clips.
"""
from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from .color import parse_color


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "List playlist tracks", **_RO})
    def fl_playlist_tracks() -> dict:
        """List playlist tracks (1-based) with name + mute/solo state."""
        return fetch_all_pages(get_bridge(), protocol.CMD_PLAYLIST_TRACK_LIST, "tracks")

    @mcp.tool(annotations={"title": "Mute/unmute a playlist track", **_WR})
    def fl_playlist_mute_track(
        track: Annotated[int, Field(ge=1, description="1-based playlist track.")],
        muted: Annotated[bool, Field(description="True = muted, False = unmuted.")] = True,
    ) -> dict:
        """Set a playlist track's mute state (reversible)."""
        b = get_bridge()
        return safety.safe_write(
            b, tool="playlist_mute_track", scope="playlist_track:%d" % track,
            command=protocol.CMD_PLAYLIST_MUTE_TRACK, params={"track": track, "state": muted},
            build_restore=lambda before: {"command": protocol.CMD_PLAYLIST_MUTE_TRACK,
                                           "params": {"track": track, "state": before["muted"]}})

    @mcp.tool(annotations={"title": "Solo/unsolo a playlist track", **_WR})
    def fl_playlist_solo_track(
        track: Annotated[int, Field(ge=1, description="1-based playlist track.")],
        solo: Annotated[bool, Field(description="True = solo, False = unsolo.")] = True,
    ) -> dict:
        """Set a playlist track's solo state (reversible)."""
        b = get_bridge()
        return safety.safe_write(
            b, tool="playlist_solo_track", scope="playlist_track:%d" % track,
            command=protocol.CMD_PLAYLIST_SOLO_TRACK, params={"track": track, "state": solo},
            build_restore=lambda before: {"command": protocol.CMD_PLAYLIST_SOLO_TRACK,
                                           "params": {"track": track, "state": before["solo"]}})

    @mcp.tool(annotations={"title": "Rename a playlist track", **_WR})
    def fl_playlist_rename_track(
        track: Annotated[int, Field(ge=1, description="1-based playlist track.")],
        name: Annotated[str, Field(description="New track name.")],
    ) -> dict:
        """Rename a playlist track (reversible)."""
        b = get_bridge()
        return safety.safe_write(
            b, tool="playlist_rename_track", scope="playlist_track:%d" % track,
            command=protocol.CMD_PLAYLIST_SET_NAME, params={"track": track, "name": name},
            build_restore=lambda before: {"command": protocol.CMD_PLAYLIST_SET_NAME,
                                           "params": {"track": track, "name": before["name"]}})

    @mcp.tool(annotations={"title": "Color a playlist track", **_WR})
    def fl_playlist_set_track_color(
        track: Annotated[int, Field(ge=1, description="1-based playlist track.")],
        color: Annotated[str, Field(description="Color name (red, blue, ...) or hex '#33A1FF'.")],
    ) -> dict:
        """Set a playlist track's color by name or hex (reversible)."""
        rgb = parse_color(color)
        if rgb is None:
            return {"ok": False, "error": "unknown color %r" % color}
        r, g, bl = rgb
        cint = (r << 16) | (g << 8) | bl
        b = get_bridge()
        return safety.safe_write(
            b, tool="playlist_set_track_color", scope="playlist_track:%d" % track,
            command=protocol.CMD_PLAYLIST_SET_COLOR, params={"track": track, "color": cint},
            build_restore=lambda before: {"command": protocol.CMD_PLAYLIST_SET_COLOR,
                                           "params": {"track": track, "color": before["color"]}})

    @mcp.tool(annotations={"title": "Get arrangement selection", **_RO})
    def fl_arrangement_selection() -> dict:
        """Read the arrangement timeline selection (start/end/active) + current
        playhead time. Read-only (FL can't author playlist clips via scripting)."""
        return get_bridge().call(protocol.CMD_ARRANGE_GET_SELECTION)

    @mcp.tool(annotations={"title": "List arrangement markers", **_RO})
    def fl_arrangement_markers() -> dict:
        """List named timeline markers (intro/verse/drop/...), best-effort + capped."""
        return get_bridge().call(protocol.CMD_ARRANGE_GET_MARKERS)
