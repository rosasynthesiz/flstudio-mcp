"""fl_screenshot (E-3): path binding, overwrite guard, region and fallback."""
import base64
import os
import sys
import time

import pytest
from fastmcp import Client

from fl_studio_mcp.server import build_server
from fl_studio_mcp.tools import visual

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
    "DwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture
def shots(monkeypatch, tmp_path):
    """Point the tool at a temp shots dir and simulate a capture device."""
    monkeypatch.setattr(visual, "_SHOTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def capture(out, region, window_id=None):
        calls.append((out, region, window_id))
        out.write_bytes(PNG_1PX)

    monkeypatch.setattr(visual, "_capture_screencapture", capture)
    monkeypatch.setattr(visual, "_capture_pyautogui", capture)
    window = {"id": 57922, "x": 12, "y": 34, "w": 800, "h": 600}
    monkeypatch.setattr(visual, "_find_fl_window", lambda: window)
    return {"dir": tmp_path, "calls": calls, "window": window,
            "window_rect": [12, 34, 800, 600]}


async def _call(arguments):
    async with Client(build_server()) as client:
        return (await client.call_tool("fl_screenshot", arguments)).data


@pytest.mark.asyncio
async def test_default_path_is_timestamped_png_in_shots(shots):
    result = await _call({})
    assert result["ok"] is True, result
    path = visual.Path(result["path"])
    assert path.parent == shots["dir"] and path.suffix == ".png"
    assert path.read_bytes() == PNG_1PX
    assert (result["width"], result["height"]) == (1, 1)


@pytest.mark.asyncio
async def test_region_and_named_path(shots):
    result = await _call({"path": "crop.png", "region": [10, 20, 300, 200]})
    assert result["ok"] is True, result
    assert result["path"] == str(shots["dir"] / "crop.png")
    assert result["target"] == "region"
    assert result["region"] == [10, 20, 300, 200]
    assert shots["calls"][0][1] == [10, 20, 300, 200]


@pytest.mark.asyncio
async def test_default_captures_the_fl_window_not_the_screen(shots):
    result = await _call({})
    assert result["ok"] is True, result
    assert result["target"] == "window"
    assert result["region"] == shots["window_rect"]
    assert shots["calls"][0][1] == shots["window_rect"]
    assert shots["calls"][0][2] == 57922


@pytest.mark.asyncio
async def test_whole_screen_is_an_explicit_opt_in(shots):
    result = await _call({"whole_screen": True})
    assert result["ok"] is True, result
    assert result["target"] == "screen"
    assert result["region"] is None
    assert shots["calls"][0][1:] == (None, None)


@pytest.mark.asyncio
async def test_missing_fl_window_asks_for_whole_screen_or_region(shots, monkeypatch):
    monkeypatch.setattr(visual, "_find_fl_window", lambda: None)
    result = await _call({})
    assert result["ok"] is False
    assert "whole_screen=true" in result["error"]
    assert not shots["calls"]
    assert list(shots["dir"].glob("*.png")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"region": [1, 2, 3]},
    {"region": [-1, 0, 10, 10]},
    {"region": [0, 0, 0, 10]},
])
async def test_region_must_be_four_positive_logical_values(shots, bad):
    result = await _call(bad)
    assert result["ok"] is False and "region" in result["error"]
    assert not shots["calls"]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../escape.png", "../../tmp/x.png",
                                  "/etc/cwd_probe.png"])
async def test_path_must_stay_inside_shots(shots, path):
    result = await _call({"path": path})
    assert result["ok"] is False and "inside" in result["error"]
    assert not shots["calls"]
    assert not (shots["dir"].parent / "escape.png").exists()


@pytest.mark.asyncio
async def test_existing_file_is_never_overwritten(shots):
    canary = shots["dir"] / "canary.png"
    canary.write_bytes(b"keep")
    result = await _call({"path": "canary.png"})
    assert result["ok"] is False and "overwrite" in result["error"]
    assert canary.read_bytes() == b"keep"


@pytest.mark.asyncio
async def test_only_png_extension(shots):
    result = await _call({"path": "shot.jpg"})
    assert result["ok"] is False and ".png" in result["error"]
    assert not shots["calls"]


@pytest.mark.asyncio
async def test_capture_failure_is_soft_with_a_hint(shots, monkeypatch):
    def boom(out, region, window_id=None):
        raise RuntimeError("no permission")

    monkeypatch.setattr(visual, "_capture_screencapture", boom)
    monkeypatch.setattr(visual, "_capture_pyautogui", boom)
    result = await _call({})
    assert result["ok"] is False and "no permission" in result["error"]
    assert "Screen Recording" in result["hint"]
    assert list(shots["dir"].glob("*.png")) == []


@pytest.mark.asyncio
async def test_window_capture_never_falls_back_to_a_screen_rect(shots, monkeypatch):
    """If -l fails, a rect capture could catch whatever covers that area."""
    seen = []

    def fail(out, region, window_id=None):
        seen.append(window_id)
        raise RuntimeError("window capture failed")

    def pyautogui_should_not_run(out, region):
        raise AssertionError("pyautogui rect fallback must not run for windows")

    monkeypatch.setattr(visual, "_capture_screencapture", fail)
    monkeypatch.setattr(visual, "_capture_pyautogui", pyautogui_should_not_run)
    result = await _call({})
    assert result["ok"] is False
    assert seen == [57922]
    assert list(shots["dir"].glob("*.png")) == []


@pytest.mark.asyncio
async def test_mac_whole_screen_still_has_a_pyautogui_fallback(shots, monkeypatch):
    def fail(out, region, window_id=None):
        raise RuntimeError("screencapture broke")

    def ok(out, region):
        out.write_bytes(PNG_1PX)

    monkeypatch.setattr(visual, "_capture_screencapture", fail)
    monkeypatch.setattr(visual, "_capture_pyautogui", ok)
    result = await _call({"whole_screen": True})
    assert result["ok"] is True, result
    assert result["target"] == "screen"


@pytest.mark.asyncio
async def test_macos_falls_back_to_pyautogui(shots, monkeypatch):
    def broken(out, region, window_id=None):
        raise RuntimeError("screencapture missing")

    monkeypatch.setattr(visual, "_capture_screencapture", broken)
    result = await _call({"whole_screen": True})
    assert result["ok"] is True, result
    assert result["target"] == "screen"


@pytest.mark.asyncio
async def test_windows_uses_pyautogui_only(shots, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(visual, "_capture_screencapture",
                        lambda out, region: out.write_bytes(b"not reached"))
    result = await _call({})
    assert result["ok"] is True, result


@pytest.mark.asyncio
async def test_unsupported_platform_is_a_soft_error(shots, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    result = await _call({})
    assert result["ok"] is False and "macOS and Windows" in result["error"]


@pytest.mark.asyncio
async def test_old_shots_are_cleaned_up(shots):
    stale = shots["dir"] / "old.png"
    stale.write_bytes(PNG_1PX)
    eight_days = time.time() - 8 * 24 * 3600
    os.utime(stale, (eight_days, eight_days))
    result = await _call({})
    assert result["ok"] is True
    assert not stale.exists()
