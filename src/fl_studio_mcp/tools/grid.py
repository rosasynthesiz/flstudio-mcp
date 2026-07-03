"""Channel step-sequencer grid (Tier 2).

Read/draw a channel's step grid without the piano roll -- ideal for drum
patterns. Single-step writes and grid clear are reversible via the safety layer
using the ``grid_bit`` snapshot scope.
"""
from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import get_bridge


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Get channel step grid", **_RO})
    def fl_channel_get_grid(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        steps: Annotated[int, Field(ge=1, le=256, description="How many steps to read.")] = 16,
    ) -> dict:
        """Read a channel's step-sequencer grid as a list of 0/1 bits."""
        return get_bridge().call(protocol.CMD_CHANNEL_GET_GRID,
                                 {"channel": channel, "steps": steps})

    @mcp.tool(annotations={"title": "Set a channel step", **_WR})
    def fl_channel_set_step(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        index: Annotated[int, Field(ge=0, description="Step index (0-based).")],
        on: Annotated[bool, Field(description="True = step on, False = off.")] = True,
    ) -> dict:
        """Toggle a single step on/off in a channel's grid (reversible)."""
        b = get_bridge()
        return safety.safe_write(
            b, tool="channel_set_step", scope="grid_bit:%d:%d" % (channel, index),
            command=protocol.CMD_CHANNEL_SET_GRID_BIT,
            params={"channel": channel, "index": index, "value": 1 if on else 0},
            build_restore=lambda before: {"command": protocol.CMD_CHANNEL_SET_GRID_BIT,
                                           "params": {"channel": channel, "index": index,
                                                      "value": before["value"]}})

    @mcp.tool(annotations={"title": "Set a channel step pattern", **_WR})
    def fl_channel_set_steps(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        steps: Annotated[list[int], Field(description="Step indices to turn ON (0-based); "
                         "all other steps in `length` are turned OFF.")],
        length: Annotated[int, Field(ge=1, le=256, description="Grid length to write.")] = 16,
    ) -> dict:
        """Write a whole step pattern in one reversible change: the given step
        indices go ON, the rest (within `length`) go OFF. E.g. a four-on-the-
        floor kick = steps [0,4,8,12]."""
        on = set(int(s) for s in steps)
        b = get_bridge()
        writes = []
        for i in range(length):
            writes.append({
                "snap_scope": "grid_bit:%d:%d" % (channel, i),
                "command": protocol.CMD_CHANNEL_SET_GRID_BIT,
                "params": {"channel": channel, "index": i, "value": 1 if i in on else 0},
                "restore": (lambda before, i=i: {"command": protocol.CMD_CHANNEL_SET_GRID_BIT,
                            "params": {"channel": channel, "index": i, "value": before["value"]}}),
            })
        return safety.safe_write_group(b, tool="channel_set_steps",
                                       scope="channel_grid:%d" % channel, writes=writes)

    @mcp.tool(annotations={"title": "Clear a channel grid", **_WR})
    def fl_channel_clear_grid(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        length: Annotated[int, Field(ge=1, le=256, description="Grid length to clear.")] = 16,
    ) -> dict:
        """Turn OFF all steps in a channel's grid (reversible)."""
        b = get_bridge()
        writes = []
        for i in range(length):
            writes.append({
                "snap_scope": "grid_bit:%d:%d" % (channel, i),
                "command": protocol.CMD_CHANNEL_SET_GRID_BIT,
                "params": {"channel": channel, "index": i, "value": 0},
                "restore": (lambda before, i=i: {"command": protocol.CMD_CHANNEL_SET_GRID_BIT,
                            "params": {"channel": channel, "index": i, "value": before["value"]}}),
            })
        return safety.safe_write_group(b, tool="channel_clear_grid",
                                       scope="channel_grid:%d" % channel, writes=writes)
