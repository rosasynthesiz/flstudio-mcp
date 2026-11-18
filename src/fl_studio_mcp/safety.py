"""Safety layer: snapshot / changelog / rollback / dry-run for write tools.

Lives on the MCP-SERVER side -- the server can do file I/O, the FL controller
script cannot. Every write tool routes through :func:`safe_write`, which
snapshots the affected scope, logs the change, executes, reads back, and
returns before+after so the caller (and a human) can see exactly what changed.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from functools import wraps
import threading
import time
from collections import deque
from pathlib import Path

from .protocol import (
    CMD_MIXER_GET_TRACK,
    CMD_CHANNEL_GET,
    CMD_MIXER_LIST_TRACKS,
    CMD_CHANNEL_LIST,
    CMD_PLUGIN_GET_PARAM,
    CMD_MIXER_GET_ROUTING,
    CMD_CHANNEL_GET_GRID,
    CMD_GET_TEMPO,
    CMD_PATTERN_GET_LENGTH,
    CMD_PLAYLIST_GET_TRACK,
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

    def _commit(self, entries):
        # Replace atomically; a persistence failure must stop a write or keep undo.
        _DIR.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=_DIR, prefix="changelog-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("".join(json.dumps(e, allow_nan=False) + "\n" for e in entries))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, _PATH)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        self._dq = deque(entries, maxlen=_MAX)

    def append(self, entry: dict) -> None:
        with self._lock:
            self._commit((list(self._dq) + [entry])[-_MAX:])

    def replace_last(self, entry):
        with self._lock:
            if not self._dq:
                raise RuntimeError("changelog is empty")
            self._commit(list(self._dq)[:-1] + ([entry] if entry is not None else []))

    def pop_last(self):
        with self._lock:
            if not self._dq:
                return None
            entry = self._dq[-1]
            self._commit(list(self._dq)[:-1])
            return entry

    def peek_last(self):
        """Keep the recovery record persisted until restoration succeeds."""
        with self._lock:
            return self._dq[-1] if self._dq else None

    def remove(self, entry):
        """Acknowledge this exact entry, without popping a newer write."""
        with self._lock:
            for i, candidate in enumerate(self._dq):
                if candidate is entry:
                    kept = list(self._dq)
                    del kept[i]
                    self._commit(kept)
                    return

    def recent(self, n: int = 10) -> list:
        with self._lock:
            return list(self._dq)[-n:]


_log = ChangeLog()
_dry_run = False

# FL commits plugin-parameter writes on a later script tick and can swallow one
# that arrives too soon after another. 0.4 s is the pace measured on live FL
# (see _landed_write). Calibration sweeps and undo use the same pace.
PLUGIN_SETTLE_SECONDS = 0.4
PLUGIN_VALUE_TOLERANCE = 0.02
# Now and then FL takes a second or more to accept a write (seen live right
# after another write landed). Sweeps and restores wait this many sends.
PLUGIN_WRITE_ATTEMPTS = 8


def set_dry_run(enabled) -> dict:
    global _dry_run
    _dry_run = bool(enabled)
    return {"dry_run": _dry_run}


def is_dry_run() -> bool:
    return _dry_run


def preview_write(*, tool, params=None, command=None):
    """Return a dry-run plan before any FL, note-script, or undo-log action."""
    if not _dry_run:
        return None
    planned = {"tool": tool, "params": params or {}}
    if command is not None:
        planned["command"] = command
    return {"ok": True, "dry_run": True, "planned": planned}


def get_changelog() -> ChangeLog:
    return _log


def take_snapshot(bridge, scope):
    """Read current state for a scope so it can be restored or recorded.

    scope: "mixer_track:N" | "channel:N" | "mixer_all" | "channels_all"
           | "plugin_param:TRACK:SLOT:PARAM" | "grid:CHANNEL:LENGTH"
           | "route:SRC:DST" | "pattern:N" | "tempo"
    """
    kind, _, arg = str(scope).partition(":")
    if kind == "tempo":
        return {"bpm": bridge.call(CMD_GET_TEMPO)["bpm"]}
    if kind == "mixer_track":
        return bridge.call(CMD_MIXER_GET_TRACK, {"index": int(arg)})
    if kind == "channel":
        return bridge.call(CMD_CHANNEL_GET, {"index": int(arg)})
    if kind == "plugin_param":
        track, slot, idx = (int(x) for x in arg.split(":"))
        return bridge.call(CMD_PLUGIN_GET_PARAM,
                           {"track": track, "slot": slot, "param": idx})
    if kind == "grid":
        channel, length = (int(x) for x in arg.split(":"))
        return bridge.call(CMD_CHANNEL_GET_GRID, {"channel": channel, "length": length})
    if kind == "route":
        src, dst = (int(x) for x in arg.split(":"))
        info = bridge.call(CMD_MIXER_GET_ROUTING, {"track": src})
        enabled = any(d.get("dst") == dst for d in info.get("routes_to", []))
        return {"src": src, "dst": dst, "enabled": enabled}
    if kind == "pattern":
        # Single-pattern read: name + length (ticks/bars) + selection state.
        # Doubles as the rename/select rollback basis (restore = old name /
        # previously selected index).
        return bridge.call(CMD_PATTERN_GET_LENGTH, {"index": int(arg)})
    if kind == "playlist_track":
        return bridge.call(CMD_PLAYLIST_GET_TRACK, {"track": int(arg)})
    if kind == "mixer_all":
        from .connection import fetch_all_pages
        return fetch_all_pages(bridge, CMD_MIXER_LIST_TRACKS, "tracks")
    if kind == "channels_all":
        from .connection import fetch_all_pages
        return fetch_all_pages(bridge, CMD_CHANNEL_LIST, "channels")
    raise ValueError("unknown snapshot scope: %r" % (scope,))


def _re_read(bridge, scope, fallback):
    """Fresh-tick re-read of a scope, falling back to the handler's echo."""
    try:
        return take_snapshot(bridge, scope)
    except Exception:
        return fallback


def _value_matches(after, field, expected, tol) -> bool:
    """Did the re-read ``field`` land on ``expected`` within ``tol``?

    A missing / non-numeric field counts as a miss (FL answered but the value
    is not what we asked for), so callers report ``verified: False`` rather
    than silently claiming success.
    """
    try:
        actual = float((after or {}).get(field))
        want = float(expected)
    except (TypeError, ValueError):
        return False
    return abs(actual - want) <= tol


def _landed_write(bridge, scope, command, params, vv, echo,
                  attempts_max=3, delay=0.4):
    """Re-issue ``command`` until a FRESH re-read of ``scope`` lands on target.

    ``vv=(field, expected, tol)`` is the value check; ``echo`` is the handler's
    same-tick reply to the first write (stale for params FL commits later).
    Each miss is re-written ``delay`` apart (0.4 s -- the live pacing, unlike
    the 0.06 s toggle coalescing window in :func:`_verify_retry`), for at most
    ``attempts_max`` retries. Returns ``(after, echo, attempts, verified)``;
    ``attempts`` counts the initial write, so 1 = it stuck first try.
    """
    field, expected, tol = vv
    def fresh_read():
        try:
            return take_snapshot(bridge, scope)
        except Exception as error:
            # A setter echo cannot prove that FL stored the requested value.
            return {"verification_error": str(error)}

    after = fresh_read()
    attempts = 1
    # Pickup mode (plugin window open) and stepped params silently swallow a
    # write: the value simply isn't there. Re-write at a live pace, then
    # report the truth instead of the requested value.
    while not _value_matches(after, field, expected, tol) and attempts <= attempts_max:
        time.sleep(delay)
        echo = bridge.call(command, params)
        after = fresh_read()
        attempts += 1
    return after, echo, attempts, _value_matches(after, field, expected, tol)


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


_operation_lock = threading.RLock()


def _serialized(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        with _operation_lock:
            if _dry_run:
                return fn(*args, **kwargs)
            # Coordinate separate MCP clients sharing the same durable undo log.
            _DIR.mkdir(parents=True, exist_ok=True)
            with (_DIR / "undo.lock").open("a+b") as lock:
                lock.seek(0, 2)
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    # A different process may have committed since this process started.
                    if _PATH.exists():
                        entries = [json.loads(line) for line in
                                   _PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
                        _log._dq = deque(entries, maxlen=_MAX)
                    else:
                        _log._dq = deque(maxlen=_MAX)
                    return fn(*args, **kwargs)
                finally:
                    if os.name == "nt":
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return run


class _ProjectBridge:
    """Controller checks the token in the same callback that performs each operation."""
    def __init__(self, bridge):
        state = bridge.call("get_project_state", {})
        token = state.get("project_token")
        if not isinstance(token, str) or not token or state.get("project_loading") is not False:
            raise RuntimeError("Project identity unavailable; update/reload the controller before writing")
        self.bridge, self.token = bridge, token
        self.pattern = None

    def call(self, command, params=None):
        params = dict(params or {}, _project_token=self.token)
        if self.pattern is not None:
            params["_expected_pattern"] = self.pattern
        return self.bridge.call(command, params)


def guard_project(bridge):
    """Keep discovery, calibration and final writes on one controller session."""
    return _ProjectBridge(bridge)


@_serialized
def temporary_plugin_write(bridge, address, operation):
    """Run a temporary parameter operation with durable, project-bound recovery.

    The transaction lock covers snapshot, sweep and restoration. Recovery is
    persisted before dispatch and removed only after independent readback.
    A project switch refuses restoration instead of targeting the new project.
    """
    if is_dry_run():
        raise ValueError("Temporary parameter writes are disabled during dry-run")
    bridge = _ProjectBridge(bridge)
    # Only an unfinished change in THIS project and session can be resolved (by
    # fl_rollback_last_change), so only that blocks. Entries left by another
    # project or an earlier FL session can never be applied here; they must not
    # lock the tool for good.
    if any(entry.get("incomplete") and entry.get("project_token") == bridge.token
           for entry in _log.recent(_MAX)):
        raise RuntimeError("An earlier change in this project did not finish. Run "
                           "fl_rollback_last_change first, then calibrate again.")
    address = {key: address[key] for key in ("track", "slot", "param")}
    scope = "plugin_param:{track}:{slot}:{param}".format(**address)
    before = take_snapshot(bridge, scope)
    value = before.get("v")
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError("Calibration requires a finite original parameter value in 0..1")
    restore = {"command": "plugin_set_param", "params": dict(address, value=value)}
    entry = {"tool": "plugin_calibrate_param", "scope": scope, "before": before,
             "restore": restore, "project_token": bridge.token, "pattern": None,
             "incomplete": True, "ts": time.time()}
    _log.append(entry)
    try:
        return operation(bridge)
    finally:
        try:
            # The sweep's last write is only just behind us, and FL can drop a
            # write that follows another too closely: send the original value
            # at the live pace until an independent read shows it.
            for attempt in range(PLUGIN_WRITE_ATTEMPTS):
                if attempt:
                    time.sleep(PLUGIN_SETTLE_SECONDS)
                result = bridge.call(restore["command"], restore["params"])
                if isinstance(result, dict) and result.get("ok") is False:
                    raise RuntimeError("Controller refused calibration restoration")
                after = take_snapshot(bridge, scope)
                actual = after.get("v")
                if (isinstance(actual, (int, float)) and not isinstance(actual, bool)
                        and math.isfinite(actual) and 0 <= actual <= 1
                        and abs(actual - value) <= 1e-4):
                    break
            else:
                raise RuntimeError("Calibration restoration readback did not match")
        except Exception as error:
            _log.replace_last(dict(entry, error=str(error)))
            raise RuntimeError(
                "Calibration restoration failed; recovery retained for original project: %s"
                % error
            ) from error
        _log.replace_last(None)


@_serialized
def safe_write(bridge, *, tool, scope, command, params, build_restore,
               verify=None, verify_value=None, verify_attempts=3,
               verify_delay=0.4, verify_state=None):
    """Snapshot -> log -> execute -> (verify+retry) -> read back. Honors dry-run.

    ``build_restore(before)`` returns ``{"command", "params"}`` that undoes
    this change. ``verify=(field, expected)`` re-issues the command until the
    reported state matches (used for flaky toggle writes like mute/solo).

    ``verify_state=(field, expected)`` requires an exact, independent readback
    (including strings). A mismatch or handler rejection returns ok=false;
    an unreadable result raises while retaining the recovery record. It never
    substitutes the setter echo or automatically repeats a pattern write.

    ``verify_value=(field, expected, tol)`` instead checks the FRESH re-read
    against a VALUE (plugin params): on a miss it re-writes and re-reads up to
    ``verify_attempts`` times, ``verify_delay`` apart -- a slow, live pace
    (0.4 s), unlike the 0.06 s toggle coalescing window. All attempts happen
    BEFORE the single changelog append, so the log still holds one entry whose
    ``after`` is the true final state. The response then carries
    ``verified: bool`` and ``attempts: int`` (1 = landed first try).
    """
    preview = preview_write(tool=tool, command=command, params=params)
    if preview is not None:
        return preview
    bridge = _ProjectBridge(bridge)
    before = take_snapshot(bridge, scope)
    if scope.startswith("grid:"):
        bridge.pattern = before["pattern"]
    restore = build_restore(before)
    entry = {"tool": tool, "scope": scope, "command": command, "params": params,
             "before": before, "restore": restore, "project_token": bridge.token,
             "pattern": bridge.pattern, "incomplete": True, "ts": time.time()}
    _log.append(entry)
    echo = None
    try:
        echo = bridge.call(command, params)
        echo = _verify_retry(bridge, command, params, echo, verify)
        # Ordinary writes retain their legacy fallback; verified writes require
        # an independent read and cannot claim success from the setter's echo.
        if verify_state is not None:
            after = take_snapshot(bridge, scope)
            field, expected = verify_state
            attempts = 1
            verified = after.get("ok") is True and after.get(field) == expected
        elif verify_value is None:
            after, attempts, verified = _re_read(bridge, scope, echo), 1, None
        else:
            after, echo, attempts, verified = _landed_write(
                bridge, scope, command, params, verify_value, echo,
                attempts_max=verify_attempts, delay=verify_delay)
    except Exception as error:
        # The initial command or a retry may have landed before the exception.
        # Preserve the original value rather than losing its recovery action.
        _log.replace_last(dict(entry, echo=echo, error=str(error)))
        raise
    _log.replace_last(dict(entry, after=after, echo=echo, incomplete=False))
    rejected = isinstance(echo, dict) and echo.get("ok") is False
    read_failed = isinstance(after, dict) and after.get("ok") is False
    ok = not rejected and not read_failed and (verify_state is None or verified)
    out = {"ok": bool(ok), "before": before, "after": after}
    if not ok:
        out["error"] = ((echo.get("error") if rejected else None)
                        or (after.get("error") if read_failed else None)
                        or "Write did not reach the requested state; recovery record retained")
    if verify_value is not None or verify_state is not None:
        out["verified"] = bool(verified) and not rejected and not read_failed
        out["attempts"] = attempts
    return out


@_serialized
def safe_write_group(bridge, *, tool, scope, writes, delay=0.0,
                     verify_values=None, verify_attempts=3,
                     verify_delay=0.4):
    """Apply several param writes as ONE rollback unit.

    ``writes`` is a list of dicts, each:
        {"snap_scope": "plugin_param:T:S:I",   # what to snapshot for restore
         "command": CMD, "params": {...},      # the write to execute
         "restore": callable(before)->{"command","params"}}  # how to undo it

    Snapshots ALL writes first (so we capture originals before any change),
    then executes them, and logs ONE changelog entry whose ``restores`` is a
    LIST -- so :func:`rollback_last_change` restores the group in reverse order, retaining recovery on failure.
    Honors dry-run. Returns {"ok", "before":[...], "after":[...]}.

    ``delay`` sleeps BETWEEN consecutive writes (FL drops writes that arrive
    back-to-back; 0.4 s is the tested pace for plugin params -- a batch of N
    therefore costs (N-1)*delay plus the RPC time). ``verify_values``
    is a per-write list mirroring :func:`safe_write`'s ``verify_value`` (or
    None to skip): each miss is re-written/re-read ``verify_attempts`` times
    before moving on, and the response gains parallel ``verified`` /
    ``attempts`` lists -- still one changelog entry.
    """
    if _dry_run:
        return {
            "ok": True, "dry_run": True,
            "planned": {"tool": tool, "scope": scope,
                        "writes": [{"command": w["command"], "params": w["params"]}
                                   for w in writes]},
        }
    bridge = _ProjectBridge(bridge)
    befores, restores = [], []
    for w in writes:                       # snapshot all first
        before = take_snapshot(bridge, w["snap_scope"])
        if w["snap_scope"].startswith("grid:"):
            if bridge.pattern is not None and bridge.pattern != before["pattern"]:
                raise RuntimeError("Selected pattern changed while snapshotting")
            bridge.pattern = before["pattern"]
        befores.append(before)
        restores.append(w["restore"](before))
    entry = {"tool": tool, "scope": scope, "group": True,
             "befores": befores, "restores": [],
             "snap_scopes": [w["snap_scope"] for w in writes],
             "project_token": bridge.token, "pattern": bridge.pattern,
             "incomplete": True, "ts": time.time()}
    afters, verified_out, attempts_out = [], [], []
    for i, w in enumerate(writes):
        if i and delay:
            time.sleep(delay)          # between writes -- FL drops back-to-back
        entry = dict(entry, restores=restores[:i + 1])
        if i == 0:
            _log.append(entry)
        else:
            _log.replace_last(entry)
        try:
            echo = bridge.call(w["command"], w["params"])
            after, verified, attempts = echo, None, None
            vv = verify_values[i] if (verify_values and i < len(verify_values)) else None
            if vv is not None:
                after, echo, attempts, verified = _landed_write(
                    bridge, w["snap_scope"], w["command"], w["params"], vv, echo,
                    attempts_max=verify_attempts, delay=verify_delay)
        except Exception as error:
            # The failed command may already have landed. Retain all originals
            # and the attempted prefix so the partial batch can still be undone.
            _log.replace_last(dict(entry, afters=afters, error=str(error)))
            raise
        afters.append(after)
        if verify_values is not None:
            # None = this write opted out of verification (not a failed one).
            verified_out.append(verified)
            attempts_out.append(attempts)
    if writes:
        _log.replace_last(dict(entry, afters=afters, incomplete=False))
    out = {"ok": True, "before": befores, "after": afters}
    if verify_values is not None:
        out["verified"] = verified_out
        out["attempts"] = attempts_out
    return out


def _snapshot_matches(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _snapshot_matches(actual[key], value)
            for key, value in expected.items())
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and abs(actual - expected) <= 0.0001
    return actual == expected


def _restore_expectation(restore, before):
    """Verify fields owned by this command, preserving unrelated manual edits.

    A group can change several fields in one snapshot scope. Comparing the
    entire scope after its first restore would prevent later restores running.
    Unknown commands keep the conservative full-snapshot verification.
    """
    fields = {
        "plugin_set_param": ("v",),
        "channel_set_grid": ("steps",),
        "mixer_set_route": ("enabled",),
        "set_tempo": ("bpm",),
        "pattern_rename": ("name",),
        "pattern_select": ("current",),
    }
    for target in ("mixer", "channel"):
        for command, field in (("volume", "vol_norm"), ("pan", "pan"),
                               ("mute", "mute"), ("solo", "solo"),
                               ("name", "name"), ("color", "color")):
            fields[f"{target}_set_{command}"] = (field,)
    owned = fields.get(restore["command"])
    if owned is None:
        return before
    if not isinstance(before, dict) or any(field not in before for field in owned):
        raise RuntimeError("Restore snapshot is missing the command's original fields")
    return {field: before[field] for field in owned}


@_serialized
def rollback_last_change(bridge):
    preview = preview_write(tool="rollback_last_change")
    if preview is not None:
        return preview
    entries = _log.recent(_MAX)
    if not entries:
        return {"ok": False, "error": "changelog is empty"}
    entry = entries[-1]
    try:
        bridge = _ProjectBridge(bridge)
        # Undo the newest change made in THIS project and session. Older entries
        # from another project or FL session stay in the log (they age out) but
        # are never applied here, and they do not hide this session's changes.
        entry = next((e for e in reversed(entries)
                      if e.get("project_token") and e["project_token"] == bridge.token), None)
        if entry is None:
            entry = entries[-1]
            raise RuntimeError("Nothing to undo in this project. The newest entry in the "
                               "log belongs to another project/controller session or "
                               "legacy history; it is kept but cannot be applied here.")
        bridge.pattern = entry.get("pattern")
        restores = entry.get("restores") if entry.get("group") else [entry.get("restore")]
        if not restores or any(not r for r in restores):
            raise RuntimeError("entry has no restore action")
        restored = []
        final_checks = {}
        # Reverse order also handles repeated writes to the same target.
        for i in reversed(range(len(restores))):
            r = restores[i]
            scope = entry["snap_scopes"][i] if entry.get("group") else entry["scope"]
            before = entry["befores"][i] if entry.get("group") else entry["before"]
            expected = _restore_expectation(r, before)
            result = bridge.call(r["command"], r.get("params") or {})
            if isinstance(result, dict) and result.get("ok") is False:
                raise RuntimeError("Controller refused restoration: %s" % result)
            after = take_snapshot(bridge, scope)
            if not _snapshot_matches(after, expected) and str(scope).startswith("plugin_param:"):
                # Same-tick read of a plugin parameter can still show the old
                # value. The restore sets an absolute value, so sending it
                # again is safe.
                for _ in range(PLUGIN_WRITE_ATTEMPTS - 1):
                    time.sleep(PLUGIN_SETTLE_SECONDS)
                    bridge.call(r["command"], r.get("params") or {})
                    after = take_snapshot(bridge, scope)
                    if _snapshot_matches(after, expected):
                        break
            if not _snapshot_matches(after, expected):
                raise RuntimeError("Restoration readback did not match original; undo retained")
            final_checks.setdefault(scope, {}).update(expected)
            restored.append(after)
        # Later restore commands may affect a field already restored earlier.
        # Verify their combined owned fields before forgetting the group.
        if entry.get("group"):
            for scope, expected in final_checks.items():
                if not _snapshot_matches(take_snapshot(bridge, scope), expected):
                    raise RuntimeError("Final restoration readback did not match; undo retained")
        _log.remove(entry)  # forget this exact entry, only after every read succeeds
        return {"ok": True, "rolled_back": entry.get("tool"),
                "scope": entry.get("scope"),
                "restored": restored if entry.get("group") else restored[0]}
    except Exception as error:
        return {"ok": False, "error": str(error), "undo_retained": True, "recovery_retained": True,
                "tool": entry.get("tool"), "scope": entry.get("scope")}
