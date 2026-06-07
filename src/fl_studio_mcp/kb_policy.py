"""Read-only helpers for source-qualified Knowledgebase policy rules.

This module deliberately exposes only small metadata helpers. It does not turn
Knowledgebase content into executable operations; writes still have to go
through the operation registry and safety layer.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

KB_ROOT = Path(__file__).resolve().parents[2] / "knowledgebase"

POLICY_FILES = (
    "mixing/mixing_fundamentals.json",
    "production/fl_studio_workflow_standards.json",
    "mastering/mastering_boundaries.json",
    "performance/fl_studio_cpu_optimization.json",
    "recipes/mix_doctor_fixes.json",
)


@lru_cache(maxsize=1)
def _rules_by_id() -> dict[str, dict[str, Any]]:
    rules: dict[str, dict[str, Any]] = {}
    for rel_path in POLICY_FILES:
        path = KB_ROOT / rel_path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rule in data.get("rules", []):
            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not rule_id:
                continue
            row = dict(rule)
            row.setdefault("confidence_level", data.get("confidence_level"))
            row["source_file"] = rel_path
            row["topic"] = data.get("topic")
            rules[rule_id] = row
    return rules


def get_rule(rule_id: str) -> dict[str, Any] | None:
    """Return a Knowledgebase policy rule by id, or None if it is unavailable."""
    rule = _rules_by_id().get(str(rule_id))
    return dict(rule) if rule else None


def rule_ref(rule_id: str) -> dict[str, Any]:
    """Compact, user-facing reference for a Knowledgebase rule."""
    rule = get_rule(rule_id)
    if rule is None:
        return {"id": str(rule_id), "available": False}
    return {
        "id": str(rule_id),
        "available": True,
        "domain": rule.get("domain"),
        "recommendation": rule.get("recommendation"),
        "confidence_level": rule.get("confidence_level"),
        "source_file": rule.get("source_file"),
    }


def rule_refs(rule_ids: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    """Compact refs for multiple rules, preserving order and dropping duplicates."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for rule_id in rule_ids:
        if rule_id in seen:
            continue
        seen.add(rule_id)
        out.append(rule_ref(rule_id))
    return out


def safety_limits(rule_ids: list[str] | tuple[str, ...]) -> list[str]:
    """Flatten unique safety limits from the requested policy rules."""
    out: list[str] = []
    seen: set[str] = set()
    for rule_id in rule_ids:
        rule = get_rule(rule_id)
        if not rule:
            continue
        for limit in rule.get("safety_limits") or []:
            text = str(limit)
            if text not in seen:
                seen.add(text)
                out.append(text)
    return out


def clear_cache() -> None:
    """Clear the policy cache. Intended for focused tests after KB edits."""
    _rules_by_id.cache_clear()
