"""Resolve the user's real Documents folder.

``~/Documents`` is wrong whenever Windows redirects Documents (OneDrive
backup, a localized folder name like ``OneDrive/Документы``, a moved library).
FL Studio itself records its user-data root in the registry, so prefer that,
then the shell's known-folder API, then the naive home path.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path


def _fl_shared_data() -> Path | None:
    """FL's 'Shared data' root, e.g. <Documents>/Image-Line (Windows only)."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Image-Line\Shared\Paths") as k:
            value, _ = winreg.QueryValueEx(k, "Shared data")
    except OSError:
        return None
    p = Path(value)
    return p if p.is_dir() else None


def _known_documents() -> Path | None:
    """FOLDERID_Documents via SHGetKnownFolderPath (Windows only)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = GUID(
            0xFDD39AD0, 0x238F, 0x46AF,
            (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
        )
        out = ctypes.c_wchar_p()
        try:
            hr = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(fid), 0, None, ctypes.byref(out))
            value = out.value if hr == 0 else None
        finally:
            # the caller owns the buffer, even when the call fails
            ctypes.windll.ole32.CoTaskMemFree(out)
        if not value:
            return None
        path = Path(value)
        return path if path.is_dir() else None
    except Exception:
        return None


@lru_cache(maxsize=1)
def documents_dir() -> Path:
    return _known_documents() or Path.home() / "Documents"


@lru_cache(maxsize=1)
def image_line_dir() -> Path:
    """<Documents>/Image-Line, honouring FL's own registry record first."""
    return _fl_shared_data() or documents_dir() / "Image-Line"
