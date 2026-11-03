#!/usr/bin/env python3
"""Offline test: drums to MIDI (music/drums.py) on a synthetic loop with all
five sounds, the sorting rule, and the step-sequencer conversion.

    python scripts/test_drums.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from fl_studio_mcp.music import drums  # noqa: E402

SR = 44100
BPM = 120.0
_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def hit(kind, rng):
    t = np.arange(int(0.45 * SR)) / SR
    noise = rng.standard_normal(len(t))
    bright = np.diff(np.diff(noise, prepend=0), prepend=0)          # mostly > 5 kHz
    if kind == "kick":
        return np.sin(2 * np.pi * (50 + 80 * np.exp(-t * 30)) * t) * np.exp(-t * 12)
    if kind == "closed hat":
        return 0.3 * bright * np.exp(-t * 80)
    if kind == "open hat":
        return 0.3 * bright * np.exp(-t * 8)                       # rings ~0.3 s
    if kind == "snare":
        return 0.5 * (0.5 * np.sin(2 * np.pi * 190 * t) + noise) * np.exp(-t * 25)
    # clap: a few quick bursts of mid-band noise, no low body
    mid = np.convolve(noise, np.ones(10) / 10, "same") - np.convolve(noise, np.ones(40) / 40, "same")
    env = sum(np.exp(-np.clip(t - d, 0, None) * 60) * (t >= d) for d in (0, 0.01, 0.02))
    return 0.6 * mid * env


def loop():
    """One bar of 8ths at 120 BPM; the open hat has room to ring before the next hit."""
    rng = np.random.default_rng(1)
    pattern = ["kick", "closed hat", "snare", "closed hat", "kick", "open hat", "clap", None]
    step = int(SR * 60 / BPM / 2)
    y = np.zeros(step * len(pattern) + SR)
    for i, kind in enumerate(pattern):
        if kind:
            h = hit(kind, rng)
            y[i * step:i * step + len(h)] += h
    return 0.8 * y / np.abs(y).max(), [k for k in pattern if k]


def tool_test(wav):
    """fl_extract_drums through the MCP server into a fake FL step sequencer."""
    import asyncio
    import importlib.util
    import json
    import types

    from fl_studio_mcp import safety
    from fl_studio_mcp.server import build_server

    grid = {(1, 3): 1}                                       # something already there
    for name in ["channels", "device", "general", "midi", "mixer", "patterns", "playlist",
                 "plugins", "transport", "ui", "arrangement", "utils"]:
        sys.modules[name] = types.ModuleType(name)
    sys.modules["channels"].getGridBit = lambda c, i: grid.get((c, i), 0)
    sys.modules["channels"].setGridBit = (
        lambda c, i, v: grid.__setitem__((c, i), 1) if v else grid.pop((c, i), None))
    sys.modules["patterns"].patternNumber = lambda: 1
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "dev_drums", root / "fl_controller" / "FLStudioMCP" / "device_FLStudioMCP.py")
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)

    class Bridge:
        def call(self, command, params=None, timeout=None):
            return json.loads(json.dumps(dev._dispatch(command, params or {})))

    bridge = Bridge()
    for name, mod in list(sys.modules.items()):
        if name.startswith("fl_studio_mcp.tools.") and hasattr(mod, "get_bridge"):
            mod.get_bridge = lambda: bridge
    tmp = Path(tempfile.mkdtemp(prefix="flmcp_drumtool_"))      # not the user's undo log
    safety._DIR, safety._PATH = tmp, tmp / "changelog.jsonl"
    safety._log = safety.ChangeLog()
    server = build_server()

    def call(name, args):
        res = asyncio.run(server.call_tool(name, args))
        sc = getattr(res, "structured_content", None)
        return sc.get("result", sc) if sc and set(sc) == {"result"} else sc

    r = call("fl_extract_drums", {"path": str(wav), "bpm": BPM,
                                  "to_channels": {"kick": 0, "snare": 1, "open hat": 2}})
    check("tool: .mid written", Path(r["midi_file"]).is_file())
    check("tool: kick into channel 0 on steps 1 and 9",
          sorted(i for (c, i) in grid if c == 0) == [0, 8], str(sorted(grid)))
    check("tool: snare replaced channel 1's old step", sorted(i for (c, i) in grid if c == 1) == [4])
    check("tool: reports everything written", r["ok"] and r["not_written"] == [])
    call("fl_rollback_last_change", {})
    check("tool: one undo restores all channels", grid == {(1, 3): 1}, str(grid))
    bad = call("fl_extract_drums", {"path": str(wav), "to_channels": {"cowbell": 5}})
    check("tool: unknown kind is refused", bad["ok"] is False and "cowbell" in bad["error"])


def main() -> int:
    check("rule: low energy = kick", drums.classify(0.9, 0.95, 0.0, 100) == drums.KICK)
    check("rule: short bright = closed hat", drums.classify(0, 0, 0.95, 35) == drums.HIHAT)
    check("rule: long bright = open hat", drums.classify(0, 0, 0.95, 300) == drums.OPEN_HAT)
    check("rule: mid with body = snare", drums.classify(0.02, 0.28, 0.4, 80) == drums.SNARE)
    check("rule: mid without body = clap", drums.classify(0.0, 0.06, 0.15, 60) == drums.CLAP)

    d = Path(tempfile.mkdtemp(prefix="flmcp_drums_"))
    y, pattern = loop()
    sf.write(str(d / "loop.wav"), y, SR)
    notes = drums.drum_notes(str(d / "loop.wav"), BPM, quantize=0.125)
    kinds = [n["kind"] for n in sorted(notes, key=lambda n: n["time_bars"])]
    check("one note per hit", len(kinds) == len(pattern), str(kinds))
    check("all five sounds sorted right", kinds == pattern, str(kinds))
    check("summary counts", drums.summary(notes).get("closed hat") == 2)

    steps = drums.to_steps(notes, bars=1)
    check("to step sequencer: kick on 1 and 9",
          steps.get("kick") == [0, 8], str(steps))
    check("to step sequencer: open hat on step 11", steps.get("open hat") == [10], str(steps))
    check("steps outside the bars are dropped", drums.to_steps(notes, bars=1, start_bar=1) == {})

    tool_test(d / "loop.wav")

    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
