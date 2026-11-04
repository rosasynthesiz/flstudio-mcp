#!/usr/bin/env python3
"""Compression Slice 2 test: limiter_curves unit tests + intents end-to-end.

Unit tests are pure. The intent tests build the real FastMCP server and call
the registered tools in-process on track 9 slot 4 (Drums Fruity Limiter), then
roll everything back and assert the COMP params return to their defaults.

    set FLSTUDIO_MCP_TRANSPORT=tcp
    python scripts/test_compression_intents.py [track] [slot]
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp.connection import get_bridge           # noqa: E402
from fl_studio_mcp.music import limiter_curves as lc      # noqa: E402
from fl_studio_mcp.server import build_server             # noqa: E402

TRACK = int(sys.argv[1]) if len(sys.argv) > 1 else 9
SLOT = int(sys.argv[2]) if len(sys.argv) > 2 else 4
_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1
    else:
        _F += 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def approx(a, b, tol):
    return a is not None and abs(a - b) <= tol


def unwrap(result):
    for attr in ("data", "structured_content", "structuredContent"):
        v = getattr(result, attr, None)
        if v is not None:
            return v
    return result


def _num(s):
    m = re.search(r"[-+]?\d*\.?\d+", str(s or ""))
    return float(m.group()) if m else None


def parse_ratio(s):
    """(X, downward): 'X:1'->(X,True), '1:X'->(X,False)."""
    t = str(s)
    if ":" not in t:
        return None, None
    a, _, b = t.partition(":")
    na, nb = _num(a), _num(b)
    if na is None or nb is None:
        return None, None
    if abs(nb - 1.0) < 0.05:
        return na, True
    if abs(na - 1.0) < 0.05:
        return nb, False
    return None, None


def unit_tests():
    print("[1] limiter_curves unit tests (pure)")
    check("ratio_to_norm(4) ~ 0.78", approx(lc.ratio_to_norm(4), 0.78, 0.02))
    check("ratio_to_norm(0.5) clamps to 0.5 (no expansion)", lc.ratio_to_norm(0.5) == 0.5)
    check("ratio_to_norm(2) > 0.5", lc.ratio_to_norm(2) > 0.5)
    check("ratio>1 always norm>0.5", all(lc.ratio_to_norm(r) > 0.5 for r in (1.1, 3, 6, 20)))
    check("norm_to_ratio(0.5) = 1.0", lc.norm_to_ratio(0.5) == 1.0)
    check("threshold_to_norm(-6) ~ 0.71", approx(lc.threshold_to_norm(-6), 0.71, 0.02))
    check("attack round-trip 50ms", approx(lc.norm_to_attack_ms(lc.attack_ms_to_norm(50)), 50, 2))
    check("release round-trip 200ms", approx(lc.norm_to_release_ms(lc.release_ms_to_norm(200)), 200, 5))
    check("knee 0% = norm 0.5", lc.knee_pct_to_norm(0) == 0.5 and lc.norm_to_knee_pct(0.5) == 0)
    check("makeup 0dB = norm 0.5", lc.makeup_db_to_norm(0) == 0.5)


def main() -> int:
    unit_tests()

    bridge = get_bridge()
    bridge.open()
    if not bridge.is_alive():
        print("\nBridge not alive -- FL open? controller loaded? daemon up (tcp)?")
        return 1

    m = build_server()

    def call(name, args):
        return unwrap(asyncio.run(m.call_tool(name, args)))

    def dump():
        return call("fl_plugin_get_params", {"track": TRACK, "slot": SLOT})

    pre = dump()
    print("\n[2] compression intents end-to-end (track %d slot %d)" % (TRACK, SLOT))

    # glue_drums(0.5) -> ~3:1, threshold lowered, attack/release set, makeup up ---
    r = call("fl_apply_compression_intent",
             {"track": TRACK, "slot": SLOT, "intent": "glue_drums", "intensity": 0.5})
    print("  glue_drums(0.5):", r.get("set"), "| readback:", r.get("readback"))
    rb = r.get("readback", {})
    x, down = parse_ratio(rb.get("Comp ratio"))
    check("glue ratio is X:1 (downward, not 1:X)", down is True, "ratio=%r" % rb.get("Comp ratio"))
    check("glue ratio ~3:1", approx(x, 3.0, 0.6), "X=%s" % x)
    check("glue threshold lowered (<-3dB)", (_num(rb.get("Comp threshold")) or 0) < -3, rb.get("Comp threshold"))
    check("glue attack ~30ms", approx(_num(rb.get("Comp attack time")), 30, 8), rb.get("Comp attack time"))
    check("glue makeup up (>0dB)", (_num(rb.get("Gain")) or 0) > 0, rb.get("Gain"))

    # heavy_vocal_compression(0.7) -> ratio ~6-7:1, threshold ~-12dB -------------
    r = call("fl_apply_compression_intent",
             {"track": TRACK, "slot": SLOT, "intent": "heavy_vocal_compression", "intensity": 0.7})
    print("  heavy_vocal(0.7):", r.get("set"), "| readback:", r.get("readback"))
    rb = r.get("readback", {})
    x, down = parse_ratio(rb.get("Comp ratio"))
    check("heavy ratio is X:1 (downward)", down is True, "ratio=%r" % rb.get("Comp ratio"))
    check("heavy ratio ~6-7:1", x is not None and 5.5 <= x <= 8.0, "X=%s" % x)
    check("heavy threshold ~-12dB", approx(_num(rb.get("Comp threshold")), -11.6, 1.5), rb.get("Comp threshold"))

    # rollback both -> defaults ---------------------------------------------------
    rb1 = call("fl_rollback_last_change", {}).get("rolled_back")
    rb2 = call("fl_rollback_last_change", {}).get("rolled_back")
    print("  rollbacks:", rb1, rb2)
    check("both reverted apply_compression_intent",
          rb1 == "apply_compression_intent" and rb2 == "apply_compression_intent")

    post = dump()
    pd = {p["name"]: p["s"] for p in post.get("params", [])}
    check("Comp ratio back to 1:1.0", pd.get("Comp ratio") == "1:1.0", pd.get("Comp ratio"))
    check("Comp threshold back to 0.0dB", pd.get("Comp threshold") == "0.0dB", pd.get("Comp threshold"))
    check("full Limiter dump restored to pre-state", post.get("params") == pre.get("params"))

    print("\n%d passed, %d failed" % (_P, _F))
    return 0 if _F == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
