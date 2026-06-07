#!/usr/bin/env python3
"""Test MCP resources: each returns valid data, fast, within size limits.

Builds the real server and reads each fl:// resource in-process (same path
an MCP client uses). Prints byte size per resource -- the big lists (mixer/channels)
must stay small.

    set FLSTUDIO_MCP_TRANSPORT=tcp
    python scripts/test_resources.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp.server import build_server  # noqa: E402

URIS = [
    "fl://agent-briefing",
    "fl://status",
    "fl://project",
    "fl://transport",
    "fl://channels",
    "fl://mixer",
    "fl://patterns",
]


def _text(r):
    """Pull text out of whatever read_resource returns across FastMCP versions."""
    if isinstance(r, (list, tuple)) and r:
        r = r[0]
    for attr in ("text", "content", "data"):
        v = getattr(r, attr, None)
        if isinstance(v, str):
            return v
        if v is not None:
            return str(v)
    return str(r)


def main() -> int:
    m = build_server()
    try:
        res = asyncio.run(m._list_resources())
        print("registered resources:", sorted(str(r.uri) for r in res))
    except Exception as e:
        print(f"(_list_resources unavailable: {e})")

    big_ok = True
    for uri in URIS:
        try:
            txt = _text(asyncio.run(m.read_resource(uri)))
            size = len(txt)
            flag = ""
            if uri == "fl://agent-briefing" and size > 5000:
                flag = "  <-- LARGE (>5KB)"
                big_ok = False
            if uri in ("fl://mixer", "fl://channels", "fl://patterns") and size > 4000:
                flag = "  <-- LARGE (>4KB)"
                big_ok = False
            print("\n=== %s === (%d bytes)%s" % (uri, size, flag))
            print(txt[:700])
        except Exception as e:
            print(f"\n=== {uri} === ERROR: {type(e).__name__}: {e}")
            big_ok = False

    print("\nbig lists within size limits:", big_ok)
    return 0 if big_ok else 1


if __name__ == "__main__":
    sys.exit(main())
