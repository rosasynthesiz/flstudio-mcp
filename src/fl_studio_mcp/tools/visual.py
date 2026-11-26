"""Screenshot tool (E-3): visual debugging aid for the agent.

Captures FL Studio's window by default so the agent can SEE it (plugin
window, hint bar, focus) without receiving the user's whole display --
no FL writes, so the tool is read-only and bypasses safe_write.

- macOS: the window is located through CoreGraphics' CGWindowList via ctypes
  (stdlib, no pyobjc) and captured with `screencapture -x -o -l <CGWindowID>`.
  That takes the window's own content, so a window that is covered or on
  another Space is still captured correctly -- never someone else's window.
  pyautogui is only a fallback for whole-screen/region captures, and only if
  it happens to be importable (it is not a macOS dependency).
- Windows: the FL window is found with EnumWindows/GetWindowRect and
  captured with pyautogui (already a Windows dependency of this package).

`whole_screen=true` captures the whole display instead (explicit opt-in).
"""
from __future__ import annotations

import contextlib
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

_SHOTS_DIR = Path.home() / ".flstudio-mcp" / "shots"
_MAX_AGE_SECONDS = 7 * 24 * 3600


def _cleanup_old_shots(directory: Path) -> None:
    """Delete screenshots older than 7 days (best effort)."""
    if not directory.is_dir():
        return
    cutoff = time.time() - _MAX_AGE_SECONDS
    for shot in directory.glob("*.png"):
        try:
            if shot.stat().st_mtime < cutoff:
                shot.unlink()
        except OSError:
            pass


def _png_size(path: Path) -> tuple[int, int]:
    """(width, height) in image pixels from the PNG IHDR header."""
    head = path.read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError(f"not a PNG file: {path}")
    return struct.unpack(">II", head[16:24])


def _capture_screencapture(out: Path, region: list[int] | None,
                           window_id: int | None = None) -> None:
    cmd = ["screencapture", "-x"]
    if window_id is not None:
        cmd += ["-o", "-l", str(window_id)]
    elif region:
        cmd += ["-R", ",".join(str(v) for v in region)]
    cmd.append(str(out))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0:
        raise RuntimeError(f"screencapture exited {res.returncode}: "
                           f"{(res.stderr or res.stdout).strip()}")
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError("screencapture produced no file (macOS Screen "
                           "Recording permission missing?)")
    _png_size(out)  # verify it really is a PNG


def _capture_pyautogui(out: Path, region: list[int] | None) -> None:
    import pyautogui
    shot = pyautogui.screenshot(region=tuple(region) if region else None)
    shot.save(out, format="PNG")


def _cg_windows() -> list[dict]:
    """All window records (incl. other Spaces) from CoreGraphics via ctypes.

    Returns [{"id", "owner", "layer", "x", "y", "w", "h"}]. CoreFoundation
    refs are released; raising CFTypeRefs are read as UTF-8 strings / int64.
    """
    import ctypes
    from ctypes import byref, c_char_p, c_int, c_long, c_longlong, c_void_p

    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/"
                     "CoreFoundation")
    cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/"
                     "CoreGraphics")
    cf.CFArrayGetCount.argtypes = [c_void_p]
    cf.CFArrayGetCount.restype = c_long
    cf.CFArrayGetValueAtIndex.argtypes = [c_void_p, c_long]
    cf.CFArrayGetValueAtIndex.restype = c_void_p
    cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_int]
    cf.CFStringCreateWithCString.restype = c_void_p
    cf.CFDictionaryGetValue.argtypes = [c_void_p, c_void_p]
    cf.CFDictionaryGetValue.restype = c_void_p
    cf.CFNumberGetValue.argtypes = [c_void_p, c_int, c_void_p]
    cf.CFNumberGetValue.restype = c_int
    cf.CFStringGetCString.argtypes = [c_void_p, c_char_p, c_long, c_int]
    cf.CFStringGetCString.restype = c_int
    cf.CFRelease.argtypes = [c_void_p]
    cg.CGWindowListCopyWindowInfo.argtypes = [c_int, c_int]
    cg.CGWindowListCopyWindowInfo.restype = c_void_p

    utf8 = 0x08000100  # kCFStringEncodingUTF8
    keys = {name: cf.CFStringCreateWithCString(None, name.encode(), utf8)
            for name in ("kCGWindowNumber", "kCGWindowOwnerName",
                         "kCGWindowLayer", "kCGWindowBounds")}
    bounds_keys = {name: cf.CFStringCreateWithCString(None, name.encode(), utf8)
                   for name in ("X", "Y", "Width", "Height")}

    def number(ref) -> int:
        value = c_longlong(0)
        cf.CFNumberGetValue(ref, 4, byref(value))  # kCFNumberSInt64Type
        return value.value

    def text(ref) -> str:
        buf = ctypes.create_string_buffer(1024)
        if cf.CFStringGetCString(ref, buf, 1024, utf8):
            return buf.value.decode("utf-8", "replace")
        return ""

    # kCGWindowListOptionAll: a window on another Space is still FL's window
    # and `screencapture -l` captures it; "on-screen only" would miss it.
    array = cg.CGWindowListCopyWindowInfo(0, 0)
    windows: list[dict] = []
    try:
        for index in range(cf.CFArrayGetCount(array)):
            entry = cf.CFArrayGetValueAtIndex(array, index)
            bounds = cf.CFDictionaryGetValue(entry, keys["kCGWindowBounds"])
            rect = {name: number(cf.CFDictionaryGetValue(bounds, ref))
                    for name, ref in bounds_keys.items()}
            windows.append({
                "id": number(cf.CFDictionaryGetValue(
                    entry, keys["kCGWindowNumber"])),
                "owner": text(cf.CFDictionaryGetValue(
                    entry, keys["kCGWindowOwnerName"])),
                "layer": number(cf.CFDictionaryGetValue(
                    entry, keys["kCGWindowLayer"])),
                "x": rect["X"], "y": rect["Y"],
                "w": rect["Width"], "h": rect["Height"],
            })
    finally:
        cf.CFRelease(array)
        for ref in list(keys.values()) + list(bounds_keys.values()):
            cf.CFRelease(ref)
    return windows


def _mac_fl_window() -> dict | None:
    """FL Studio's main window {"id", x, y, w, h} (points), or None.

    Picks the largest layer-0 window owned by FL Studio; the small 38 px
    helper windows the app also owns are filtered out by area.
    """
    try:
        candidates = [w for w in _cg_windows()
                      if w["layer"] == 0 and w["w"] > 0 and w["h"] > 0
                      and w["owner"].startswith("FL Studio")]
    except (OSError, AttributeError, ValueError):
        return None
    if not candidates:
        return None
    best = max(candidates, key=lambda w: w["w"] * w["h"])
    return {"id": best["id"], "x": best["x"], "y": best["y"],
            "w": best["w"], "h": best["h"]}


def _win_fl_window() -> dict | None:
    """FL Studio's main window {"id", x, y, w, h} in pixels, or None.

    Found by FL's own window class (the same lookup pyscript_trigger uses),
    not by title, so a browser tab or folder named "FL Studio" is never
    captured by mistake.
    """
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW("TFruityLoopsMainForm", None)
        if not hwnd or not user32.IsWindowVisible(hwnd):
            return None
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None
        return {"id": int(hwnd), "x": rect.left, "y": rect.top,
                "w": width, "h": height}
    except Exception:  # noqa: BLE001 -- window lookup is best-effort
        return None


def _find_fl_window() -> list[int] | None:
    """FL Studio's window rect in the capture space, or None when unknown."""
    if sys.platform == "darwin":
        return _mac_fl_window()
    if sys.platform == "win32":
        return _win_fl_window()
    return None


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": False, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Screenshot (agent debugging)", **_RO})
    def fl_screenshot(
        path: Annotated[str | None,
                        Field(description="File NAME or full path inside "
                              "~/.flstudio-mcp/shots/ (nothing outside is "
                              "accepted, existing files are never "
                              "overwritten); omit for a timestamped "
                              "default.")] = None,
        region: Annotated[list[int] | None,
                          Field(description="Absolute crop [x, y, w, h] in "
                                "LOGICAL points (pyautogui space), e.g. "
                                "[100, 100, 800, 600]. Overrides the default "
                                "window capture.")] = None,
        whole_screen: Annotated[bool,
                                Field(description="Capture the whole display "
                                      "instead of the FL Studio window. Off by "
                                      "default so the assistant does not "
                                      "receive unrelated windows.")] = False,
    ) -> dict:
        """Capture FL Studio's window to a PNG -- for AGENT DEBUGGING (see
        the plugin window, the hint bar, focus), not part of the music
        workflow. Only that window is captured by default; set
        whole_screen=True to capture the entire display, or region=[x,y,w,h]
        for an explicit crop.

        Returns {ok, target, path, size, width, height}; Read the path to view
        it. target is "window", "screen" or "region". Files go to
        ~/.flstudio-mcp/shots/<timestamp>.png and are cleaned up after 7 days.
        path= accepts only a name or path INSIDE that shots directory (it is
        resolved and bound there -- the tool never writes elsewhere) and never
        overwrites an existing file.

        Coordinates: region is in LOGICAL points -- the space pyautogui
        clicks in, NOT image pixels. A retina PNG is 2x bigger than the
        logical screen (E-0 Q5 measured: logical 1710x1107 -> PNG 3420x2214,
        factor exactly 2.0 on this display). To convert screenshot pixels to
        click coordinates: logical = px / (png_width / logical_screen_width)
        -- measure that ratio per display (pyautogui.size() vs the returned
        width), never hardcode 2.0. width/height here are PNG pixels."""
        if sys.platform not in ("darwin", "win32"):
            return {"ok": False,
                    "error": f"fl_screenshot supports macOS and Windows "
                             f"(sys.platform={sys.platform}); use your OS's "
                             f"screenshot tool instead."}
        if region is not None and (len(region) != 4
                                   or region[2] <= 0 or region[3] <= 0
                                   or region[0] < 0 or region[1] < 0):
            return {"ok": False,
                    "error": f"region must be [x, y, w, h] with x,y >= 0 and "
                             f"w,h > 0 (logical points); got {region!r}"}
        try:
            _SHOTS_DIR.mkdir(parents=True, exist_ok=True)
            _cleanup_old_shots(_SHOTS_DIR)
            if path is None:
                from datetime import datetime
                out = _SHOTS_DIR / (datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                                    + ".png")
            else:
                if not str(path).lower().endswith(".png"):
                    return {"ok": False,
                            "error": f"path must end in .png "
                                     f"(the format is picked by extension): {path}"}
                p = Path(path).expanduser()
                out = (p if p.is_absolute() else _SHOTS_DIR / p).resolve()
                shots = _SHOTS_DIR.resolve()
                try:
                    out.relative_to(shots)
                except ValueError:
                    return {"ok": False,
                            "error": f"path must stay inside {shots} -- the "
                                     f"tool never writes elsewhere (got "
                                     f"{path!r} -> {out})"}
            if out.exists():
                return {"ok": False,
                        "error": f"file already exists, refusing to overwrite: "
                                 f"{out}"}
            if region is not None:
                target, crop, window_id = "region", region, None
            elif whole_screen:
                target, crop, window_id = "screen", None, None
            else:
                window = _find_fl_window()
                if window is None:
                    return {"ok": False,
                            "error": "FL Studio's window was not found; set "
                                     "whole_screen=true to capture the display, "
                                     "or region=[x, y, w, h] for a crop.",
                            "hint": "Is FL Studio open? On an empty project it "
                                    "still has a window; if it is hidden, bring "
                                    "it back. (The display itself is only "
                                    "captured when you ask for it.)"}
                target, window_id = "window", window.get("id")
                crop = [window["x"], window["y"], window["w"], window["h"]]
            attempts = []
            if sys.platform == "darwin":
                attempts.append(lambda: _capture_screencapture(out, crop,
                                                               window_id))
                if window_id is None:
                    attempts.append(lambda: _capture_pyautogui(out, crop))
            else:
                attempts.append(lambda: _capture_pyautogui(out, crop))
            errors = []
            for attempt in attempts:
                try:
                    attempt()
                    break
                except Exception as exc:  # noqa: BLE001 -- fall through to next
                    errors.append(f"capture: {type(exc).__name__}: {exc}")
            else:
                with contextlib.suppress(OSError):
                    out.unlink(missing_ok=True)  # no empty leftover
                hint = ("macOS: System Settings > Privacy & Security > "
                        "Screen Recording -- enable the app running the MCP "
                        "server, then retry.") if sys.platform == "darwin" else \
                       ("Windows: pyautogui/Pillow must be importable; "
                        "re-run the installer or `pip install pyautogui`.")
                return {"ok": False, "error": "; ".join(errors), "hint": hint}
            width, height = _png_size(out)
            return {"ok": True, "target": target, "path": str(out),
                    "size": out.stat().st_size,
                    "width": width, "height": height,
                    "region": crop if target != "screen" else None}
        except Exception as exc:  # noqa: BLE001 -- soft-fail per DoD
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
