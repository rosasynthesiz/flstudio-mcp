#!/usr/bin/env python3
"""A stand-in for FL Studio on real MIDI ports, for end-to-end tests: runs
the real controller script (device_FLStudioMCP.py) with fake FL modules,
feeding it SysEx from the server and sending its replies and heartbeats back.

    python scripts/fake_fl.py            # until Ctrl+C

Windows: uses the existing loopMIDI ports (close FL first, or both answer).
macOS/Linux: creates virtual ports with those names itself.
"""
from __future__ import annotations

import importlib.util
import sys
import time
import types
from pathlib import Path

import mido

ROOT = Path(__file__).resolve().parents[1]
RX, TX = "FLStudioMCP RX", "FLStudioMCP TX"      # FL's input / FL's output


class Project:
    """A tiny FL project: 3 channels, 4 mixer tracks, a step grid."""
    def __init__(self):
        self.chan_names = ["Kick", "Snare", "Keys"]
        self.targets = [0, 0, 1]
        self.track_names = ["Master", "Keys", "Insert 2", "Insert 3"]
        self.routes = {1: {0}, 2: {0}, 3: {0}}
        self.volumes = [0.8] * len(self.track_names)
        self.grid = set()
        self.tempo = 128.0


def fl_modules(p, send_sysex):
    m = {n: types.ModuleType(n) for n in
         ["channels", "device", "general", "midi", "mixer", "patterns", "playlist",
          "plugins", "transport", "ui", "arrangement", "utils"]}
    ch, mx, pat = m["channels"], m["mixer"], m["patterns"]
    ch.channelCount = lambda *a: len(p.chan_names)
    ch.getChannelName = lambda i, *a: p.chan_names[i]
    ch.getTargetFxTrack = lambda i, *a: p.targets[i]
    ch.getGridBit = lambda c, i, *a: int((c, i) in p.grid)
    ch.setGridBit = lambda c, i, v, *a: p.grid.add((c, i)) if v else p.grid.discard((c, i))
    mx.trackCount = lambda: len(p.track_names)
    mx.getTrackName = lambda i, *a: p.track_names[i]
    mx.setTrackName = lambda i, n, *a: p.track_names.__setitem__(i, n)
    mx.getRouteSendActive = lambda s, d: d in p.routes.get(s, set())
    mx.getCurrentTempo = lambda *a: p.tempo * 1000
    mx.getTrackPan = lambda i, *a: 0.0                 # used by the mixer_track snapshot
    mx.isTrackMuted = mx.isTrackSolo = lambda i, *a: False
    mx.getTrackColor = lambda i, *a: 0
    mx.getTrackVolume = lambda i, *a: p.volumes[i]
    mx.setTrackVolume = lambda i, v, *a: p.volumes.__setitem__(i, v)
    m["transport"].isPlaying = m["transport"].isRecording = lambda: False
    pat.patternNumber = lambda: 1
    pat.patternCount = lambda: 1
    m["ui"].getVersion = lambda *a: "Fake FL (test stand-in)"
    m["device"].midiOutSysex = send_sysex
    return m


def main() -> int:
    virtual = sys.platform != "win32"
    if virtual:
        inp = mido.open_input(RX, virtual=True)
        out = mido.open_output(TX, virtual=True)
    else:
        inp = mido.open_input(next(n for n in mido.get_input_names() if n.startswith(RX)))
        out = mido.open_output(next(n for n in mido.get_output_names() if n.startswith(TX)))

    def send_sysex(data):
        out.send(mido.Message("sysex", data=list(bytes(data)[1:-1])))   # strip F0/F7

    project = Project()
    sys.modules.update(fl_modules(project, send_sysex))
    path = ROOT / "fl_controller" / "FLStudioMCP" / "device_FLStudioMCP.py"
    spec = importlib.util.spec_from_file_location("device_FLStudioMCP", path)
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    dev.OnInit()
    print("fake FL ready (%s ports)" % ("virtual" if virtual else "loopMIDI"), flush=True)

    class Event:
        def __init__(self, data):
            self.sysex = bytes([0xF0] + list(data) + [0xF7])
            self.status, self.handled = 0xF0, False

    try:
        while True:
            for msg in inp.iter_pending():
                if msg.type == "sysex":
                    dev.OnSysEx(Event(msg.data))
            dev.OnIdle()
            time.sleep(0.01)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
