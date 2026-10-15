"""Check an installer run (no FL Studio needed). Skipped unless pointed at one:

    FLMCP_INSTALL_LOG=install.log   output of scripts/install_windows.bat or install_macos.sh
    FLMCP_DAEMON_CMD=<command>      installed daemon (for the Windows lock check)

The FL folder is found the same way the server finds it (FL_SETTINGS, FL's
registry setting, Documents), so a fake folder works through FL_SETTINGS.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fl_studio_mcp.paths import fl_settings_dir

ROOT = Path(__file__).resolve().parents[1]
LOG = os.environ.get("FLMCP_INSTALL_LOG")

needs_log = pytest.mark.skipif(not LOG, reason="set FLMCP_INSTALL_LOG to check an installer run")


def _log():
    return Path(LOG).read_text(encoding="utf-8", errors="replace")


@needs_log
def test_controller_installed():
    path = fl_settings_dir() / "Hardware" / "FLStudioMCP" / "device_FLStudioMCP.py"
    assert path.is_file(), "not found: %s" % path


@needs_log
def test_mcp_apply_seeded():
    path = fl_settings_dir() / "Piano roll scripts" / "MCP_Apply.pyscript"
    assert path.is_file(), "not found: %s" % path


@needs_log
def test_port_check_ran():
    log = _log().lower()                  # Windows says MISSING, macOS says Missing
    assert "missing ports" in log or "all required ports present" in log, \
        "installer log has no port check result"


@needs_log
def test_chords_ready():
    if "Audio to MIDI not installed" in _log():
        pytest.skip("installed without audio to MIDI")
    assert "Chords to MIDI: ready" in _log(), "installer log doesn't say 'Chords to MIDI: ready'"


@needs_log
@pytest.mark.skipif(sys.platform != "win32", reason="the file lock check is Windows only")
def test_installer_refuses_while_daemon_runs():
    cmd = shlex.split(os.environ.get("FLMCP_DAEMON_CMD", ""), posix=False)
    if not cmd:
        pytest.skip("set FLMCP_DAEMON_CMD")
    daemon = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(3)
        run = subprocess.run(["cmd", "/c", str(ROOT / "scripts" / "install_windows.bat")],
                             capture_output=True, text=True, errors="replace", timeout=300,
                             env=dict(os.environ, FLMCP_EXTRAS="none"), cwd=ROOT)
        print(run.stdout)
        assert run.returncode != 0, "installer ran although the daemon was running"
        assert "daemon is running" in run.stdout, "installer didn't say the daemon is running"
    finally:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(daemon.pid)], capture_output=True)
