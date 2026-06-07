#!/usr/bin/env python3
"""Live smoke suite for Priority 1/2 tools.

Covers:
- Effect slot + native EQ writes (rollback-safe)
- Pattern color/length writes (rollback-safe)
- Piano roll duplicate/velocity-ramp writes (undo-backed rollback)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("FLSTUDIO_MCP_TRANSPORT", "tcp")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol, safety  # noqa: E402
from fl_studio_mcp.connection import (
    FLCommandFailed,  # noqa: E402
    get_bridge,  # noqa: E402
)
from fl_studio_mcp.tools import effects, patterns_playlist, pianoroll  # noqa: E402


class MockMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, annotations=None):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def _pass(msg: str) -> None:
    print(f"[PASS] {msg}")


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _skip(msg: str) -> None:
    print(f"[SKIP] {msg}")


def _is_api_limited_error(exc: Exception) -> bool:
    txt = str(exc).lower()
    return (
        "api unavailable" in txt
        or "api-limited" in txt
        or "no attribute 'setpatternlength'" in txt
        or "unknown command" in txt
    )


def _rollback_and_check(bridge, label: str) -> bool:
    rb = safety.rollback_last_change(bridge)
    if not rb.get("ok"):
        _fail(f"{label}: rollback failed: {rb}")
        return False
    _pass(f"{label}: rollback ok")
    return True


def _find_effect_target(tools: dict) -> tuple[int, int] | None:
    # Prefer a real occupied slot on commonly-used fixture tracks first,
    # then scan a wider range.
    scan = list(dict.fromkeys([1, 29, 32, 42, 56, 57] + list(range(1, 61))))
    for track in scan:
        try:
            slots = tools["fl_effect_list_slots"](track).get("slots", [])
        except Exception:
            continue
        for row in slots:
            if row.get("valid"):
                return track, int(row["slot"])
    return None


def main() -> int:
    bridge = get_bridge()

    try:
        pong = bridge.call(protocol.CMD_PING, {})
    except Exception as e:
        print(f"[FAIL] bridge ping failed: {type(e).__name__}: {e}")
        return 1

    print(f"FL: {pong.get('fl_version')} | build={pong.get('build')}")
    print("Running Priority 1/2 live smoke with immediate rollback...")
    ok = True

    # Register tools and bind live bridge.
    mcp = MockMCP()
    patterns_playlist.register(mcp)
    effects.register(mcp)
    pianoroll.register(mcp)
    patterns_playlist.get_bridge = lambda: bridge
    effects.get_bridge = lambda: bridge
    pianoroll.get_bridge = lambda: bridge

    # Capability preflight: if controller script wasn't reloaded, new commands
    # are unknown and the smoke run must stop early with a clear message.
    try:
        _ = mcp.tools["fl_pattern_find_empty"]()
    except FLCommandFailed as e:
        if "Unknown command" in str(e):
            print(
                "[BLOCKED] Controller script is stale (missing new commands). "
                "Reload FL MIDI scripts and restart the daemon, then rerun this smoke suite."
            )
            print(f"Details: {e}")
            return 2
        raise

    # 1) Pattern color + length ------------------------------------------------
    selected = bridge.call(protocol.CMD_PATTERN_SELECTED, {}).get("selected", 1)
    base_pat = mcp.tools["fl_pattern_get"](selected)

    base_color = int(base_pat["color"]["int"])
    temp_color = base_color ^ 0x00303030
    res = mcp.tools["fl_pattern_set_color"](selected, color=temp_color)
    if res.get("ok") and int(res["after"]["color"]["int"]) == temp_color:
        _pass("pattern_set_color write/readback")
    else:
        _fail(f"pattern_set_color write mismatch: {res}")
        ok = False
    ok = _rollback_and_check(bridge, "pattern_set_color") and ok
    restored_pat = mcp.tools["fl_pattern_get"](selected)
    if int(restored_pat["color"]["int"]) == base_color:
        _pass("pattern_set_color restore verified")
    else:
        _fail("pattern_set_color restore mismatch")
        ok = False

    base_len = float(base_pat.get("length", 16))
    temp_len = base_len + 1.0 if base_len < 63 else max(1.0, base_len - 1.0)
    try:
        res = mcp.tools["fl_pattern_set_length"](selected, temp_len)
        after_len = float(res.get("after", {}).get("length", temp_len))
        if res.get("ok") and abs(after_len - temp_len) <= 0.01:
            _pass("pattern_set_length write/readback")
        else:
            _fail(f"pattern_set_length write mismatch: {res}")
            ok = False
        ok = _rollback_and_check(bridge, "pattern_set_length") and ok
        restored_pat = mcp.tools["fl_pattern_get"](selected)
        if abs(float(restored_pat.get("length", base_len)) - base_len) <= 0.01:
            _pass("pattern_set_length restore verified")
        else:
            _fail("pattern_set_length restore mismatch")
            ok = False
    except FLCommandFailed as e:
        if _is_api_limited_error(e):
            _skip(f"pattern_set_length unavailable on this FL build: {e}")
        else:
            raise

    # 2) Effects + EQ ----------------------------------------------------------
    target = _find_effect_target(mcp.tools)
    if target is None:
        print("[WARN] No valid plugin slot found in first 40 tracks; skipping effects slot tests.")
    else:
        track, slot = target
        print(f"Effect target: track={track} slot={slot}")

        slot_before = mcp.tools["fl_effect_get_slot"](track, slot)
        temp_mix = 0.2 if float(slot_before.get("mix", 0.8)) > 0.4 else 0.8
        res = mcp.tools["fl_effect_set_slot_mix"](track, slot, temp_mix)
        if res.get("ok") and abs(float(res["after"]["mix"]) - temp_mix) <= 0.03:
            _pass("effect_set_slot_mix write/readback")
        else:
            _fail(f"effect_set_slot_mix write mismatch: {res}")
            ok = False
        ok = _rollback_and_check(bridge, "effect_set_slot_mix") and ok
        slot_restored = mcp.tools["fl_effect_get_slot"](track, slot)
        if abs(float(slot_restored["mix"]) - float(slot_before["mix"])) <= 0.03:
            _pass("effect_set_slot_mix restore verified")
        else:
            _fail("effect_set_slot_mix restore mismatch")
            ok = False

        slots_state = mcp.tools["fl_effect_get_track_slots_enabled"](track)
        target_enabled = not bool(slots_state.get("enabled", True))
        try:
            res = mcp.tools["fl_effect_set_track_slots_enabled"](track, target_enabled)
            if res.get("ok") and bool(res["after"]["enabled"]) == target_enabled:
                _pass("effect_set_track_slots_enabled write/readback")
            else:
                _fail(f"effect_set_track_slots_enabled mismatch: {res}")
                ok = False
            ok = _rollback_and_check(bridge, "effect_set_track_slots_enabled") and ok
            slots_restored = mcp.tools["fl_effect_get_track_slots_enabled"](track)
            if bool(slots_restored.get("enabled", True)) == bool(slots_state.get("enabled", True)):
                _pass("effect_set_track_slots_enabled restore verified")
            else:
                _fail("effect_set_track_slots_enabled restore mismatch")
                ok = False
        except FLCommandFailed as e:
            if _is_api_limited_error(e):
                _skip(f"effect_set_track_slots_enabled unavailable on this FL build: {e}")
            else:
                raise

        eq_before = mcp.tools["fl_eq_get"](track)
        b1 = next((b for b in eq_before.get("bands", []) if int(b.get("band", -1)) == 1), None)
        if b1 is None:
            print("[WARN] Could not read EQ band 1; skipping EQ write smoke.")
        else:
            base_gain = float(b1.get("gain", 0.0))
            temp_gain = max(-1.0, min(1.0, base_gain + (0.1 if base_gain <= 0 else -0.1)))
            try:
                res = mcp.tools["fl_eq_set_band"](track, 1, gain=temp_gain)
                b1_after = next(
                    (
                        b
                        for b in res.get("after", {}).get("bands", [])
                        if int(b.get("band", -1)) == 1
                    ),
                    None,
                )
                if res.get("ok") and b1_after and abs(float(b1_after["gain"]) - temp_gain) <= 0.02:
                    _pass("eq_set_band write/readback")
                else:
                    _fail(f"eq_set_band mismatch: {res}")
                    ok = False
                ok = _rollback_and_check(bridge, "eq_set_band") and ok
                eq_restored = mcp.tools["fl_eq_get"](track)
                b1_restored = next(
                    (b for b in eq_restored.get("bands", []) if int(b.get("band", -1)) == 1),
                    None,
                )
                if b1_restored and abs(float(b1_restored["gain"]) - base_gain) <= 0.02:
                    _pass("eq_set_band restore verified")
                else:
                    _fail("eq_set_band restore mismatch")
                    ok = False
            except FLCommandFailed as e:
                if _is_api_limited_error(e):
                    _skip(f"eq_set_band unavailable on this FL build: {e}")
                else:
                    raise

    # 3) Piano roll duplicate + velocity ramp ---------------------------------
    # Readback for note content is API-limited. We verify write success + immediate undo.
    res = mcp.tools["fl_piano_duplicate"](1.0)
    if res.get("ok"):
        _pass("piano_duplicate write path executed")
    else:
        _fail(f"piano_duplicate failed: {res}")
        ok = False
    ok = _rollback_and_check(bridge, "piano_duplicate") and ok

    res = mcp.tools["fl_piano_velocity_ramp"](0.25, 0.9)
    if res.get("ok"):
        _pass("piano_velocity_ramp write path executed")
    else:
        _fail(f"piano_velocity_ramp failed: {res}")
        ok = False
    ok = _rollback_and_check(bridge, "piano_velocity_ramp") and ok

    # settle one tick
    time.sleep(0.1)
    print("Live smoke done.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
