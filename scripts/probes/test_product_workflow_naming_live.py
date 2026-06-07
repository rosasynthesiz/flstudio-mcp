#!/usr/bin/env python3
"""Live smoke for renamed product workflow tools.

This script verifies the API-breaking product workflow naming pass against a
live FL Studio session. It uses only current public names. Most checks are
read-only; the single write check nudges one non-Master mixer fader through
``fl_apply_mix_adjustment`` and immediately rolls it back.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("FLSTUDIO_MCP_TRANSPORT", "tcp")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fl_studio_mcp.server import build_server  # noqa: E402
from fl_studio_mcp.tools import (  # noqa: E402
    chains,
    mix_doctor,
    mixer,
    mixer_core,
    project_doctor,
    project_organizer,
    routing,
    transport,
)

NEW_TOOL_NAMES = {
    "fl_review_mix",
    "fl_review_low_end_stereo",
    "fl_apply_mix_adjustment",
    "fl_review_routing",
    "fl_plan_routing_cleanup",
    "fl_apply_routing_cleanup",
    "fl_apply_bus_layout",
    "fl_project_health_overview",
    "fl_check_project_preflight",
    "fl_start_guided_cleanup",
    "fl_get_guided_cleanup_context",
}

REMOVED_TOOL_NAMES = {
    "fl_diagnose_mix",
    "fl_apply_mix_fix",
    "fl_analyze_routing",
    "fl_plan_routing_fix",
    "fl_apply_routing_batch",
    "fl_create_bus_layout",
    "fl_project_health_dashboard",
    "fl_preflight_project",
    "fl_start_guided_fix_mode",
    "fl_get_guided_fix_context",
}


class MockMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, annotations=None):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def _public_tool_names() -> set[str]:
    return {tool.name for tool in asyncio.run(build_server().list_tools())}


def _register_tools() -> dict:
    mcp = MockMCP()
    transport.register(mcp)
    mixer.register(mcp)
    mixer_core.register(mcp)
    mix_doctor.register(mcp)
    routing.register(mcp)
    project_doctor.register(mcp)
    project_organizer.register(mcp)
    chains.register(mcp)
    return mcp.tools


def _summarize_result(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(item, (str, int, float, bool)) or item is None:
                out[key] = item
            elif isinstance(item, list):
                out[key] = f"list[{len(item)}]"
            elif isinstance(item, dict):
                out[key] = f"dict[{len(item)}]"
        return out
    return value


def _choose_volume_target(tracks: list[dict]) -> tuple[int, float] | None:
    candidates = [row for row in tracks if isinstance(row.get("i"), int) and row.get("i") > 0]
    preferred = [row for row in candidates if row.get("i") == 20]
    for row in preferred + candidates:
        vol_db = row.get("vol_db")
        if isinstance(vol_db, (int, float)) and math.isfinite(float(vol_db)):
            current = float(vol_db)
            target = current - 0.25 if current > -50.0 else current + 0.25
            return int(row["i"]), round(target, 2)
    return None


def main() -> int:
    tools = _register_tools()
    results: dict[str, object] = {
        "date": "2026-06-07",
        "transport": "tcp",
        "checks": [],
        "write_check": None,
    }

    public_names = _public_tool_names()
    missing_new = sorted(NEW_TOOL_NAMES - public_names)
    present_removed = sorted(REMOVED_TOOL_NAMES & public_names)
    if missing_new or present_removed:
        results["registration"] = {
            "missing_new": missing_new,
            "present_removed": present_removed,
            "registered_count": len(public_names),
        }
        print(json.dumps(results, indent=2, sort_keys=True))
        return 1

    ping = tools["fl_transport"]("ping")
    results["ping"] = ping
    build = ping.get("build")
    fl_version = ping.get("fl_version")
    print(f"FL: {fl_version} | controller={build}")
    if build != "channels-v39":
        results["error"] = f"unexpected controller build marker: {build!r}"
        print(json.dumps(results, indent=2, sort_keys=True))
        return 2

    tools["fl_transport"]("stop")

    read_only_calls = [
        ("fl_review_mix", lambda: tools["fl_review_mix"]()),
        ("fl_review_low_end_stereo", lambda: tools["fl_review_low_end_stereo"]()),
        ("fl_gain_stage", lambda: tools["fl_gain_stage"]()),
        ("fl_review_routing", lambda: tools["fl_review_routing"]()),
        ("fl_project_health_overview", lambda: tools["fl_project_health_overview"]()),
        ("fl_check_project_preflight", lambda: tools["fl_check_project_preflight"]()),
        ("fl_start_guided_cleanup", lambda: tools["fl_start_guided_cleanup"]()),
        ("fl_get_guided_cleanup_context", lambda: tools["fl_get_guided_cleanup_context"]()),
        ("fl_analyze_project_organization", lambda: tools["fl_analyze_project_organization"]()),
        ("fl_setup_chain", lambda: tools["fl_setup_chain"](20, "vocal")),
    ]
    ok = True
    for name, fn in read_only_calls:
        try:
            value = fn()
            results["checks"].append(
                {"tool": name, "ok": True, "summary": _summarize_result(value)}
            )
            print(f"[PASS] {name}")
        except Exception as exc:
            ok = False
            results["checks"].append(
                {"tool": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            )
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")

    mixer_state = tools["fl_mixer"]("list")
    tracks = mixer_state.get("tracks", []) if isinstance(mixer_state, dict) else []
    target = _choose_volume_target(tracks)
    if target is None:
        ok = False
        results["write_check"] = {"ok": False, "error": "no non-Master track with vol_db found"}
    else:
        track, target_db = target
        before = tools["fl_mixer"]("get", {"track": track})
        before_norm = before.get("vol_norm")
        try:
            applied = tools["fl_apply_mix_adjustment"](
                "trim_volume", track=track, target_db=target_db
            )
            after = tools["fl_mixer"]("get", {"track": track})
            rollback = tools["fl_rollback_last_change"]()
            restored = tools["fl_mixer"]("get", {"track": track})
            restored_norm = restored.get("vol_norm")
            restored_ok = (
                isinstance(before_norm, (int, float))
                and isinstance(restored_norm, (int, float))
                and abs(float(before_norm) - float(restored_norm)) <= 0.001
            )
            ok = ok and bool(applied.get("ok")) and bool(rollback.get("ok")) and restored_ok
            results["write_check"] = {
                "tool": "fl_apply_mix_adjustment",
                "track": track,
                "target_db": target_db,
                "before": {"vol_db": before.get("vol_db"), "vol_norm": before_norm},
                "after": {"vol_db": after.get("vol_db"), "vol_norm": after.get("vol_norm")},
                "rollback_ok": bool(rollback.get("ok")),
                "restored": {"vol_db": restored.get("vol_db"), "vol_norm": restored_norm},
                "restored_ok": restored_ok,
                "ok": bool(applied.get("ok")) and bool(rollback.get("ok")) and restored_ok,
            }
            print(
                f"[{'PASS' if results['write_check']['ok'] else 'FAIL'}] "
                f"fl_apply_mix_adjustment rollback on track {track}"
            )
        except Exception as exc:
            ok = False
            results["write_check"] = {
                "ok": False,
                "tool": "fl_apply_mix_adjustment",
                "track": track,
                "error": f"{type(exc).__name__}: {exc}",
            }
            print(f"[FAIL] fl_apply_mix_adjustment: {type(exc).__name__}: {exc}")
            try:
                rb = tools["fl_rollback_last_change"]()
                results["write_check"]["emergency_rollback"] = rb
            except Exception as rollback_exc:
                results["write_check"]["emergency_rollback_error"] = (
                    f"{type(rollback_exc).__name__}: {rollback_exc}"
                )

    tools["fl_transport"]("stop")
    results["completed_at_unix"] = time.time()
    results["ok"] = bool(ok)

    out_path = ROOT / "scratch" / "product_workflow_naming_live_2026_06_07.json"
    out_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
