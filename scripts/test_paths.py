#!/usr/bin/env python3
"""Offline test: FL user data folder lookup (paths.py), with a fake FL folder.

    python scripts/test_paths.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import paths  # noqa: E402

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def main() -> int:
    os.environ.pop("FL_SETTINGS", None)
    docs = paths.documents_dir()
    check("documents_dir is absolute", docs.is_absolute(), str(docs))

    roots = paths.image_line_dirs()
    check("image_line_dirs has no duplicates", len(roots) == len(set(roots)))
    check("image_line_dirs includes <Documents>/Image-Line", docs / "Image-Line" in roots)

    # Registry setting (FL's moved user data folder) wins when it has Settings.
    fake = Path(tempfile.mkdtemp(prefix="flmcp_paths_"))
    (fake / "FL Studio" / "Settings").mkdir(parents=True)
    real_registry = paths._registry_user_data_dir
    paths._registry_user_data_dir = lambda: fake
    try:
        check("registry folder comes first", paths.image_line_dirs()[0] == fake)
        check("fl_settings_dir uses registry folder",
              paths.fl_settings_dir() == fake / "FL Studio" / "Settings",
              str(paths.fl_settings_dir()))
    finally:
        paths._registry_user_data_dir = real_registry

    # Nothing found anywhere: falls back to <Documents>/Image-Line/FL Studio/Settings.
    paths._registry_user_data_dir = lambda: None
    real_roots = paths.image_line_dirs
    paths.image_line_dirs = lambda: [fake / "missing"]
    try:
        check("fallback is <Documents>/Image-Line/FL Studio/Settings",
              paths.fl_settings_dir() == docs / "Image-Line" / "FL Studio" / "Settings")
    finally:
        paths._registry_user_data_dir = real_registry
        paths.image_line_dirs = real_roots

    os.environ["FL_SETTINGS"] = str(fake / "custom")
    try:
        check("FL_SETTINGS overrides everything", paths.fl_settings_dir() == fake / "custom")
    finally:
        del os.environ["FL_SETTINGS"]

    if sys.platform != "win32":
        check("no registry lookup off Windows", paths._registry_user_data_dir() is None)

    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
