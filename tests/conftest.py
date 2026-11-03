"""Shared fixtures: a recording fake bridge + an isolated changelog.

No live FL anywhere -- every test drives safety/plugin/connection code
against :class:`FakeBridge`, which answers scripted responses and records
every call for assertions.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types

import pytest

from fl_studio_mcp import safety


class FakeBridge:
    """Minimal stand-in for FLBridge/TCPBridge: records calls, replays replies.

    ``replies`` maps a command name to either a single response dict (always
    the same) or a list of responses consumed in order (last one repeats).
    """

    def __init__(self, replies=None):
        self.replies = replies or {}
        self.calls = []          # [(command, params), ...] in order

    def call(self, command, params=None):
        params = dict(params or {})
        self.calls.append((command, params))
        r = self.replies.get(command)
        if r is None:
            return {}
        if isinstance(r, list):
            return r.pop(0) if len(r) > 1 else r[0]
        return dict(r) if isinstance(r, dict) else r

    def calls_to(self, command):
        return [p for c, p in self.calls if c == command]


@pytest.fixture
def fake_bridge():
    return FakeBridge()


@pytest.fixture
def changelog(tmp_path, monkeypatch):
    """Point the safety changelog at a tmp file; return a fresh empty log."""
    monkeypatch.setattr(safety, "_DIR", tmp_path)
    monkeypatch.setattr(safety, "_PATH", tmp_path / "changelog.jsonl")
    log = safety.ChangeLog()
    monkeypatch.setattr(safety, "_log", log)
    return log


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch, request):
    """Speed up safety unit tests without changing installer readiness waits."""
    if request.node.path.name not in {"test_e1_write_verify.py", "test_review_faults.py"}:
        return
    import time
    monkeypatch.setattr(time, "sleep", lambda *_: None)


@pytest.fixture
def controller(monkeypatch):
    for name in ("channels", "device", "general", "midi", "mixer", "patterns",
                 "playlist", "plugins", "transport", "ui", "arrangement", "utils"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    path = (Path(__file__).resolve().parents[1] / "fl_controller"
            / "FLStudioMCP" / "device_FLStudioMCP.py")
    spec = importlib.util.spec_from_file_location("fl_controller_regression", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pytest_runtest_logreport(report):
    if report.failed and os.environ.get("GITHUB_ACTIONS"):
        crash = getattr(report.longrepr, "reprcrash", None)
        text = crash.message if crash else str(report.longrepr)
        reason = text.splitlines()[0][:300] if text else "failed"
        print("\n::error title=%s failed::%s" % (report.nodeid.split("::")[-1], reason), flush=True)
