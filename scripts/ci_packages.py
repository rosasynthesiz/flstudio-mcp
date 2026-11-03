#!/usr/bin/env python3
"""Print the platform, Python and installed package versions.

    python scripts/ci_packages.py
"""
from __future__ import annotations

import platform
import sys
from importlib import metadata

PACKAGES = ["fl-studio-mcp", "fastmcp", "mcp", "pydantic", "mido", "python-rtmidi",
            "pyautogui", "librosa", "soundfile", "numpy", "scipy", "torch", "torchcrepe",
            "onnxruntime", "basic-pitch", "pretty-midi", "resampy", "scikit-learn", "setuptools"]


def main() -> int:
    print("%s, Python %s (%s)" % (platform.platform(), platform.python_version(), platform.machine()))
    for name in PACKAGES:
        try:
            version = metadata.version(name)
        except metadata.PackageNotFoundError:
            version = "not installed"
        print("  %-16s %s" % (name, version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
