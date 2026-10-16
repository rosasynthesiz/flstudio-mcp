#!/usr/bin/env python3
"""Offline test: optional per-note porta in render_apply_script.

Runs the generated .pyscript against a stub flpianoroll module, so no FL needed.

    python scripts/test_porta.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp.pyscript_gen import render_apply_script  # noqa: E402

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def run_in_stub(src):
    """Exec a generated script against a fake flpianoroll; return added notes."""
    added = []

    class Note:
        porta = False

    class Score:
        PPQ = 96

        def clearNotes(self, *a):
            added.clear()

        def addNote(self, n):
            added.append(n)

    sys.modules["flpianoroll"] = types.SimpleNamespace(Note=Note, score=Score())
    try:
        exec(compile(src, "MCP_Apply.pyscript", "exec"), {"__name__": "__main__"})
    finally:
        del sys.modules["flpianoroll"]
    return added


def main() -> int:
    plain = [
        {"pitch": 36, "time_bars": 0.0, "length_bars": 0.5, "velocity": 0.8},
        {"pitch": 43, "time_bars": 0.5, "length_bars": 0.5, "velocity": 0.8},
    ]
    s_plain = render_apply_script(plain)
    check("no porta -> 4-tuples, as before",
          "NOTES = [(36, 0.0, 0.5, 0.8), (43, 0.5, 0.5, 0.8)]" in s_plain)

    # porta=False (the PianoRollNote default after model_dump) renders identically
    s_false = render_apply_script([dict(n, porta=False) for n in plain])
    check("porta=False renders identically", s_false == s_plain)

    glide = [plain[0], dict(plain[1], porta=True)]
    notes = run_in_stub(render_apply_script(glide))
    check("script adds both notes", len(notes) == 2, str(len(notes)))
    check("porta set only on the gliding note",
          notes[0].porta is False and notes[1].porta is True)
    check("timing/pitch unaffected by porta",
          notes[1].number == 43 and notes[1].time == 192 and notes[1].length == 192,
          "%s %s %s" % (notes[1].number, notes[1].time, notes[1].length))

    print("\n%d passed, %d failed" % (_P, _F))
    return 0 if _F == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
