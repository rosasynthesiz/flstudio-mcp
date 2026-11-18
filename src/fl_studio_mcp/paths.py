"""Locate the real Documents folder and FL Studio's user data folder.

Windows Documents may be redirected (OneDrive, localized names), and FL's user
data folder may be moved; FL stores that in the registry as "Shared data".
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

try:                         # Windows only
    import winreg
except ImportError:
    winreg = None

_MAX_PATH = 260
_CSIDL_PERSONAL = 5          # My Documents
_SHGFP_TYPE_CURRENT = 0


def documents_dir() -> Path:
    if sys.platform == "win32":
        try:
            buf = ctypes.create_unicode_buffer(_MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(
                    None, _CSIDL_PERSONAL, None, _SHGFP_TYPE_CURRENT, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Documents"


def _registry_user_data_dir() -> Path | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Image-Line\Shared\Paths") as key:
            value, _ = winreg.QueryValueEx(key, "Shared data")
    except OSError:
        return None
    p = Path(value) if value else None
    return p if p and p.is_dir() else None


def _macos_user_data_dir() -> Path | None:
    """macOS keeps FL's "Shared data" path in an XML registry file."""
    if sys.platform != "darwin":
        return None
    reg = Path.home() / "Library" / "Preferences" / "Image-Line" / "reg.xml"
    try:
        import xml.etree.ElementTree as ET
        for node in ET.parse(reg).iter("Value"):
            if node.get("Name") == "Shared data" and node.text:
                p = Path(node.text.strip())
                return p if p.is_dir() else None
    except Exception:
        return None
    return None


def image_line_dirs() -> list[Path]:
    """Candidate Image-Line user data roots, most authoritative first."""
    out: list[Path] = []
    for p in (_registry_user_data_dir(), _macos_user_data_dir(),
              documents_dir() / "Image-Line",
              Path.home() / "Documents" / "Image-Line", Path.home() / "Image-Line"):
        if p is not None and p not in out:
            out.append(p)
    return out


def fl_settings_dir() -> Path:
    """FL Studio's Settings folder (holds Hardware/ and Piano roll scripts/)."""
    override = os.environ.get("FL_SETTINGS")     # same override as the installer
    if override:
        return Path(override)
    for root in image_line_dirs():
        settings = root / "FL Studio" / "Settings"
        if settings.is_dir():
            return settings
    return documents_dir() / "Image-Line" / "FL Studio" / "Settings"


def bundled_controller() -> Path:
    """The controller script that ships with this server version."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "_controller" / "device_FLStudioMCP.py",          # wheel
                      here.parents[1] / "fl_controller" / "FLStudioMCP"
                      / "device_FLStudioMCP.py"):                               # checkout
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("The FL controller script is missing from this install.")


def installed_controller() -> Path:
    """Where FL Studio loads the controller script from."""
    return fl_settings_dir() / "Hardware" / "FLStudioMCP" / "device_FLStudioMCP.py"
