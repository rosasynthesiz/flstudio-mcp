"""FL undo tool (E-5): one general.undoUp() step, outside the safety layer.

Why not safe_write: nothing readable describes what the jump will undo, so a
snapshot is impossible; a changelog entry with no restore would either lie or
block rolling back the previous REAL write. Undo therefore joins
fl_play / fl_stop / fl_record as a direct controller command with an explicit
warning.

Coverage varies (live on FL 26.1.7): volume/parameter writes undo; some API
actions (e.g. pattern rename) are NOT in FL's undo stack at all. Undo and
fl_rollback_last_change do NOT commute, so the response surfaces the newest
changelog entry the undo may have just cancelled.
"""
from __future__ import annotations

import time

from fastmcp import FastMCP

from .. import protocol, safety
from ..connection import get_bridge

_WARNING = (
    "undo and fl_rollback_last_change do NOT commute: an undo jump can "
    "cancel a rollback (and a later rollback can jump again). Undo "
    "coverage varies -- volume/parameter writes undo; some API actions "
    "(e.g. pattern rename) are not in FL's undo stack. ALWAYS re-read "
    "state with a fresh get after fl_undo."
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={
        "title": "FL Undo (one step, NOT rollback-covered)",
        "readOnlyHint": False, "destructiveHint": False,
        "idempotentHint": False, "openWorldHint": True,
    })
    def fl_undo() -> dict:
        """One FL undo step (general.undoUp). WARNING: not covered by
        fl_rollback_last_change -- undo jumps FL's own history and nothing
        readable describes what was undone, so no snapshot exists. Undo and
        rollback do NOT commute (see the response warning); coverage
        varies by action type. The response includes `last_rollback` -- the
        newest changelog entry, which an undo may have just cancelled."""
        recent = safety.get_changelog().recent(1)
        last = recent[-1] if recent else None
        last_rollback = None
        if last:
            last_rollback = {
                "tool": last.get("tool"),
                "scope": last.get("scope"),
                "age_s": round(time.time() - float(last.get("ts") or 0), 1),
            }
        res = get_bridge().call(protocol.CMD_UNDO, {})
        out = dict(res) if isinstance(res, dict) else {"ok": bool(res)}
        out["warning"] = _WARNING
        out["last_rollback"] = last_rollback
        return out
