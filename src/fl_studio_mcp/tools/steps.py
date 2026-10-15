"""Step sequencer: read and write a channel's steps in the current pattern
(drum patterns without the piano roll). Writes go through the safety layer.
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import get_bridge


def parse_steps(steps=None, pattern=None, length=16):
    """Steps as a list of indexes, or a pattern string ('x' or '1' = on,
    anything else = off, spaces and '|' ignored). Returns (sorted steps, length)."""
    if pattern:
        cells = [ch for ch in pattern if ch not in " |"]
        on = [i for i, ch in enumerate(cells) if ch.lower() in ("x", "1")]
        length = max(length, len(cells))
    else:
        on = sorted(set(int(s) for s in (steps or [])))
    bad = [s for s in on if not 0 <= s < length]
    if bad:
        raise ValueError("steps outside 0..%d: %s" % (length - 1, bad))
    return on, length


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Read step sequencer", **_RO})
    def fl_get_step_grid(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        length: Annotated[int, Field(ge=1, le=256, description="Steps to read (16 = one bar of 1/16).")] = 16,
    ) -> dict:
        """Which step-sequencer steps are on for a channel in the CURRENT
        pattern, plus a pattern string ('x' on, '.' off)."""
        r = get_bridge().call(protocol.CMD_CHANNEL_GET_GRID, {"channel": channel, "length": length})
        r["pattern_string"] = "".join("x" if i in r.get("steps", []) else "." for i in range(length))
        return r

    @mcp.tool(annotations={"title": "Write step sequencer (drum pattern)",
                           "readOnlyHint": False, "destructiveHint": False,
                           "idempotentHint": True, "openWorldHint": True})
    def fl_set_step_grid(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        pattern: Annotated[Optional[str], Field(description="Steps as text, e.g. 'x...x...x...x...' (four on the floor); 'x' or '1' = on.")] = None,
        steps: Annotated[Optional[List[int]], Field(description="Or: step indexes that are on (0 = first 1/16).")] = None,
        length: Annotated[int, Field(ge=1, le=256, description="Steps to write; all others in range are turned off.")] = 16,
    ) -> dict:
        """Set a channel's step-sequencer steps in the CURRENT pattern: exactly
        the given steps on, the rest of 0..length-1 off. Snapshot, read back,
        undo with fl_rollback_last_change."""
        try:
            on, length = parse_steps(steps, pattern, length)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        params = {"channel": channel, "steps": on, "length": length}
        return safety.safe_write(
            get_bridge(), tool="channel_set_grid", scope="grid:%d:%d" % (channel, length),
            command=protocol.CMD_CHANNEL_SET_GRID, params=params, verify=("steps", on),
            build_restore=lambda b: {"command": protocol.CMD_CHANNEL_SET_GRID,
                                     "params": {"channel": channel, "length": length,
                                                "steps": b.get("steps", [])}})
