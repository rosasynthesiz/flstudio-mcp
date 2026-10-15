"""Shared fixtures: a recording fake bridge + an isolated changelog.

No live FL anywhere -- every test drives safety/plugin/connection code
against :class:`FakeBridge`, which answers scripted responses and records
every call for assertions.
"""

from __future__ import annotations

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
def no_sleep(monkeypatch):
    """Keep retry loops instant in unit tests."""
    import time
    monkeypatch.setattr(time, "sleep", lambda *_: None)
