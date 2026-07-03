"""Safety layer: snapshot / changelog / rollback / dry-run for write tools.

Lives on the MCP-SERVER side -- the server can do file I/O, the FL controller
script cannot. Every write tool routes through :func:`safe_write`, which
snapshots the affected scope, logs the change, executes, reads back, and
returns before+after so the caller (and a human) can see exactly what changed.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path

from .protocol import (
    CMD_CHANNEL_GET,
    CMD_CHANNEL_GET_GRID_BIT,
    CMD_CHANNEL_LIST,
    CMD_MIXER_GET_ROUTING,
    CMD_MIXER_GET_TRACK,
    CMD_MIXER_LIST_TRACKS,
    CMD_PLAYLIST_GET_TRACK,
    CMD_PLUGIN_GET_PARAM,
)

_DIR = Path.home() / ".flstudio-mcp"
_PATH = _DIR / "changelog.jsonl"
_MAX = 50


class ChangeLog:
    """Rolling deque of the last ``_MAX`` writes, persisted to a jsonl file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dq: deque = deque(maxlen=_MAX)
        self._load()

    def _load(self) -> None:
        try:
            if _PATH.exists():
                for line in _PATH.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        self._dq.append(json.loads(line))
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            _DIR.mkdir(parents=True, exist_ok=True)
            # Atomic write: serialise to a temp file in the same dir, then
            # os.replace() over the target. Prevents a truncated/corrupt log if
            # the process dies mid-write.
            payload = "".join(json.dumps(e) + "\n" for e in self._dq)
            tmp = _PATH.with_suffix(_PATH.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, _PATH)
        except Exception:
            pass

    def append(self, entry: dict) -> None:
        with self._lock:
            self._dq.append(entry)
            self._persist()

    def pop_last(self):
        with self._lock:
            if not self._dq:
                return None
            entry = self._dq.pop()
            self._persist()
            return entry

    def recent(self, n: int = 10) -> list:
        with self._lock:
            return list(self._dq)[-n:]


_log = ChangeLog()
_dry_run = False


def set_dry_run(enabled) -> dict:
    global _dry_run
    _dry_run = bool(enabled)
    return {"dry_run": _dry_run}


def is_dry_run() -> bool:
    return _dry_run


def get_changelog() -> ChangeLog:
    return _log


def take_snapshot(bridge, scope):
    """Read current state for a scope so it can be restored or recorded.

    scope: "mixer_track:N" | "channel:N" | "mixer_all" | "channels_all"
           | "plugin_param:TRACK:SLOT:PARAM"
    """
    kind, _, arg = str(scope).partition(":")
    if kind == "mixer_track":
        return bridge.call(CMD_MIXER_GET_TRACK, {"index": int(arg)})
    if kind == "channel":
        return bridge.call(CMD_CHANNEL_GET, {"index": int(arg)})
    if kind == "plugin_param":
        track, slot, idx = (int(x) for x in arg.split(":"))
        return bridge.call(CMD_PLUGIN_GET_PARAM,
                           {"track": track, "slot": slot, "param": idx})
    if kind == "route":
        src, dst = (int(x) for x in arg.split(":"))
        info = bridge.call(CMD_MIXER_GET_ROUTING, {"track": src})
        enabled = any(d.get("dst") == dst for d in info.get("routes_to", []))
        return {"src": src, "dst": dst, "enabled": enabled}
    if kind == "playlist_track":
        return bridge.call(CMD_PLAYLIST_GET_TRACK, {"track": int(arg)})
    if kind == "grid_bit":
        ch, idx = (int(x) for x in arg.split(":"))
        return bridge.call(CMD_CHANNEL_GET_GRID_BIT, {"channel": ch, "index": idx})
    if kind == "mixer_all":
        from .connection import fetch_all_pages
        return fetch_all_pages(bridge, CMD_MIXER_LIST_TRACKS, "tracks")
    if kind == "channels_all":
        from .connection import fetch_all_pages
        return fetch_all_pages(bridge, CMD_CHANNEL_LIST, "channels")
    raise ValueError("unknown snapshot scope: %r" % (scope,))


def _verify_retry(bridge, command, params, result, verify, attempts=4, delay=0.06):
    """Re-issue a toggle-style command until its reported state sticks.

    FL occasionally drops a mute/solo toggle when it lands too close to other
    writes (it coalesces these over a short window). Each re-issue is a fresh
    SysEx = a fresh FL script-tick + latency = spacing, so it lands.
    """
    if verify is None:
        return result
    field, expected = verify
    n = 0
    while result.get(field) != expected and n < attempts:
        time.sleep(delay)
        result = bridge.call(command, params)
        n += 1
    return result


def safe_write(bridge, *, tool, scope, command, params, build_restore, verify=None):
    """Snapshot -> log -> execute -> (verify+retry) -> read back. Honors dry-run.

    ``build_restore(before)`` returns ``{"command", "params"}`` that undoes
    this change. ``verify=(field, expected)`` re-issues the command until the
    reported state matches (used for flaky toggle writes like mute/solo).
    """
    if _dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "planned": {"tool": tool, "command": command, "params": params},
        }
    before = take_snapshot(bridge, scope)
    restore = build_restore(before)
    echo = bridge.call(command, params)
    echo = _verify_retry(bridge, command, params, echo, verify)
    # FL commits some writes (notably mixer fader volume/pan) on a LATER
    # script-tick, so the handler's SAME-tick readback (echo) can report the
    # stale pre-write value. Re-read the scope on a FRESH tick for the TRUE
    # post-write state. Fall back to the echo if the scope can't be re-read.
    try:
        after = take_snapshot(bridge, scope)
    except Exception:
        after = echo
    _log.append({
        "tool": tool, "scope": scope, "command": command, "params": params,
        "before": before, "after": after, "echo": echo, "restore": restore,
        "ts": time.time(),
    })
    return {"ok": True, "before": before, "after": after}


def safe_write_group(bridge, *, tool, scope, writes):
    """Apply several param writes as ONE rollback unit.

    ``writes`` is a list of dicts, each:
        {"snap_scope": "plugin_param:T:S:I",   # what to snapshot for restore
         "command": CMD, "params": {...},      # the write to execute
         "restore": callable(before)->{"command","params"}}  # how to undo it

    Snapshots ALL writes first (so we capture originals before any change),
    then executes them, and logs ONE changelog entry whose ``restores`` is a
    LIST -- so :func:`rollback_last_change` reverts the whole group atomically.
    Honors dry-run. Returns {"ok", "before":[...], "after":[...]}.
    """
    if _dry_run:
        return {
            "ok": True, "dry_run": True,
            "planned": {"tool": tool, "scope": scope,
                        "writes": [{"command": w["command"], "params": w["params"]}
                                   for w in writes]},
        }
    befores, restores = [], []
    for w in writes:                       # snapshot all first
        before = take_snapshot(bridge, w["snap_scope"])
        befores.append(before)
        restores.append(w["restore"](before))
    afters = [bridge.call(w["command"], w["params"]) for w in writes]
    _log.append({
        "tool": tool, "scope": scope, "group": True,
        "befores": befores, "afters": afters, "restores": restores,
        "ts": time.time(),
    })
    return {"ok": True, "before": befores, "after": afters}


def rollback_last_change(bridge):
    entry = _log.pop_last()
    if entry is None:
        return {"ok": False, "error": "changelog is empty"}
    if entry.get("group"):                 # grouped write -> replay every restore
        restored = [bridge.call(r["command"], r.get("params") or {})
                    for r in (entry.get("restores") or [])]
        return {"ok": True, "rolled_back": entry.get("tool"),
                "scope": entry.get("scope"), "restored": restored}
    restore = entry.get("restore")
    if not restore:
        return {"ok": False, "error": "entry has no restore action",
                "tool": entry.get("tool")}
    rparams = restore.get("params") or {}
    restored = bridge.call(restore["command"], rparams)
    # mute/solo restores are toggles -> verify+retry like safe_write
    if "state" in rparams:
        field = "mute" if "mute" in restored else ("solo" if "solo" in restored else None)
        if field is not None:
            restored = _verify_retry(bridge, restore["command"], rparams,
                                     restored, (field, rparams["state"]))
    return {"ok": True, "rolled_back": entry.get("tool"),
            "scope": entry.get("scope"), "restored": restored}
