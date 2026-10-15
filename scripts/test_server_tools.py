#!/usr/bin/env python3
"""Offline test: the server builds and registers every tool (no FL needed).

    python scripts/test_server_tools.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp.server import build_server  # noqa: E402

EXPECTED_TOOLS = 68
MUST_HAVE = ["fl_ping", "fl_get_project_state", "fl_write_piano_roll_notes",
             "fl_diagnose_mix", "fl_extract_melody", "fl_extract_chords",
             "fl_export_midi", "fl_rollback_last_change"]

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def main() -> int:
    tools = asyncio.run(build_server().list_tools())
    names = sorted(t.name for t in tools)
    check("tool count", len(names) == EXPECTED_TOOLS,
          "%d registered, expected %d" % (len(names), EXPECTED_TOOLS))
    check("tool names unique", len(names) == len(set(names)))
    for name in MUST_HAVE:
        check("has %s" % name, name in names)
    check("every tool has a description",
          all((t.description or "").strip() for t in tools),
          ", ".join(t.name for t in tools if not (t.description or "").strip()))
    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
