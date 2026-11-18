#!/usr/bin/env python3
"""Test MCP resources: each returns valid data, fast, within size limits.

Builds the real server and reads each fl:// resource in-process (same path
Claude uses). Prints byte size per resource -- the big lists (mixer/channels)
must stay small.

    set FLSTUDIO_MCP_TRANSPORT=tcp
    python scripts/test_resources.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp.server import build_server             # noqa: E402
from fastmcp import Client                               # noqa: E402

URIS = ["fl://status", "fl://project", "fl://transport",
        "fl://channels", "fl://mixer", "fl://patterns"]


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


async def check_resources(client) -> int:
    res = await client.list_resources()
    print("registered resources:", sorted(str(r.uri) for r in res))

    big_ok = True
    for uri in URIS:
        try:
            txt = _text(await client.read_resource(uri))
            size = len(txt)
            flag = ""
            if uri in ("fl://mixer", "fl://channels", "fl://patterns") and size > 4000:
                flag = "  <-- LARGE (>4KB)"
                big_ok = False
            print("\n=== %s === (%d bytes)%s" % (uri, size, flag))
            print(txt[:700])
        except Exception as e:
            print("\n=== %s === ERROR: %s: %s" % (uri, type(e).__name__, e))
            big_ok = False

    print("\nbig lists within size limits:", big_ok)
    return 0 if big_ok else 1


async def main():
    async with Client(build_server()) as client:
        return await check_resources(client)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
