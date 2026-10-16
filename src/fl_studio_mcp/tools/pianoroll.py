"""Phase 2 MCP tool -- author notes into FL's piano roll.

Uses the generate-script bridge (pyscript can't read/write files, so the
daemon generates a .pyscript with the notes baked in, then force-focuses FL
and fires the platform run-last-script shortcut). Requires the FL Piano roll
open, and a one-time setup: run 'MCP_Apply' once from the piano-roll Scripting
menu so that 'Run last script again' targets it.
"""

from __future__ import annotations

from typing import Annotated, List

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..connection import get_bridge
from ..pyscript_gen import quantize_notes


class PianoRollNote(BaseModel):
    pitch: int = Field(ge=0, le=127,
                       description="MIDI note (60 = middle C; FL displays it as C5).")
    time_bars: float = Field(0.0, ge=0.0,
                             description="Start, in bars from the pattern start.")
    length_bars: float = Field(1.0, gt=0.0, description="Duration in bars.")
    velocity: float = Field(100 / 127.0, ge=0.0, le=1.0,
                            description="0.0-1.0 (0.787 ~= MIDI velocity 100).")
    porta: bool = Field(False,
                        description="Portamento: slide into this note from the previous one (808 glides).")


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={
        "title": "Write piano-roll notes",
        "readOnlyHint": False,
        "destructiveHint": True,   # mode='replace' clears existing notes
        "idempotentHint": False,
        "openWorldHint": True,
    })
    def fl_write_piano_roll_notes(
        notes: List[PianoRollNote],
        mode: Annotated[str, Field(
            description="'replace' clears the pattern first; 'append' adds to it.",
        )] = "replace",
        quantize: Annotated[float, Field(
            description="Optional grid (bars) to snap note starts to before writing: 0.0625=1/16, 0.125=1/8, 0=off.",
        )] = 0.0,
    ) -> dict:
        """Write notes into the currently-open FL Piano roll.

        Each note: {pitch (MIDI), time_bars, length_bars, velocity 0-1,
        porta (optional, slide into the note)}. Set
        quantize (grid in bars) to snap note starts to a grid before writing.
        Setup: open the Piano roll and run 'MCP_Apply' once from its Scripting
        menu (so Run last script again targets it). mode='replace' clears first.
        """
        arr = [n.model_dump() for n in notes]
        if quantize and quantize > 0:
            arr = quantize_notes(arr, float(quantize))
        return get_bridge().apply_notes(arr, mode)

    @mcp.tool(annotations={
        "title": "Quantize piano-roll notes",
        "readOnlyHint": False, "destructiveHint": False,
        "idempotentHint": False, "openWorldHint": True,
    })
    def fl_quantize_pattern(
        grid_bars: Annotated[float, Field(gt=0, description="Snap grid in bars: 0.0625=1/16, 0.125=1/8, 0.25=1/4.")] = 0.0625,
        snap_ends: Annotated[bool, Field(description="Also snap note lengths to the grid.")] = False,
    ) -> dict:
        """Quantize the notes ALREADY in the open Piano roll: reads the score,
        snaps note starts (and optionally lengths) to the grid, rewrites -- via
        the pyscript bridge, no dialog. Needs the Piano roll open + MCP_Apply
        armed once this session (same setup as note writing)."""
        return get_bridge().apply_notes([], trigger=True, quantize=float(grid_bars), snap_ends=snap_ends)
