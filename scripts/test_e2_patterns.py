#!/usr/bin/env python3
"""E-2 live check: pattern list/select/rename/get_length + rollback.

Drives the REAL tools in-process (same path an MCP client uses). The
controller handlers (pattern_select/rename/get_length) must be live in FL --
deploy the repo controller and restart FL first, then check fl_ping.build.

    set FLSTUDIO_MCP_TRANSPORT=tcp
    python scripts/test_e2_patterns.py

Scenario (from 01 E-2 DoD):
  1. fl_pattern_list paginates (walk every page) and includes our test pattern
  2. fl_arrange_new_pattern -> TEST index T
  3. fl_pattern_rename(T, "E2TEST_renamed") verified, old name snapshotted
  4. fl_pattern_select(other) -> verified; prev_index/prev_name reported
  5. fl_pattern_get_length(T) -> ticks/bars sane (bars <= 64)
  6. rollback select -> previous pattern selected again
  7. rollback rename -> original name back
  8. rejection: select(0) and select(9999) fail with a range error

The created pattern CANNOT be deleted via API (FL limitation): it is renamed
to TMP_E2_deleted_after_test -- the user removes it by hand in FL.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import safety  # noqa: E402
from fl_studio_mcp.connection import get_bridge  # noqa: E402
from fl_studio_mcp.server import build_server  # noqa: E402

TMP_NAME = "TMP_E2_deleted_after_test"
RENAMED = "E2TEST_renamed"


def unwrap(result):
    for attr in ("data", "structured_content", "structuredContent"):
        v = getattr(result, attr, None)
        if v is not None:
            return v
    if isinstance(result, tuple) and result:
        return unwrap(result[0]) if hasattr(result[0], "data") else result[0]
    return result


def main() -> int:
    m = build_server()

    async def call(name, args):
        return unwrap(await m.call_tool(name, args))

    fails = []

    def check(label, cond, extra=""):
        print(("PASS " if cond else "FAIL ") + label + ("  " + extra if extra else ""))
        if not cond:
            fails.append(label)

    # baseline state ------------------------------------------------------
    before_count = asyncio.run(call("fl_pattern_list", {"limit": 1})).get("total")
    prev_sel = asyncio.run(call("fl_pattern_get_length", {"index": 1})).get("current")
    print(f"baseline: patterns={before_count} selected={prev_sel}")

    # 1. pagination -------------------------------------------------------
    full = asyncio.run(call("fl_pattern_list", {}))
    leftovers = [p for p in full.get("patterns", [])
                 if p["name"].startswith("TMP_")]
    if leftovers:
        print(f"WARNING: leftover test pattern(s) from a previous run: "
              f"{[p['pattern'] for p in leftovers]} -- delete them in FL "
              f"(Del in the pattern picker) before re-running.")
    allp, cur = [], 0
    while True:
        page = asyncio.run(call("fl_pattern_list", {"start": cur, "limit": 3}))
        chunk = page.get("patterns") or []
        if not chunk:
            break
        allp.extend(chunk)
        cur += len(chunk)
        if cur >= (page.get("total") or 0):
            break
    check("list returns total + items", full.get("total") == len(full.get("patterns", [])),
          f"total={full.get('total')} items={len(full.get('patterns', []))}")
    check("list items 1-based contiguous",
          [p["pattern"] for p in full.get("patterns", [])] ==
          list(range(1, (full.get("total") or 0) + 1)))
    check("paged walk matches full list",
          [p["pattern"] for p in allp] ==
          [p["pattern"] for p in full.get("patterns", [])])

    # 2. create -----------------------------------------------------------
    created = asyncio.run(call("fl_arrange_new_pattern", {"name": "E2TEST"}))
    t = created.get("index")
    check("created test pattern", bool(created.get("ok")) and bool(t),
          f"index={t} selected={created.get('selected')}")
    if not t:
        print("ABORT: cannot create test pattern")
        return 1

    try:
        # 3. rename -------------------------------------------------------
        rr = asyncio.run(call("fl_pattern_rename", {"index": t, "name": RENAMED}))
        print(f"rename: ok={rr.get('ok')} before.name={(rr.get('before') or {}).get('name')!r}"
              f" after.name={(rr.get('after') or {}).get('name')!r}")
        check("rename landed", (rr.get("after") or {}).get("name") == RENAMED)
        check("rename snapshotted old name", (rr.get("before") or {}).get("name") == "E2TEST",
              repr((rr.get("before") or {}).get("name")))

        # 4. select another ----------------------------------------------
        # A fresh project may have no OTHER pattern to select: create a
        # helper one (renamed to TMP_ in cleanup, like the main test one).
        second = None
        if t != 1:
            other = 1
        else:
            second = asyncio.run(call("fl_arrange_new_pattern",
                                      {"name": "E2TEST2"}))
            other = second.get("index")
            if not other:
                print("ABORT: no second pattern for the select step")
                return 1
        sr = asyncio.run(call("fl_pattern_select", {"index": other}))
        print(f"select {other}: ok={sr.get('ok')} prev_index={sr.get('prev_index')}")
        check("select landed (re-read current)", (sr.get("after") or {}).get("current") == other)
        check("select reports prev selection", (sr.get("before") or {}).get("current") == t,
              f"before.current={(sr.get('before') or {}).get('current')}")

        # 5. get_length ---------------------------------------------------
        gl = asyncio.run(call("fl_pattern_get_length", {"index": t}))
        print(f"length: beats={gl.get('length_beats')} bars={gl.get('length_bars')} "
              f"ticks={gl.get('length_ticks')} ppq={gl.get('ppq')}")
        check("length sane (1..64 bars)", 0 < (gl.get("length_bars") or 0) <= 64)
        check("length beats*ppq == ticks",
              (gl.get("length_beats") or 0) * (gl.get("ppq") or 0) ==
              (gl.get("length_ticks") or -1))
        check("length carries name", gl.get("name") in (RENAMED, "E2TEST"))

        # 6/7. rollbacks (LIFO) ------------------------------------------
        n0 = len(safety.get_changelog().recent(50))
        safety.rollback_last_change(get_bridge())
        sel_after = asyncio.run(call("fl_pattern_get_length", {"index": t})).get("current")
        check("rollback select restored previous", sel_after == t,
              f"current={sel_after} want={t}")
        safety.rollback_last_change(get_bridge())
        name_after = asyncio.run(call("fl_pattern_get_length", {"index": t})).get("name")
        check("rollback rename restored old name", name_after == "E2TEST",
              repr(name_after))
        n1 = len(safety.get_changelog().recent(50))
        print(f"changelog entries consumed: {n0 - n1} ({n0} -> {n1})")

        # 8. rejections ---------------------------------------------------
        # 8. rejections (tool-level ge=1 OR controller range guard) --------
        def try_select(idx):
            try:
                return asyncio.run(call("fl_pattern_select", {"index": idx}))
            except Exception as e:            # pydantic ge=1 raises pre-controller
                return {"ok": False, "error": str(e)}

        for idx in (0, 9999, -3):
            bad = try_select(idx)
            err = str(bad.get("error", ""))
            check(f"select({idx}) rejected", bad.get("ok") is False and err,
                  repr(err[:80]))
        try:
            gl0 = asyncio.run(call("fl_pattern_get_length", {"index": 0}))
        except Exception as e:
            gl0 = {"ok": False, "error": str(e)}
        check("get_length(0) rejected", gl0.get("ok") is False)
    finally:
        # leave no garbage: rename the test patterns to the TMP marker ------
        asyncio.run(call("fl_pattern_rename", {"index": t, "name": TMP_NAME}))
        if second:
            asyncio.run(call("fl_pattern_rename", {"index": second.get("index"),
                                                   "name": TMP_NAME}))
        if prev_sel:
            asyncio.run(call("fl_pattern_select", {"index": prev_sel}))
        print(f"\ncleanup: pattern(s) {[t, second.get('index') if second else None]} "
              f"renamed to {TMP_NAME!r} "
              f"(FL API cannot delete patterns -- remove them by hand in FL)")

    print()
    if fails:
        print(f"FAILED {len(fails)}: {fails}")
        return 1
    print("ALL PASS (0 failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
