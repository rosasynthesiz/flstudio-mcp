#!/usr/bin/env python3
"""Offline test: chord naming and the per-bar progression of fl_extract_chords.
Pure logic; needs neither Basic Pitch nor FL.

    python scripts/test_chord_progression.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp.tools.audio import _bar_progression, _chord_name  # noqa: E402

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def chords(progression):
    return [(p["bar"], p["chord"]) for p in progression]


def main() -> int:
    check("chord names", [_chord_name(c) for c in ([0, 4, 7], [9, 0, 4], [4, 7, 11, 2])]
          == ["C", "Am", "Em7"])
    check("unknown shape gives None", _chord_name([0, 1, 2]) is None)

    # C4/E4/G4 held 8 s at 120 BPM (2 s bars) = four bars of C.
    held = _bar_progression([(0, 8, p, 0.8) for p in (60, 64, 67)], barlen=2)
    check("sustained chord shows in all 4 bars", chords(held) == [(b, "C") for b in (1, 2, 3, 4)],
          str(chords(held)))

    # A held chord that starts mid-bar and ends mid-bar touches 3 bars.
    mid = _bar_progression([(1, 5, p, 0.8) for p in (57, 60, 64)], barlen=2)
    check("held chord counts in partial bars", chords(mid) == [(1, "Am"), (2, "Am"), (3, "Am")],
          str(chords(mid)))

    # Change of chord: one bar of C, then one bar of F.
    change = _bar_progression([(0, 2, p, 0.8) for p in (60, 64, 67)] +
                              [(2, 4, p, 0.8) for p in (65, 69, 72)], barlen=2)
    check("chord change per bar", chords(change) == [(1, "C"), (2, "F")], str(chords(change)))

    # A note ending exactly on a bar line must not leak into the next bar.
    edge = _bar_progression([(0, 2, p, 0.8) for p in (60, 64, 67)], barlen=2)
    check("note ending on the bar line stays in its bar", chords(edge) == [(1, "C")],
          str(chords(edge)))

    # In a bar, the chord held longest sets the root over a short passing chord
    # (its strongest extra note may still add a 7th: G + F = G7).
    weighted = _bar_progression([(0, 1.8, p, 0.8) for p in (67, 71, 74)] +
                                [(1.8, 2, p, 0.8) for p in (65, 69, 72)], barlen=2)
    check("longest chord in the bar sets the root", chords(weighted)[0][1].startswith("G"),
          str(chords(weighted)))

    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
