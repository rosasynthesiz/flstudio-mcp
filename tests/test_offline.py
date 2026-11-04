"""Run the offline scripts/test_*.py checks under pytest (no FL Studio needed).

    python -m pytest -v

FLMCP_DAEMON_CMD / FLMCP_SERVER_CMD point the app tests at an installed
daemon / MCP server instead of the code in src/.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

APP = ["server_tools", "mcp_stdio", "daemon_tcp", "bridge_e2e"]
OFFLINE = ["paths", "protocol_sync", "step_grid", "bulk", "chains", "color", "mix_doctor", "midi_export",
           "quantize", "plugin_library", "preset_library", "resources"]
AUDIO = ["audio_analysis", "melody_extract", "reference_match", "chord_progression", "drums",
         "chords_extract"]

_INSTALLED = {"daemon_tcp": "FLMCP_DAEMON_CMD", "mcp_stdio": "FLMCP_SERVER_CMD"}

# Go through the (absent) daemon instead of opening MIDI ports: CI runners may
# have no working MIDI system, and RtMidi then aborts the process.
_ENV = {"resources": {"FLSTUDIO_MCP_TRANSPORT": "tcp"}}


def run_script(name):
    args = shlex.split(os.environ.get(_INSTALLED.get(name, ""), ""), posix=os.name != "nt")
    proc = subprocess.run([sys.executable, str(SCRIPTS / ("test_%s.py" % name))] + args,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=600, env=dict(os.environ, **_ENV.get(name, {})))
    out = proc.stdout + proc.stderr
    print(out)                                   # shown by pytest -rA and on failure
    if proc.returncode == 77:                    # the script found no working MIDI system
        pytest.skip(out.strip().splitlines()[-1])
    counts = re.findall(r"(\d+) passed, (\d+) failed", out)
    assert proc.returncode == 0, "test_%s failed (%s)" % (
        name, "%s passed, %s failed" % counts[-1] if counts else "exit %d" % proc.returncode)


@pytest.mark.parametrize("name", APP)
def test_app(name):
    run_script(name)


@pytest.mark.parametrize("name", OFFLINE)
def test_offline(name):
    run_script(name)


@pytest.mark.parametrize("name", AUDIO)
def test_audio(name):
    pytest.importorskip("librosa", reason="audio extras not installed")
    if name == "chords_extract":
        for mod in ("onnxruntime", "basic_pitch"):
            pytest.importorskip(mod, reason="chords to MIDI not installed: pip install -e "
                                "'.[audio-chords]' and pip install --no-deps basic-pitch==0.4.0")
    run_script(name)
