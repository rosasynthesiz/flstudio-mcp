#!/usr/bin/env python3
"""Offline test: step sequencer read/write. Runs the real controller handlers
against a fake FL step grid, through the server's safety layer (write, read
back, rollback). No FL needed.

    python scripts/test_step_grid.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fl_studio_mcp import protocol, safety  # noqa: E402
from fl_studio_mcp.tools.steps import parse_steps  # noqa: E402

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


GRID = {}                                   # (channel, step) -> 1


def load_controller():
    names = ["channels", "device", "general", "midi", "mixer", "patterns", "playlist",
             "plugins", "transport", "ui", "arrangement", "utils"]
    for name in names:
        sys.modules[name] = types.ModuleType(name)
    ch = sys.modules["channels"]
    ch.getGridBit = lambda c, i: GRID.get((c, i), 0)
    ch.setGridBit = lambda c, i, v: GRID.__setitem__((c, i), 1) if v else GRID.pop((c, i), None)
    sys.modules["patterns"].patternNumber = lambda: 5
    path = ROOT / "fl_controller" / "FLStudioMCP" / "device_FLStudioMCP.py"
    spec = importlib.util.spec_from_file_location("device_FLStudioMCP", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeBridge:
    """Sends commands straight to the controller's handlers."""
    def __init__(self, dev):
        self.dev = dev

    def call(self, command, params=None, timeout=None):
        return self.dev._dispatch(command, params or {})


def main() -> int:
    check("pattern string", parse_steps(pattern="x...x...x...x...") == ([0, 4, 8, 12], 16))
    check("pattern string with bars and 1s", parse_steps(pattern="1.1. ....|....  ..1.") ==
          ([0, 2, 14], 16))
    check("steps list is sorted and deduplicated", parse_steps(steps=[8, 0, 8]) == ([0, 8], 16))
    check("long pattern grows the length", parse_steps(pattern="x" + "." * 31)[1] == 32)
    try:
        parse_steps(steps=[16], length=16)
        check("step outside the range is refused", False)
    except ValueError:
        check("step outside the range is refused", True)

    dev = load_controller()
    bridge = FakeBridge(dev)
    GRID.update({(2, 3): 1})                                  # something already there
    r = bridge.call(protocol.CMD_CHANNEL_GET_GRID, {"channel": 2, "length": 16})
    check("controller reads the grid", r["steps"] == [3] and r["pattern"] == 5, str(r))

    # Keep the user's real undo log (~/.flstudio-mcp/changelog.jsonl) out of this.
    tmp = Path(tempfile.mkdtemp(prefix="flmcp_grid_"))
    safety._DIR, safety._PATH = tmp, tmp / "changelog.jsonl"
    safety._log = safety.ChangeLog()
    out = safety.safe_write(
        bridge, tool="channel_set_grid", scope="grid:2:16",
        command=protocol.CMD_CHANNEL_SET_GRID,
        params={"channel": 2, "steps": [0, 4, 8, 12], "length": 16}, verify=("steps", [0, 4, 8, 12]),
        build_restore=lambda b: {"command": protocol.CMD_CHANNEL_SET_GRID,
                                 "params": {"channel": 2, "length": 16, "steps": b["steps"]}})
    check("write sets exactly those steps", out["after"]["steps"] == [0, 4, 8, 12], str(out["after"]))
    check("old step 3 was turned off", GRID.get((2, 3)) is None)
    check("before state recorded", out["before"]["steps"] == [3])
    check("other channels untouched", all(c == 2 for c, _ in GRID))

    rb = safety.rollback_last_change(bridge)
    now = bridge.call(protocol.CMD_CHANNEL_GET_GRID, {"channel": 2, "length": 16})["steps"]
    check("rollback restores the old steps", now == [3], "%s / %s" % (now, rb))

    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
