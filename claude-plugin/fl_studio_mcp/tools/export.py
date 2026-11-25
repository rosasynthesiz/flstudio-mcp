"""Export an arrangement to a Standard MIDI File on disk.

Claude builds the full multi-section / multi-instrument arrangement; this writes
ONE type-1 .mid the user imports into FL -- bypassing the note-bridge's
one-pattern + MCP_Apply-arm limits for big arrangements. Does NOT touch FL.
"""
from __future__ import annotations

import os
import time
from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..music.midi_export import write_midi

_EXPORT_DIR = os.path.join(os.path.expanduser("~"), ".flstudio-mcp", "exports")


class ExportNote(BaseModel):
    pitch: int = Field(ge=0, le=127, description="MIDI note (60 = middle C).")
    start_bars: float = Field(ge=0.0, description="Start in bars from song start.")
    length_bars: float = Field(gt=0.0, description="Duration in bars.")
    velocity: float = Field(0.787, description="0..1 (0.787~=vel 100) or a raw 1..127 int.")


class ExportTrack(BaseModel):
    name: str = Field(description="Track name, e.g. 'Drums', 'Bass', 'Lead'.")
    channel: int = Field(0, ge=0, le=15, description="MIDI channel 0-15 (9 = GM drums, by convention).")
    notes: List[ExportNote]


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={"title": "Export arrangement to .mid", "readOnlyHint": False,
                           "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
    def fl_export_midi(
        tracks: List[ExportTrack],
        bpm: Annotated[float, Field(gt=0, description="Tempo (BPM).")] = 120.0,
        output_path: Annotated[Optional[str], Field(description="Output .mid path; defaults to ~/.flstudio-mcp/exports/.")] = None,
        beats_per_bar: Annotated[int, Field(ge=1, le=16, description="Time-signature numerator (4 = 4/4).")] = 4,
    ) -> dict:
        """Write a type-1 multi-track .mid from an arrangement spec. YOU (Claude)
        generate the whole arrangement -- multiple named tracks, each with notes
        {pitch, start_bars, length_bars, velocity} across all sections -- and this
        writes ONE .mid. Bypasses the note-bridge's one-pattern + MCP_Apply limits.

        Does NOT touch FL: IMPORT the file yourself (FL: File > Import > MIDI file,
        or drag it into the playlist). FL won't auto-load instruments -- assign a
        channel to each imported track. Returns the saved file path."""
        if not tracks:
            return {"ok": False, "error": "no tracks given"}
        path = output_path or os.path.join(_EXPORT_DIR, "arrangement_%d.mid" % int(time.time()))
        try:
            specs = [t.model_dump() for t in tracks]
            write_midi(specs, float(bpm), path, beats_per_bar=int(beats_per_bar))
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        return {"ok": True, "path": path, "size_bytes": os.path.getsize(path),
                "format": "SMF type 1", "bpm": bpm, "beats_per_bar": beats_per_bar,
                "track_count": len(tracks), "track_names": [t.name for t in tracks],
                "note_count": sum(len(t.notes) for t in tracks),
                "import": ("Import into FL: File > Import > MIDI file (or drag the .mid into the "
                           "playlist). Instruments are NOT auto-loaded -- assign each track to a "
                           "channel after import.")}
