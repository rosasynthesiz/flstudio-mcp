#!/usr/bin/env python3
"""E-1 live check: verified single write + batch write + one-step rollback.

Builds the FastMCP server and drives the REAL tools in-process (the same path
an MCP client uses). Non-destructive: every value is restored by rolling the
changelog back to the baseline it captured.

    set FLSTUDIO_MCP_TRANSPORT=tcp
    python scripts/test_e1_plugin_write.py [track] [slot] \
        [writable_params_csv] [refused_param]

Defaults target Fruity Parametric EQ 2 at track 1 slot 0:

    writable = "Band 1 level:0.6,Band 3 level:0.55,Main level:0.66"
    refused  = "Band 5 width"      # FL ignores it -> verified:false + hint

A param the plugin genuinely refuses is REQUIRED for the negative case; pass
an empty string to skip it.

FL26 write facts this exercises (measured on Fruity Parametric EQ 2):
  * levels/gains take an arbitrary 0..1 value,
  * stepped params (filter types, orders, selectors) snap to their own grid,
    so an off-grid request is verified:false with the snapped value in after,
  * some params (band widths) ignore writes entirely -> verified:false with
    the attempts budget exhausted,
  * an open plugin window (pickup mode) did NOT block script writes in FL 26,
  * values are normalised 0..1 and the reply carries verified/attempts.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp.server import build_server  # noqa: E402

DEFAULT_WRITABLE = "Band 1 level:0.6,Band 3 level:0.55,Main level:0.66"
DEFAULT_REFUSED = "Band 5 width"


def unwrap(result):
    """Pull a plain value out of whatever call_tool returns across versions."""
    for attr in ("data", "structured_content", "structuredContent"):
        v = getattr(result, attr, None)
        if v is not None:
            return v
    if isinstance(result, tuple) and result:
        return unwrap(result[0]) if hasattr(result[0], "data") else result[0]
    return result


def parse_writes(spec):
    out = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, value = chunk.partition(":")
        out.append({"param": name.strip(), "value": float(value)})
    return out


def main() -> int:
    track = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    slot = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    writes = parse_writes(sys.argv[3] if len(sys.argv) > 3 else DEFAULT_WRITABLE)
    refused = (sys.argv[4] if len(sys.argv) > 4 else DEFAULT_REFUSED).strip()

    m = build_server()

    async def call(name, args):
        return unwrap(await m.call_tool(name, args))

    def vals():
        d = asyncio.run(call("fl_plugin_get_params", {"track": track, "slot": slot}))
        return {p["name"]: p["v"] for p in d.get("params", [])}

    fails = []

    def check(label, cond, extra=""):
        print(("PASS " if cond else "FAIL ") + label + ("  " + extra if extra else ""))
        if not cond:
            fails.append(label)

    base = vals()
    print("baseline:", {w["param"]: base.get(w["param"]) for w in writes})

    # 1. single write -> verified ------------------------------------------
    one = dict(writes[0])
    one["value"] = min(1.0, one["value"] + 0.12) if one["param"] in base else one["value"]
    r1 = asyncio.run(call("fl_plugin_set_param", {"track": track, "slot": slot, **one}))
    print(f"single: verified={r1.get('verified')} attempts={r1.get('attempts')}"
          f" after.v={(r1.get('after') or {}).get('v')}")
    check("single write verified", r1.get("verified") is True)
    check("single write attempts 1..4", 1 <= (r1.get("attempts") or 0) <= 4,
          str(r1.get("attempts")))
    check("before/after preserved (back-compat)",
          "before" in r1 and "after" in r1)

    # 2. optional negative case: a param FL silently ignores -----------------
    if refused and refused in base:
        r2 = asyncio.run(call("fl_plugin_set_param",
                              {"track": track, "slot": slot,
                               "param": refused, "value": 0.5}))
        print(f"refused: verified={r2.get('verified')} attempts={r2.get('attempts')}"
              f" hint={(r2.get('hint') or '')[:40]!r}")
        check("refused param -> verified False", r2.get("verified") is False)
        check("refused param -> attempts exhausted", r2.get("attempts") == 4,
              str(r2.get("attempts")))
        check("refused param -> hint present", bool(r2.get("hint")))
        check("refused param -> value unchanged",
              abs((r2.get("after") or {}).get("v", -1) - base[refused]) < 0.005)
    elif refused:
        print(f"skip negative case: {refused!r} not in this plugin's param list")

    # 3. batch -> one rollback unit -----------------------------------------
    r3 = asyncio.run(call("fl_plugin_set_params",
                          {"track": track, "slot": slot, "writes": writes}))
    print("batch:", [(it["param"]["name"], it["verified"], it["attempts"])
                     for it in r3.get("results", [])])
    check("batch ok", r3.get("ok") is True and r3.get("count") == len(writes),
          str(r3.get("count")))
    check("batch all verified",
          all(it["verified"] for it in r3.get("results", [])))
    check("batch hint absent when clean", "hint" not in r3)

    now = vals()
    for w in writes:
        check("readback {} == {}".format(w["param"], w["value"]),
              abs(now.get(w["param"], -1) - w["value"]) <= 0.02,
              str(now.get(w["param"])))

    # 4. roll back to baseline ----------------------------------------------
    labels = ["batch"]
    if refused and refused in base:
        labels.append("refused single")
    labels.append("first single")
    for label in labels:
        rb = asyncio.run(call("fl_rollback_last_change", {}))
        print("rollback ({}): {} | {}".format(label, rb.get("rolled_back"),
                                          rb.get("scope")))
        check(f"rollback popped {label}", bool(rb.get("rolled_back")))

    # The three restores above are issued back-to-back and FL commits plugin
    # writes on a later script tick (the same fact E-1's verify loop exists
    # for). Give it a beat before judging the final state.
    time.sleep(1.0)
    final = vals()
    drift = {k: (base[k], final[k]) for k in base
             if abs(final.get(k, 9e9) - base[k]) > 0.005}
    check("state restored to baseline", not drift, str(drift))

    status = "ALL PASS" if not fails else "FAILURES"
    print(f"\n{status} ({len(fails)} failed)")
    for f in fails:
        print("  -", f)
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:                       # noqa: BLE001
        print(f"E-1 live check could not run ({type(e).__name__}: {e})")
        sys.exit(2)
