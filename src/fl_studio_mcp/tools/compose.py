"""Raga / scale composer -- write Claude-generated notes via the note bridge.

NO theory engine: CLAUDE knows the ragas (Hamsadhwani, Charukesi, Mohanam,
Kalyani, ...) and supplies the notes; these tools just SELECT the target channel
and WRITE the notes through the existing (hardened) piano-roll bridge. raga/root
are echoed for labelling only.

Setup (same as the note bridge): Piano roll open + 'MCP_Apply' armed once per
session. Writes into the SELECTED pattern + channel.
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import protocol, safety
from ..connection import get_bridge


class RagaNote(BaseModel):
    pitch: int = Field(ge=0, le=127, description="MIDI note (60 = middle C / FL C5).")
    time_bars: float = Field(0.0, ge=0.0, description="Start in bars from pattern start.")
    length_bars: float = Field(0.25, gt=0.0, description="Duration in bars.")
    velocity: float = Field(0.787, ge=0.0, le=1.0, description="0..1 (0.787 ~= MIDI vel 100).")


def _write(notes, channel, mode):
    preview = safety.preview_write(tool="write_raga_notes", params={
        "notes": [n.model_dump() for n in notes], "channel": channel, "mode": mode,
    })
    if preview is not None:
        return preview
    bridge = get_bridge()
    sel = None
    if channel is not None:
        sel = bridge.call(protocol.CMD_CHANNEL_SELECT, {"channel": channel})
    res = bridge.apply_notes([n.model_dump() for n in notes], mode)
    if isinstance(res, dict) and sel is not None:
        res["channel_selected"] = sel
    return res


def register(mcp: FastMCP) -> None:
    _WR = {"readOnlyHint": False, "destructiveHint": True,
           "idempotentHint": False, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Write a raga/scale MELODY", **_WR})
    def fl_write_raga_melody(
        notes: List[RagaNote],
        raga: Annotated[Optional[str], Field(description="Raga/scale name (label only), e.g. 'Hamsadhwani'.")] = None,
        root: Annotated[Optional[str], Field(description="Root/tonic (label only), e.g. 'C', 'D#'.")] = None,
        channel: Annotated[Optional[int], Field(ge=0, description="Channel-rack channel to write into (selected first).")] = None,
        mode: Annotated[str, Field(description="'replace' clears the pattern first; 'append' adds.")] = "replace",
    ) -> dict:
        """Write a MELODY (single-line, sequential notes) into the selected channel
        via the piano-roll bridge. YOU (Claude) generate the swaras for the named
        raga/root -> MIDI notes (use the proper aarohana/avarohana; respect the
        raga's allowed swaras); this tool only selects the channel + writes. SHOW
        the user the notes/swaras BEFORE calling. Needs the Piano roll open +
        MCP_Apply armed once this session (see the note-bridge setup)."""
        result = _write(notes, channel, mode)
        if result.get("dry_run"):
            result["planned"].update(raga=raga, root=root)
            return result
        return {"ok": True, "wrote": len(notes), "raga": raga, "root": root,
                "channel": channel, "bridge": result}

    @mcp.tool(annotations={"title": "Write raga/scale CHORDS", **_WR})
    def fl_write_raga_chords(
        notes: List[RagaNote],
        raga: Annotated[Optional[str], Field(description="Raga/scale name (label only).")] = None,
        root: Annotated[Optional[str], Field(description="Root/tonic (label only).")] = None,
        channel: Annotated[Optional[int], Field(ge=0, description="Channel-rack channel to write into (selected first).")] = None,
        mode: Annotated[str, Field(description="'replace' clears the pattern first; 'append' adds.")] = "replace",
    ) -> dict:
        """Write CHORDS / a progression (stacked notes sharing start times) into
        the selected channel via the bridge. YOU stack chord tones drawn from the
        raga/scale (give simultaneous notes the SAME time_bars). Tool selects the
        channel + writes. SHOW the user the chords BEFORE calling."""
        result = _write(notes, channel, mode)
        if result.get("dry_run"):
            result["planned"].update(raga=raga, root=root)
            return result
        return {"ok": True, "wrote": len(notes), "raga": raga, "root": root,
                "channel": channel, "bridge": result}
