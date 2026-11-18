"""Screenshot tool (E-3): visual debugging aid for the agent.

Captures the screen so the agent can SEE FL (plugin window, hint bar,
focus) -- no FL writes, so the tool is read-only and bypasses safe_write.
macOS path is `screencapture -x` (fast, no focus stealing; E-0 Q5: 0.18 s
vs pyautogui's 0.27 s), falling back to `pyautogui.screenshot()`.
Windows uses pyautogui (already a Windows dependency of this package).
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


def _capture_screencapture(out: Path, region: list[int] | None) -> None:
    cmd = ["screencapture", "-x"]
    if region:
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
                          Field(description="Crop [x, y, w, h] in LOGICAL "
                                "points (pyautogui space), e.g. "
                                "[100, 100, 800, 600].")] = None,
    ) -> dict:
        """Capture the screen to a PNG -- for AGENT DEBUGGING (see the FL
        window, a plugin, the hint bar), not part of the music workflow.

        Returns {ok, path, size, width, height}; Read the path to view it.
        Files go to ~/.flstudio-mcp/shots/<timestamp>.png and are cleaned up
        after 7 days. path= accepts only a name or path INSIDE that shots
        directory (it is resolved and bound there -- the tool never writes
        elsewhere) and never overwrites an existing file.

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
            captures = (_capture_screencapture, _capture_pyautogui) \
                if sys.platform == "darwin" else (_capture_pyautogui,)
            errors = []
            for capture in captures:
                try:
                    capture(out, region)
                    break
                except Exception as exc:  # noqa: BLE001 -- fall through to next
                    errors.append(f"{capture.__name__}: "
                                  f"{type(exc).__name__}: {exc}")
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
            return {"ok": True, "path": str(out), "size": out.stat().st_size,
                    "width": width, "height": height,
                    "region": region or None}
        except Exception as exc:  # noqa: BLE001 -- soft-fail per DoD
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
