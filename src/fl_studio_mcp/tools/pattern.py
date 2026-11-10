"""Pattern tools (E-2): list / select / rename / get length.

FL patterns are 1-based indexes; select/rename go through safe_write with a
`pattern:N` snapshot so both are single rollback steps. FL's API cannot
DELETE a pattern, so a rename rollback restores the old name -- and a created
pattern has to be cleaned up by hand (rename it to a TMP_ marker).
"""
from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge


def _restore_select(before):
    """Rollback for select = jump back to the pattern that WAS selected."""
    if not before.get("ok") or "current" not in before:
        raise ValueError("pattern select: no usable snapshot to restore from"
                         + (f": {before['error']}" if before.get("error") else ""))
    return {"command": protocol.CMD_PATTERN_SELECT,
            "params": {"index": before["current"]}}


def _restore_rename(index):
    """Rollback for rename = put the snapshotted old name back."""
    def build(before):
        if not before.get("ok") or "name" not in before:
            raise ValueError("pattern rename: no usable snapshot to restore from"
                             + (f": {before['error']}" if before.get("error") else ""))
        return {"command": protocol.CMD_PATTERN_RENAME,
                "params": {"index": index, "name": before["name"]}}
    return build


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "List patterns", **_RO})
    def fl_pattern_list(
        start: Annotated[int, Field(ge=0, description="Page start (0-based).")] = 0,
        limit: Annotated[int | None,
                         Field(gt=0, description="Max items; omit for ALL pages.")] = None,
    ) -> dict:
        """List patterns: {total, patterns:[{pattern (1-based), name}]}.
        Paginated (600-byte pages); omit limit to walk every page."""
        bridge = get_bridge()
        if limit is None:
            return fetch_all_pages(bridge, protocol.CMD_PATTERN_LIST,
                                   "patterns", {"start": start})
        out, cur = [], start
        total = None
        while len(out) < limit:
            page = bridge.call(protocol.CMD_PATTERN_LIST, {"start": cur})
            total = page.get("total", total)
            chunk = page.get("patterns") or []
            out.extend(chunk[: limit - len(out)])
            nxt = page.get("next_start")
            if nxt is None or int(nxt) <= cur or not chunk:
                break
            cur = int(nxt)
        return {"total": total, "start": start, "patterns": out}

    @mcp.tool(annotations={"title": "Select a pattern", **_WR})
    def fl_pattern_select(
        index: Annotated[int, Field(ge=1, description="1-based pattern index.")],
    ) -> dict:
        """Make a pattern the current one (index must exist -- FL silently
        clamps out-of-range jumps, so we reject them). One rollback step:
        restores the previously selected pattern. Reports prev_index /
        prev_name."""
        bridge = get_bridge()
        result = safety.safe_write(
            bridge, tool="pattern_select", scope=f"pattern:{index}",
            command=protocol.CMD_PATTERN_SELECT, params={"index": index},
            build_restore=_restore_select)
        # The controller reply carries the previous selection, but safe_write
        # exposes only before/after; surface prev_index/prev_name from the
        # snapshot (and the controller's own echo is lost by design).
        if isinstance(result, dict):
            prev = (result.get("before") or {}).get("current")
            if isinstance(prev, int):
                meta = bridge.call(protocol.CMD_PATTERN_GET_LENGTH,
                                   {"index": prev})
                if meta.get("ok"):
                    result["prev_index"] = prev
                    result["prev_name"] = meta.get("name")
            result["resolved_index"] = (result.get("after") or {}).get("current")
        return result

    @mcp.tool(annotations={"title": "Rename a pattern", **_WR})
    def fl_pattern_rename(
        index: Annotated[int, Field(ge=1, description="1-based pattern index.")],
        name: Annotated[str, Field(description="New pattern name.")],
    ) -> dict:
        """Rename a pattern. One rollback step: restores the old name."""
        return safety.safe_write(
            get_bridge(), tool="pattern_rename", scope=f"pattern:{index}",
            command=protocol.CMD_PATTERN_RENAME,
            params={"index": index, "name": name},
            build_restore=_restore_rename(index))

    @mcp.tool(annotations={"title": "Get pattern length", **_RO})
    def fl_pattern_get_length(
        index: Annotated[int, Field(ge=1, description="1-based pattern index.")],
    ) -> dict:
        """Pattern length in BEATS (FL's native unit) + derived ticks and bars
        (via RecPPQ / RecPPB), plus its name and current selection state."""
        return get_bridge().call(protocol.CMD_PATTERN_GET_LENGTH, {"index": index})
