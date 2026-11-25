#!/usr/bin/env python3
"""Refresh claude-plugin/fl_studio_mcp from src/fl_studio_mcp.

The Claude plugin is a self-contained folder, so it carries its own copy of the
server package. Run this after changing anything under src/fl_studio_mcp:

    python scripts/sync_claude_plugin.py          # copy
    python scripts/sync_claude_plugin.py --check  # exit 1 if the copy is stale

Left out of the copy: setup_cli.py (installer/doctor CLI, not needed by the
server; fl_ping has a built-in fallback) and caches.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "fl_studio_mcp"
DST = ROOT / "claude-plugin" / "fl_studio_mcp"
EXCLUDE_FILES = {"setup_cli.py"}
EXCLUDE_DIRS = {"__pycache__"}


def included_files(base: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base)
        if not p.is_file() or EXCLUDE_DIRS & set(rel.parts) or p.suffix == ".pyc":
            continue
        if rel.as_posix() in EXCLUDE_FILES:
            continue
        out[rel.as_posix()] = p
    return out


def drift() -> list[str]:
    """Human-readable differences between src and the vendored copy."""
    want, have = included_files(SRC), included_files(DST) if DST.is_dir() else {}
    problems = [f"missing in plugin: {r}" for r in want if r not in have]
    problems += [f"extra in plugin: {r}" for r in have if r not in want]
    problems += [f"differs: {r}" for r in want
                 if r in have and want[r].read_bytes() != have[r].read_bytes()]
    return problems


def sync() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    for rel, src in included_files(SRC).items():
        dst = DST / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def main(argv: list[str]) -> int:
    if "--check" in argv:
        problems = drift()
        for line in problems:
            print(line)
        return 1 if problems else 0
    sync()
    print(f"synced {len(included_files(DST))} files to {DST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
