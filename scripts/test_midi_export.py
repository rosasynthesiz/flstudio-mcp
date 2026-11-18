#!/usr/bin/env python3
"""Test MIDI export: build a 3-track (drums/bass/lead) arrangement -> .mid,
read it back with mido + assert it's a valid type-1 multi-track file. Uses a
disposable temporary file; never writes into user export folders (no FL).

    python scripts/test_midi_export.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mido                                              # noqa: E402
from fl_studio_mcp.music.midi_export import write_midi   # noqa: E402

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def main() -> int:
    # 2-bar, 4/4, 120 BPM arrangement.
    def hit(p, b, ln=0.25, v=0.79):
        return {"pitch": p, "start_bars": b, "length_bars": ln, "velocity": v}

    drums = {"name": "Drums", "channel": 9, "notes":
             [hit(36, b, 0.12) for b in (0, 0.5, 1.0, 1.5)]            # kick beats 1&3
             + [hit(38, b, 0.12) for b in (0.25, 0.75, 1.25, 1.75)]   # snare 2&4
             + [hit(42, b / 8.0, 0.06, 0.6) for b in range(16)]}      # hats (8ths)
    bass = {"name": "Bass", "channel": 0, "notes":
            [hit(40, 0.0, 0.5), hit(43, 0.5, 0.5), hit(36, 1.0, 0.5), hit(38, 1.5, 0.5)]}
    lead = {"name": "Lead", "channel": 1, "notes":
            [hit(60, 0.0), hit(64, 0.25), hit(67, 0.5), hit(72, 0.75),
             hit(67, 1.0), hit(64, 1.25), hit(62, 1.5), hit(60, 1.75)]}
    tracks = [drums, bass, lead]
    total_notes = sum(len(t["notes"]) for t in tracks)

    with tempfile.TemporaryDirectory(prefix="flmcp-export-test-") as folder:
        path = os.path.join(folder, "test_arrangement.mid")
        write_midi(tracks, 120.0, path, beats_per_bar=4)
        print("wrote temporary MIDI:", os.path.getsize(path), "bytes")
        mf = mido.MidiFile(path)
    names = [t.name for t in mf.tracks if t.name]
    note_ons = sum(1 for tr in mf.tracks for m in tr if m.type == "note_on" and m.velocity > 0)
    note_offs = sum(1 for tr in mf.tracks for m in tr
                    if m.type == "note_off" or (m.type == "note_on" and m.velocity == 0))
    tempos = [m.tempo for tr in mf.tracks for m in tr if m.type == "set_tempo"]

    check("valid SMF type 1", mf.type == 1, "type=%d" % mf.type)
    check("ppq 480", mf.ticks_per_beat == 480, str(mf.ticks_per_beat))
    check("4 tracks (conductor + 3)", len(mf.tracks) == 4, "got %d" % len(mf.tracks))
    check("track names present", {"Drums", "Bass", "Lead"}.issubset(set(names)), str(names))
    check("note_on count == notes given", note_ons == total_notes, "%d vs %d" % (note_ons, total_notes))
    check("every note has a note_off", note_offs == note_ons, "%d offs / %d ons" % (note_offs, note_ons))
    check("tempo set (~120 BPM)", tempos and abs(mido.tempo2bpm(tempos[0]) - 120.0) < 1.0,
          str([round(mido.tempo2bpm(t), 1) for t in tempos]))

    print("\n%d passed, %d failed" % (_P, _F))
    return 0 if _F == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
