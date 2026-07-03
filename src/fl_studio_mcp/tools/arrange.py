"""Arrangement primitives (Slice 1).

FL's API can't place pattern clips on the playlist (confirmed by probe), so
"arrangement" here = create/name/fill section PATTERNS + mark the timeline with
named markers; the user drags the patterns onto the playlist.

Filling notes reuses the existing piano-roll bridge (fl_write_piano_roll_notes),
which writes into the CURRENTLY SELECTED pattern -- so the flow is
new_pattern (selects it) -> write notes.
"""
from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol
from ..connection import get_bridge


def register(mcp: FastMCP) -> None:
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": False, "openWorldHint": True}

    @mcp.tool(annotations={"title": "New named pattern (selects it)", **_WR})
    def fl_arrange_new_pattern(
        name: Annotated[str, Field(description="Pattern name, e.g. 'INTRO'.")],
    ) -> dict:
        """Create + select + name the next empty pattern. After this, the note
        bridge (fl_write_piano_roll_notes) writes INTO this pattern."""
        return get_bridge().call(protocol.CMD_ARRANGE_NEW_PATTERN, {"name": name})

    @mcp.tool(annotations={"title": "Select channel (note-bridge target)", **_WR})
    def fl_arrange_select_channel(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
    ) -> dict:
        """Make a channel the active selection so the note bridge
        (fl_write_piano_roll_notes) writes INTO it. Use before writing each
        instrument's notes in a section (drums -> ch X, bass -> ch Y, ...)."""
        return get_bridge().call(protocol.CMD_CHANNEL_SELECT, {"channel": channel})

    @mcp.tool(annotations={"title": "Clone a pattern (copies notes)", **_WR})
    def fl_arrange_clone_pattern(
        src: Annotated[int, Field(ge=1, description="Source pattern index.")],
        new_name: Annotated[str, Field(description="Name for the clone.")],
    ) -> dict:
        """Clone a pattern (copies its notes) and rename the clone -- e.g. for
        verse -> verse2 variations."""
        return get_bridge().call(protocol.CMD_ARRANGE_CLONE_PATTERN,
                                 {"src": src, "new_name": new_name})

    @mcp.tool(annotations={"title": "Add a section marker at a bar", **_WR})
    def fl_arrange_add_marker(
        bar: Annotated[int, Field(ge=1, description="Bar number (1 = song start).")],
        name: Annotated[str, Field(description="Marker name, e.g. 'Verse'.")],
    ) -> dict:
        """Add a named timeline marker at a bar (intro/verse/chorus/drop)."""
        return get_bridge().call(protocol.CMD_ARRANGE_ADD_MARKER, {"bar": bar, "name": name})

    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "List patterns", **_RO})
    def fl_pattern_list() -> dict:
        """List all patterns as {pattern (1-based), name}. Paginated internally."""
        from ..connection import fetch_all_pages
        return fetch_all_pages(get_bridge(), protocol.CMD_PATTERN_LIST, "patterns")

    @mcp.tool(annotations={"title": "Select a pattern", **_WR})
    def fl_pattern_select(
        pattern: Annotated[int, Field(ge=1, description="1-based pattern number.")],
    ) -> dict:
        """Select (jump to) a pattern by its 1-based number. The note bridge then
        writes into THIS pattern."""
        return get_bridge().call(protocol.CMD_PATTERN_SELECT, {"pattern": pattern})

    @mcp.tool(annotations={"title": "Rename a pattern", **_WR})
    def fl_pattern_rename(
        pattern: Annotated[int, Field(ge=1, description="1-based pattern number.")],
        name: Annotated[str, Field(description="New pattern name.")],
    ) -> dict:
        """Rename a pattern by its 1-based number."""
        return get_bridge().call(protocol.CMD_PATTERN_RENAME,
                                 {"pattern": pattern, "name": name})

    @mcp.tool(annotations={"title": "Get pattern length", **_RO})
    def fl_pattern_get_length(
        pattern: Annotated[int, Field(ge=1, description="1-based pattern number.")],
    ) -> dict:
        """Return a pattern's length in beats and bars (4/4)."""
        return get_bridge().call(protocol.CMD_PATTERN_GET_LENGTH, {"pattern": pattern})
