"""Cross-platform discovery of FL Studio user-data locations.

FL Studio uses the SAME on-disk layout on Windows and macOS:

    <home>/Documents/Image-Line/FL Studio[ NNNN]/
        Settings/Hardware/FLStudioMCP/          # controller script
        Settings/Piano roll scripts/            # note-bridge pyscript
        Presets/Plugin database/Installed/       # scanned plugin shortcuts
        Presets/                                 # channel/mixer/plugin presets

so a single discovery routine serves every platform. Each lookup takes an
explicit env override first (so unusual installs always work), then the
standard path, then any versioned "FL Studio NNNN" folder, newest first.

Pure filesystem reads -- no FL, no bridge -- so this is easy to unit-test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

# Env overrides (each points directly at the target folder).
ENV_PIANO_ROLL_SCRIPTS = "FLSTUDIO_MCP_PIANO_ROLL_SCRIPTS"
ENV_FL_SETTINGS = "FLSTUDIO_MCP_FL_SETTINGS"


def fl_data_roots() -> Iterator[Path]:
    """Yield candidate FL Studio user-data roots, newest version first.

    Handles both the unversioned ``FL Studio`` folder and versioned
    ``FL Studio 2025`` style folders, under Documents/Image-Line (the standard
    on Windows and macOS) and a bare ~/Image-Line fallback.
    """
    home = Path.home()
    for base in (home / "Documents" / "Image-Line", home / "Image-Line"):
        if not base.is_dir():
            continue
        # exact "FL Studio" first, then versioned folders newest-first
        exact = base / "FL Studio"
        if exact.is_dir():
            yield exact
        for fl in sorted(base.glob("FL Studio *"), reverse=True):
            if fl.is_dir():
                yield fl


def find_fl_settings_dir() -> str | None:
    """Locate FL's ``Settings`` folder (env override wins). Returns a str path
    or None if not found."""
    env = os.environ.get(ENV_FL_SETTINGS)
    if env and os.path.isdir(env):
        return env
    for root in fl_data_roots():
        settings = root / "Settings"
        if settings.is_dir():
            return str(settings)
    return None


def find_piano_roll_scripts_dir() -> str:
    """Locate FL's ``Piano roll scripts`` folder.

    Order: env override -> discovered ``Settings/Piano roll scripts`` ->
    the standard path (returned even if absent, so callers can create it and
    fail loudly on write rather than silently pick the wrong place).
    """
    env = os.environ.get(ENV_PIANO_ROLL_SCRIPTS)
    if env:
        return env
    settings = find_fl_settings_dir()
    if settings:
        cand = Path(settings) / "Piano roll scripts"
        if cand.is_dir():
            return str(cand)
    standard = (Path.home() / "Documents" / "Image-Line" / "FL Studio"
                / "Settings" / "Piano roll scripts")
    # If a versioned root exists but the unversioned one doesn't, prefer it.
    if not standard.is_dir():
        for root in fl_data_roots():
            cand = root / "Settings" / "Piano roll scripts"
            return str(cand)
    return str(standard)
