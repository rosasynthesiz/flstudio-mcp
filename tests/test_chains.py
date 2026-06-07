#!/usr/bin/env python3
"""Offline test: chains.plan_chain recipe -> existing-plugin matching (no FL).

python scripts/test_chains.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol  # noqa: E402
from fl_studio_mcp.music import chains as ch  # noqa: E402
from fl_studio_mcp.tools import chains as chain_tools  # noqa: E402

_P = _F = 0


class MockMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, annotations=None):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class FakeBridge:
    def __init__(self, slots):
        self._slots = list(slots)
        self.calls = []

    def call(self, command, params=None):
        params = params or {}
        self.calls.append((command, params))
        if command == protocol.CMD_PLUGIN_LIST:
            return {"slots": list(self._slots)}
        raise AssertionError(f"unexpected command: {command!r} params={params!r}")


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{'  -- ' + detail if detail else ''}")


def _ref_ids(result):
    return {row.get("id") for row in result.get("kb_policy_refs", [])}


def main() -> int:
    eq = {"slot": 0, "name": "Fruity Parametric EQ 2"}
    comp = {"slot": 1, "name": "FabFilter Pro-C 3"}

    # vocal with EQ + comp but NO reverb -> reverb step missing.
    plan = ch.plan_chain("vocal", [eq, comp])
    roles = [s["role"] for s in plan["steps"]]
    miss = [m["role"] for m in plan["missing"]]
    check(
        "vocal: EQ steps -> EQ slot 0",
        all(s["slot"] == 0 for s in plan["steps"] if s["kind"] == "eq"),
    )
    check(
        "vocal: comp -> comp slot 1",
        any(s["kind"] == "comp" and s["slot"] == 1 for s in plan["steps"]),
    )
    check("vocal: reverb step MISSING (no reverb loaded)", "space" in miss, str(miss))
    check(
        "vocal: HP/presence/air present",
        {"high-pass", "presence", "air"}.issubset(set(roles)),
        str(roles),
    )
    check(
        "steps carry valid tool + intent",
        all(s["tool"].startswith("fl_apply_") and s["intent"] for s in plan["steps"]),
    )

    bad = ch.plan_chain("nonsense", [eq])
    check(
        "unknown chain_type -> ok False + available list",
        bad["ok"] is False and "vocal" in bad.get("available", []),
    )

    empty = ch.plan_chain("drum_bus", [])
    check(
        "no plugins -> 0 steps, all missing",
        len(empty["steps"]) == 0 and len(empty["missing"]) == 3,
        str(empty["missing"]),
    )

    check("describe() lists all recipes", set(ch.describe()) == set(ch.available()))

    # Tool-level contract: chain setup is a read-only plan over already-loaded plugins.
    mcp = MockMCP()
    chain_tools.register(mcp)
    bridge = FakeBridge(
        [
            {"slot": 0, "name": "Fruity Parametric EQ 2"},
            {"slot": 1, "name": "Fruity Limiter"},
        ]
    )
    original_get_bridge = chain_tools.get_bridge
    original_list_installed = chain_tools.pl.list_installed
    try:
        chain_tools.get_bridge = lambda: bridge
        chain_tools.pl.list_installed = lambda: {
            "found": True,
            "path": "/tmp/fake-fl-plugin-db",
            "counts": {"effects": 2, "generators": 0},
            "effects": ["Fruity Parametric EQ 2", "Fruity Limiter"],
            "generators": [],
        }
        master_plan = mcp.tools["fl_setup_chain"](track=7, chain_type="master")
    finally:
        chain_tools.get_bridge = original_get_bridge
        chain_tools.pl.list_installed = original_list_installed

    refs = _ref_ids(master_plan)
    check("fl_setup_chain returns ok for master plan", master_plan.get("ok") is True)
    check(
        "master plan exposes loaded-plugin and mastering KB refs",
        {
            "mix_doctor_existing_plugin_only",
            "mastering_after_mix_readiness",
            "maximus_loaded_plugin_only",
        }.issubset(refs),
        str(refs),
    )
    check(
        "master plan configures only existing intent tools",
        all(
            step.get("apply", {}).get("tool", "").startswith("fl_apply_")
            and "load" not in step.get("apply", {}).get("tool", "").lower()
            for step in master_plan.get("configure_now", [])
        ),
        str(master_plan.get("configure_now")),
    )
    check(
        "master plan guidance keeps plugin loading and rendering manual",
        "FL can't load plugins" in master_plan.get("guidance", "")
        and "rendering/export/manual mastering outside MCP automation"
        in master_plan.get("guidance", ""),
    )

    print("\n%d passed, %d failed" % (_P, _F))
    return 0 if _F == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
