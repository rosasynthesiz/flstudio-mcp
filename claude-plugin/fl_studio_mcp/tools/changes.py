"""Session history: list what this session changed, and roll several back.

The safety layer already records every write (tool, scope, the value it
replaced, and how to restore it) and can undo the newest one. These two tools
close the gap the roadmap names: a plain list of this session's changes, and
"undo all of them" without calling `fl_rollback_last_change` by hand.

Read-only listing never touches FL beyond asking which project is open (so
entries can be marked undoable here). Bulk rollback replays the same restore
path as the single-step tool, newest first; if one restore fails it stops and
reports exactly how far it got, keeping the failed entry.
"""

from __future__ import annotations

import time

from fastmcp import FastMCP

from .. import safety
from ..connection import get_bridge

_MAX_BULK = 20
_SUMMARY_CHARS = 140
_HINT = (
    "Newest first. 'undoable' means the entry belongs to the open project and "
    "can be restored here. fl_rollback_changes undoes the newest N one by one; "
    "FL redo is not scriptable, so re-running a write is the only way back."
)
_WARNING = (
    "Bulk rollback removes the rolled-back entries from the changelog. FL's "
    "redo is not scriptable, so re-running the original writes is the only way "
    "back."
)


def _short(value, limit: int = 40) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _diff(before, after) -> list:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    return [key for key in before
            if key in after and before[key] != after[key]
            and key not in ("ok", "error")]


def _changed(entry: dict) -> list:
    if entry.get("group"):
        changed = []
        for scope, before, after in zip(entry.get("snap_scopes") or [],
                                        entry.get("befores") or [],
                                        entry.get("afters") or [], strict=False):
            changed += [f"{scope}:{key}" for key in _diff(before, after)]
        return changed[:8]
    return _diff(entry.get("before"), entry.get("after"))[:8]


def _summary(entry: dict) -> str:
    tool = str(entry.get("tool") or "?")
    if entry.get("group"):
        count = len(entry.get("snap_scopes") or [])
        return f"{tool} ({count} writes)"[:_SUMMARY_CHARS]
    params = entry.get("params") or {}
    pairs = ", ".join(
        f"{key}={_short(value)}" for key, value in params.items()
        if not str(key).startswith("_"))
    return f"{tool}({pairs})"[:_SUMMARY_CHARS]


def _current_token(bridge):
    try:
        token = bridge.call("get_project_state", {}).get("project_token")
    except Exception:
        return None
    return token if isinstance(token, str) and token else None


def _describe(number: int, entry: dict, token) -> dict:
    entry_token = entry.get("project_token")
    if token is None:
        project = "unknown"
    elif entry_token and entry_token == token:
        project = "current"
    else:
        project = "other"
    ts = entry.get("ts")
    age = round(max(0.0, time.time() - ts), 1) if isinstance(ts, (int, float)) else None
    return {
        "n": number,
        "tool": entry.get("tool"),
        "scope": entry.get("scope"),
        "age_s": age,
        "project": project,
        "undoable": project == "current" and not entry.get("incomplete"),
        "summary": _summary(entry),
        "changed": _changed(entry),
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={
        "title": "List this session's changes",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": True,
    })
    def fl_list_changes(limit: int = 10, start: int = 0) -> dict:
        """What changed in this session, newest first, with what can be undone.

        Reads the safety changelog (the last 50 writes, shared by every server
        on this machine). Each entry carries the tool, the scope, its age, a
        one-line summary, the fields that actually changed, and whether it can
        be rolled back in the open project right now. Read-only: it only asks
        FL which project is open, so `fl_rollback_changes` can undo safely.
        """
        bridge = get_bridge()
        limit = max(1, min(int(limit), 50))
        start = max(0, int(start))
        entries = list(reversed(safety.get_changelog().recent(50)))
        total = len(entries)
        page = entries[start:start + limit]
        token = _current_token(bridge)
        end = start + len(page)
        return {
            "ok": True,
            "total": total,
            "start": start,
            "changes": [_describe(n, entry, token)
                        for n, entry in enumerate(page, start + 1)],
            "next_start": end if end < total else None,
            "hint": _HINT,
        }

    @mcp.tool(annotations={
        "title": "Roll back the newest N changes",
        "readOnlyHint": False, "destructiveHint": True,
        "idempotentHint": False, "openWorldHint": True,
    })
    def fl_rollback_changes(count: int = 1) -> dict:
        """Undo the newest N changes of the open project, one at a time.

        Uses exactly the path of `fl_rollback_last_change` (saved snapshot,
        fresh readback, entry removed only after the restore lands), newest
        first. Stops at the first failure and says how many landed, so a
        partial rollback is never reported as complete. Entries from another
        project or controller session are never applied here.
        """
        planned = safety.preview_write(tool="rollback_changes",
                                       params={"count": count})
        if planned is not None:
            return planned
        try:
            count = int(count)
        except (TypeError, ValueError):
            return {"ok": False, "error": "count must be an integer"}
        if not 1 <= count <= _MAX_BULK:
            return {"ok": False,
                    "error": f"count must be between 1 and {_MAX_BULK}"}
        bridge = get_bridge()
        done = []
        for _ in range(count):
            result = safety.rollback_last_change(bridge)
            if not result.get("ok"):
                return {
                    "ok": False,
                    "rolled_back": len(done),
                    "requested": count,
                    "changes": done,
                    "error": result.get("error"),
                    "warning": _WARNING,
                }
            done.append({"tool": result.get("rolled_back"),
                         "scope": result.get("scope")})
        return {
            "ok": True,
            "rolled_back": len(done),
            "requested": count,
            "changes": done,
            "warning": _WARNING,
        }
