"""API probe tool (E-5): agent handle on FL's scripting-module introspection.

Wraps the controller's api_probe op=dir (budget-paginated names of one FL
module) so future spikes don't need controller edits. Optional `pattern`
walks all pages and filters case-insensitively; the filtered reply is
trimmed to the payload budget with a `truncated` flag + full `match_count`.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol
from ..connection import get_bridge

_LIST_BUDGET = 600
_MAX_PAGES = 50

_Module = Literal["playlist", "arrangement", "patterns", "general",
                  "transport", "ui", "midi", "mixer", "channels", "plugins"]


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Probe FL scripting API (names)", **_RO})
    def fl_api_probe(
        module: Annotated[_Module, Field(description="FL scripting module.")],
        pattern: Annotated[str | None,
                           Field(description="Case-insensitive substring "
                                             "filter; walks all pages.")] = None,
        start: Annotated[int, Field(ge=0, description="Page start (no filter).")] = 0,
    ) -> dict:
        """Public names of one FL scripting module (dir(module), names only,
        budget-paginated). Without pattern: one page {module, total, start,
        next_start, names}. With pattern: all pages walked, matches filtered,
        reply carries {match_count, names, truncated}."""
        bridge = get_bridge()
        if pattern is None:
            return bridge.call(protocol.CMD_API_PROBE,
                               {"op": "dir", "module": module, "start": start})
        names: list[str] = []
        cur, total, pages = start, None, 0
        while pages < _MAX_PAGES:
            page = bridge.call(protocol.CMD_API_PROBE,
                               {"op": "dir", "module": module, "start": cur})
            total = page.get("total", total)
            names.extend(page.get("names") or [])
            nxt = page.get("next_start")
            pages += 1
            if nxt is None or int(nxt) <= cur:
                break
            cur = int(nxt)
        needle = pattern.lower()
        hits = [n for n in names if needle in n.lower()]
        out: list[str] = []
        for n in hits:
            trial = out + [n]
            env = {"module": module, "pattern": pattern, "total": total,
                   "start": start, "match_count": len(hits), "names": trial,
                   "truncated": True}
            # Budget the FULL envelope, not just the names list: a 600-byte
            # names array still shipped 675 B with the wrapper.
            if len(json.dumps(env, separators=(",", ":"))) > _LIST_BUDGET and out:
                break
            out.append(n)
        return {"module": module, "pattern": pattern, "total": total,
                "start": start, "match_count": len(hits), "names": out,
                "truncated": len(out) < len(hits)}
