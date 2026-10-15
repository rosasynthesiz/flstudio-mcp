"""Drums to MIDI: a drum loop or stem to a .mid and, optionally, straight into
the step sequencer of the channels you name (one undo step).
"""
from __future__ import annotations

import os
import time
from typing import Annotated, Dict, Optional

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import get_bridge
from .export import _EXPORT_DIR

KINDS = ("kick", "snare", "clap", "closed hat", "open hat")


def drum_report(path, bpm=None, bars=1, start_bar=0, midi_out=None):
    """Detect hits and summarize them; PURE apart from reading audio/writing midi_out."""
    from ..music import drums
    from ..music.midi_export import write_midi

    bpm = float(bpm) if bpm else drums.estimate_tempo(path)
    notes = drums.drum_notes(path, bpm)
    steps = drums.to_steps(notes, bars=bars, start_bar=start_bar)
    length = bars * 16
    out = {"path": str(path), "bpm_used": round(bpm, 1), "hits": len(notes),
           "counts": drums.summary(notes), "bars": bars, "start_bar": start_bar,
           "steps": steps,
           "preview": {k: "".join("x" if i in v else "." for i in range(length))
                       for k, v in steps.items()},
           "quality": ("Hits are sorted by sound only (kick, snare, clap, closed and open "
                       "hat); toms, cymbals and layered sounds get the closest of those. "
                       "An open hat needs ~150 ms before the next hit to be told apart.")}
    if midi_out:
        write_midi([{"name": "Drums", "channel": 9,
                     "notes": [{"pitch": n["pitch"], "start_bars": n["time_bars"],
                                "length_bars": n["length_bars"], "velocity": n["velocity"]}
                               for n in notes]}], bpm, midi_out)
        out["midi_file"] = str(midi_out)
    return out


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={"title": "Drums to MIDI / step sequencer",
                           "readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": False, "openWorldHint": True})
    def fl_extract_drums(
        path: Annotated[str, Field(description="Drum loop or drum stem (WAV/FLAC; MP3 needs ffmpeg).")],
        bpm: Annotated[Optional[float], Field(description="Tempo; auto-detected if omitted.")] = None,
        to_channels: Annotated[Optional[Dict[str, int]], Field(description="Write into the step sequencer: kind -> channel, e.g. {'kick': 0, 'snare': 1, 'closed hat': 2}. Kinds: kick, snare, clap, closed hat, open hat.")] = None,
        bars: Annotated[int, Field(ge=1, le=16, description="How many bars to preview / write (16 steps each).")] = 1,
        start_bar: Annotated[int, Field(ge=0, description="First bar of the audio to use (0 = start).")] = 0,
    ) -> dict:
        """Detect the hits in a drum loop or stem and sort them into kick,
        snare, clap, closed and open hi-hat. Always writes a .mid to
        ~/.flstudio-mcp/exports and returns per-kind step patterns. With
        to_channels, also writes those steps into the CURRENT pattern of the
        given channels (one undo step: fl_rollback_last_change)."""
        if not os.path.isfile(path):
            return {"ok": False, "error": "file not found: %s" % path}
        from ..music import drums as drum_lib
        if not drum_lib.available():
            return {"ok": False, "error": "drums to MIDI is not installed: re-run the "
                    "installer and answer yes to audio to MIDI"}
        bad = sorted(set(to_channels or {}) - set(KINDS))
        if bad:
            return {"ok": False, "error": "unknown kinds %s; use %s" % (bad, ", ".join(KINDS))}
        os.makedirs(_EXPORT_DIR, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        midi = os.path.join(_EXPORT_DIR, "%s_drums_%d.mid" % (base, int(time.time())))
        try:
            report = drum_report(path, bpm, bars, start_bar, midi)
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        if not to_channels:
            return {"ok": True, **report}

        length = bars * 16
        writes = []
        for kind, channel in to_channels.items():
            steps = report["steps"].get(kind, [])
            writes.append({"snap_scope": "grid:%d:%d" % (channel, length),
                           "command": protocol.CMD_CHANNEL_SET_GRID,
                           "params": {"channel": channel, "steps": steps, "length": length},
                           "restore": lambda b, channel=channel: {
                               "command": protocol.CMD_CHANNEL_SET_GRID,
                               "params": {"channel": channel, "length": length,
                                          "steps": b.get("steps", [])}}})
        try:
            res = safety.safe_write_group(get_bridge(), tool="extract_drums",
                                          scope="grid:drums", writes=writes)
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), **report}
        written = {k: a.get("steps") for k, a in zip(to_channels, res.get("after", []),
                                                         strict=False)}
        wrong = [k for k in to_channels if written.get(k) != report["steps"].get(k, [])]
        return {"ok": not wrong, **report, "written": written, "not_written": wrong,
                "undo": "fl_rollback_last_change restores the old steps of every channel"}
