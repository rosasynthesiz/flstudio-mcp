#!/usr/bin/env python3
"""Offline test: fl_extract_chords (Basic Pitch) on a synthetic C-Am-F-G file.
Needs the audio to MIDI option (audio-chords extra + basic-pitch --no-deps).

    python scripts/test_chords_extract.py
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from fl_studio_mcp.tools import audio  # noqa: E402

SR = 22050
CHORDS = [(60, 64, 67), (57, 60, 64), (65, 69, 72), (67, 71, 74)]   # C, Am, F, G

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def chord_wav():
    t = np.arange(SR) / SR                                           # 1 s per chord
    parts = [sum(np.sin(2 * np.pi * 440 * 2 ** ((m - 69) / 12) * t) * np.exp(-2 * t)
                 for m in c) / len(c) for c in CHORDS]
    return 0.6 * np.concatenate(parts)


def main() -> int:
    check("chord names", [audio._chord_name(c) for c in ([0, 4, 7], [9, 0, 4], [4, 7, 11, 2])]
          == ["C", "Am", "Em7"])
    check("unknown shape gives None", audio._chord_name([0, 1, 2]) is None)

    if not audio.chords_available():
        print("  [FAIL] Basic Pitch not installed (audio-chords extra + basic-pitch --no-deps)")
        return 1

    d = Path(tempfile.mkdtemp(prefix="flmcp_chords_"))
    wav, mid = d / "chords.wav", d / "chords.mid"
    sf.write(str(wav), chord_wav(), SR)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r = audio.audio_extract_chords(str(wav), bpm=120.0, midi_out=str(mid), include_notes=True)
    check("nothing printed to stdout (MCP channel)", out.getvalue() == "", repr(out.getvalue()[:80]))

    onsets = {}
    for n in r["notes"]:
        onsets.setdefault(round(n["start_sec"]), set()).add(n["midi"])
    for i, c in enumerate(CHORDS):
        check("chord %d is %s" % (i + 1, c), onsets.get(i) == set(c), str(sorted(onsets.get(i, []))))
    check("bridge_notes match notes", len(r["bridge_notes"]) == len(r["notes"]))
    check("progression returned", bool(r["progression"]))
    check(".mid written", mid.is_file() and mid.stat().st_size > 0)

    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
