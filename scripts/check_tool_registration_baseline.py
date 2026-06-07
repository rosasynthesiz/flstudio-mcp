#!/usr/bin/env python3
"""Report and lock the current FastMCP public tool registration baseline."""

from __future__ import annotations

import ast
import asyncio
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audit_tool_safety import TOOLS_DIR, audit_file, count_by_status  # noqa: E402
from fastmcp import FastMCP  # noqa: E402

from fl_studio_mcp import __version__  # noqa: E402
from fl_studio_mcp import server as server_module  # noqa: E402

EXPECTED_REGISTERED_TOOL_COUNT = 87
EXPECTED_STATIC_TOOL_COUNT = 166
EXPECTED_REGISTERED_SAFETY_SUMMARY = {
    "external-write": 2,
    "read-only": 41,
    "server-state": 4,
    "unannotated": 7,
    "write-safe": 33,
}
EXPECTED_STATIC_SAFETY_SUMMARY = {
    "external-write": 2,
    "read-only": 71,
    "server-state": 4,
    "transient": 5,
    "write-gap": 0,
    "write-safe": 84,
}


@dataclass(frozen=True)
class RegistrationCall:
    alias: str
    line: int


def _build_server_function() -> ast.FunctionDef:
    server_path = ROOT / "src" / "fl_studio_mcp" / "server.py"
    tree = ast.parse(server_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_server":
            return node
    raise RuntimeError("build_server() not found in server.py")


def _registration_calls() -> list[RegistrationCall]:
    calls: list[RegistrationCall] = []
    for node in _build_server_function().body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "register"
            and isinstance(func.value, ast.Name)
        ):
            continue
        if not call.args or not isinstance(call.args[0], ast.Name) or call.args[0].id != "mcp":
            continue
        calls.append(RegistrationCall(alias=func.value.id, line=node.lineno))
    return calls


def _new_server() -> FastMCP:
    return FastMCP(
        name="fl-studio-mcp",
        version=__version__,
        instructions=server_module.SERVER_INSTRUCTIONS,
    )


def _build_from_calls(
    calls: list[RegistrationCall], *, skip_repeated_aliases: bool = False
) -> tuple[FastMCP, list[RegistrationCall]]:
    mcp = _new_server()
    seen: set[str] = set()
    skipped: list[RegistrationCall] = []
    for call in calls:
        if skip_repeated_aliases and call.alias in seen:
            skipped.append(call)
            continue
        getattr(server_module, call.alias).register(mcp)
        seen.add(call.alias)
    return mcp, skipped


async def _list_tools(mcp: FastMCP) -> list:
    return list(await mcp.list_tools())


def _static_audits():
    audits = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        if path.name != "__init__.py":
            audits.extend(audit_file(path))
    return audits


def _safety_class(tool) -> str:
    annotations = getattr(tool, "annotations", None)
    safety_class = getattr(annotations, "safetyClass", None)
    return str(safety_class or "unannotated")


def _print_summary(title: str, counts: dict[str, int]) -> None:
    print(title)
    for key in sorted(counts):
        print(f"- {key}: {counts[key]}")


def main() -> int:
    logging.getLogger("fastmcp").setLevel(logging.ERROR)

    calls = _registration_calls()
    repeated_aliases = {
        alias: [call.line for call in calls if call.alias == alias]
        for alias, count in Counter(call.alias for call in calls).items()
        if count > 1
    }

    registered_mcp = server_module.build_server()
    registered_tools = asyncio.run(_list_tools(registered_mcp))
    registered_names = [tool.name for tool in registered_tools]
    registered_name_set = set(registered_names)
    duplicate_public_names = sorted(
        name for name, count in Counter(registered_names).items() if count > 1
    )
    registered_summary = dict(Counter(_safety_class(tool) for tool in registered_tools))

    if repeated_aliases:
        deduped_mcp, skipped = _build_from_calls(calls, skip_repeated_aliases=True)
        deduped_names = {tool.name for tool in asyncio.run(_list_tools(deduped_mcp))}
    else:
        skipped = []
        deduped_names = registered_name_set

    static_audits = _static_audits()
    static_names = {audit.name for audit in static_audits}
    static_summary = {"write-gap": 0, **count_by_status(static_audits)}
    registered_not_static = sorted(registered_name_set - static_names)
    static_not_registered = sorted(static_names - registered_name_set)
    expected_static_not_registered = sorted(
        getattr(server_module, "_LEGACY_LOW_LEVEL_TOOLS", set()) & static_names
    )

    print("Tool registration baseline")
    print(f"- registered_public_tools: {len(registered_tools)}")
    print(f"- unique_public_tool_names: {len(registered_name_set)}")
    print(f"- duplicate_public_tool_names: {len(duplicate_public_names)}")
    print(f"- static_audited_tools: {len(static_audits)}")
    print(f"- registered_without_static_audit: {len(registered_not_static)}")
    print(f"- static_not_registered: {len(static_not_registered)}")
    print()
    _print_summary("Registered safety classes", registered_summary)
    print()
    _print_summary("Static safety audit classes", static_summary)
    print()
    print("Duplicate registration check")
    if repeated_aliases:
        for alias, lines in repeated_aliases.items():
            print(f"- repeated module registration: {alias} at lines {lines}")
    else:
        print("- repeated module registration: none")
    skipped_summary = [(call.alias, call.line) for call in skipped]
    print(f"- skipped repeated calls for comparison: {skipped_summary}")
    print(f"- normal_public_tool_count: {len(registered_tools)}")
    print(f"- without_repeated_module_aliases_count: {len(deduped_names)}")
    print(f"- name_sets_identical: {registered_name_set == deduped_names}")
    print()
    if registered_not_static:
        print("Registered tools without static AST safety audit")
        for name in registered_not_static:
            print(f"- {name}")
        print()
    if static_not_registered:
        print("Static audited tools retired from public registration")
        for name in static_not_registered:
            print(f"- {name}")
        print()

    checks = {
        "registered tool count matches baseline": len(registered_tools)
        == EXPECTED_REGISTERED_TOOL_COUNT,
        "no duplicate public tool names": not duplicate_public_names,
        "static tool count matches baseline": len(static_audits) == EXPECTED_STATIC_TOOL_COUNT,
        "registered safety summary matches baseline": registered_summary
        == EXPECTED_REGISTERED_SAFETY_SUMMARY,
        "static safety summary matches baseline": static_summary == EXPECTED_STATIC_SAFETY_SUMMARY,
        "only approved legacy aliases are absent from public registration": static_not_registered
        == expected_static_not_registered,
        "duplicate module registration does not affect public names": registered_name_set
        == deduped_names,
    }
    failed = [name for name, ok in checks.items() if not ok]
    print("Checks")
    for name, ok in checks.items():
        print(f"- {'PASS' if ok else 'FAIL'}: {name}")
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
