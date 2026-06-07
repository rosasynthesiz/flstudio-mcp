#!/usr/bin/env python3
"""
Anti-Vibe Coding Audit
Enforces discipline by blocking lazy LLM coding patterns, ensuring the controller
sandbox isn't breached by filesystem/OS calls, and verifying Knowledgebase compliance.
"""

import ast
import json
import re
import sys
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGEBASE_DIR = ROOT_DIR / "knowledgebase"
CONTROLLER_DIR = ROOT_DIR / "fl_controller"
SRC_DIR = ROOT_DIR / "src"
SCRIPTS_DIR = ROOT_DIR / "scripts"

# ANSI Colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

errors = []


def report_error(filepath, line, violation_type, suggestion):
    errors.append(
        f"{RED}[VIBE CODING] {filepath}:{line}{RESET} - "
        f"{YELLOW}{violation_type}{RESET} -> {suggestion}"
    )


# --- 1. Knowledgebase Compliance ---
REQUIRED_KB_FIELDS = {
    "date",
    "topic",
    "context",
    "observation",
    "tested_values",
    "result",
    "confidence_level",
    "source_method",
    "open_questions",
    "next_recommended_action",
}
# author / agent_author and affected_api / affected_file_api are handled dynamically

ALLOWED_CONFIDENCE_LEVELS = {
    "hypothesis",
    "user_reported",
    "docs_confirmed",
    "measured_once",
    "measured_repeated",
    "implementation_verified",
    "cross_platform_verified",
    "deprecated_or_rejected",
}


def check_kb_schema():
    if not KNOWLEDGEBASE_DIR.exists():
        return

    for json_file in KNOWLEDGEBASE_DIR.rglob("*.json"):
        rel_path = json_file.relative_to(ROOT_DIR)
        if json_file.name.endswith(".schema.json"):
            continue
        if rel_path.parts[:3] == ("knowledgebase", "templates", "profiles"):
            continue
        if "calibration" in json_file.name or "mapping" in json_file.name:
            continue  # Calibration matrices and mappings are data, not reports

        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)

            entries = data if isinstance(data, list) else [data]

            for i, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    report_error(rel_path, 1, "Invalid KB Format", "Entry must be a JSON object.")
                    continue

                missing = REQUIRED_KB_FIELDS - set(entry.keys())
                if "author" not in entry and "agent_author" not in entry:
                    missing.add("author")
                if "affected_api" not in entry and "affected_file_api" not in entry:
                    missing.add("affected_api")

                if missing:
                    report_error(
                        rel_path,
                        1,
                        "Missing KB Fields",
                        "Entry {i}: Add missing keys: {missing} to comply with AGENTS.md".format(
                            i=i,
                            missing=", ".join(missing),
                        ),
                    )

                conf = entry.get("confidence_level")
                if conf and conf not in ALLOWED_CONFIDENCE_LEVELS:
                    report_error(
                        rel_path,
                        1,
                        "Invalid Confidence Level",
                        "Entry {i}: '{conf}' is not allowed. Must be one of: {levels}".format(
                            i=i,
                            conf=conf,
                            levels=", ".join(ALLOWED_CONFIDENCE_LEVELS),
                        ),
                    )

        except json.JSONDecodeError as e:
            report_error(rel_path, e.lineno, "Invalid JSON", "Fix JSON syntax errors.")


# --- 2. Controller Sandbox Compliance ---
FORBIDDEN_SANDBOX_MODULES = {"os", "sys", "subprocess", "io", "pathlib"}


class SandboxVisitor(ast.NodeVisitor):
    def __init__(self, rel_path):
        self.rel_path = rel_path

    def visit_Import(self, node):
        for alias in node.names:
            base_module = alias.name.split(".")[0]
            if base_module in FORBIDDEN_SANDBOX_MODULES:
                report_error(
                    self.rel_path,
                    node.lineno,
                    "Sandbox Violation (Import)",
                    f"Remove 'import {alias.name}'. FL Studio sandbox blocks "
                    "OS/filesystem calls. Do judgment on the Python server instead.",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            base_module = node.module.split(".")[0]
            if base_module in FORBIDDEN_SANDBOX_MODULES:
                report_error(
                    self.rel_path,
                    node.lineno,
                    "Sandbox Violation (ImportFrom)",
                    f"Remove 'from {node.module} import ...'. FL Studio sandbox blocks "
                    "OS/filesystem calls.",
                )
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            report_error(
                self.rel_path,
                node.lineno,
                "Sandbox Violation (open() call)",
                "Remove 'open()'. The FL controller cannot write files. "
                "Route data over SysEx and write it on the server.",
            )
        self.generic_visit(node)


def check_controller_sandbox():
    if not CONTROLLER_DIR.exists():
        return

    for py_file in CONTROLLER_DIR.rglob("*.py"):
        rel_path = py_file.relative_to(ROOT_DIR)
        try:
            with open(py_file, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))
            visitor = SandboxVisitor(rel_path)
            visitor.visit(tree)
        except SyntaxError as e:
            report_error(
                rel_path, e.lineno, "Syntax Error", "Fix Python syntax so AST can parse it."
            )


# --- 3. Vibe Keywords ---
VIBE_REGEX = re.compile(
    r"(TODO:\s*fix later|TODO\s*maybe|FIXME\s*later|HACK|quick hack|dirty fix|"
    r"placeholder implementation|stub implementation|untested|probably works|guessing|"
    r"print\(['\"]here\d*['\"]\)|print\(['\"]wtf['\"]\))",
    re.IGNORECASE,
)


def check_vibe_keywords():
    check_dirs = [SRC_DIR, CONTROLLER_DIR, SCRIPTS_DIR]

    for d in check_dirs:
        if not d.exists():
            continue
        for py_file in d.rglob("*.py"):
            # skip this script itself
            if py_file.name == "audit_anti_vibe.py":
                continue

            rel_path = py_file.relative_to(ROOT_DIR)
            with open(py_file, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    match = VIBE_REGEX.search(line)
                    if match:
                        report_error(
                            rel_path,
                            i,
                            f"Vibe Keyword Detected ('{match.group(1)}')",
                            "Remove lazy/unverified patterns. Write a proper implementation, "
                            "file a strict TODO with a real issue/roadmap reference, or "
                            "remove lazy print debugging.",
                        )


def main():
    print("Running Anti-Vibe Coding Audits...")

    check_kb_schema()
    check_controller_sandbox()
    check_vibe_keywords()

    if errors:
        print(f"\n{RED}❌ VIBE CODING DETECTED! {len(errors)} violation(s) found:{RESET}")
        for err in errors:
            print(err)
        print(f"\n{YELLOW}Please apply the suggested fixes and commit disciplined code.{RESET}")
        sys.exit(1)
    else:
        print(f"{GREEN}✅ No vibe coding detected. The codebase is disciplined.{RESET}")
        sys.exit(0)


if __name__ == "__main__":
    main()
