#!/usr/bin/env python3
"""Offline tests for the Knowledgebase policy helper."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import kb_policy  # noqa: E402

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    if cond:
        _P += 1
    else:
        _F += 1
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{'  -- ' + detail if detail else ''}")


def main() -> int:
    kb_policy.clear_cache()

    master = kb_policy.rule_ref("master_peak_boundary")
    check("loads mixing policy rule", master.get("available") is True, str(master))
    check(
        "rule ref includes source file",
        master.get("source_file") == "mixing/mixing_fundamentals.json",
        str(master),
    )

    mix = kb_policy.rule_ref("mix_doctor_insert_headroom_context")
    check("loads Mix Review recipe rule", mix.get("available") is True, str(mix))

    limits = kb_policy.safety_limits(["mix_doctor_existing_plugin_only"])
    check(
        "loads safety limits",
        any("Do not load missing plugins" in item for item in limits),
        str(limits),
    )

    missing = kb_policy.rule_ref("does_not_exist")
    check(
        "missing rule is explicit",
        missing == {"id": "does_not_exist", "available": False},
        str(missing),
    )

    print(f"\nKB policy tests: {_P} passed, {_F} failed.")
    return 1 if _F else 0


def test_policy_loader_smoke() -> None:
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
