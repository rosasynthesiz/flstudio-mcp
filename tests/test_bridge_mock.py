#!/usr/bin/env python3
"""Mock TCP bridge smoke test for CI.

This does not require FL Studio or MIDI ports. It starts a local one-shot fake
daemon that implements the small JSON protocol used by TCPBridge and verifies
health, command calls, error mapping, and apply_notes proxying.
"""

from __future__ import annotations

import json
import socketserver
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol  # noqa: E402
from fl_studio_mcp.connection import FLCommandFailed, TCPBridge  # noqa: E402


class _State:
    bpm = 120.0
    calls: list[dict] = []


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline()
        req = json.loads(raw.decode("utf-8"))
        op = req.get("op")
        if op == "health":
            resp = {"ok": True, "alive": True, "heartbeat_age": 0.01}
        elif op == "apply_notes":
            resp = {
                "ok": True,
                "mode": req.get("mode"),
                "triggered": bool(req.get("trigger")),
                "notes_written": len(req.get("notes") or []),
            }
        elif op == "call":
            cmd = req.get("cmd")
            params = req.get("params") or {}
            _State.calls.append({"cmd": cmd, "params": params})
            if cmd == protocol.CMD_PING:
                resp = {"ok": True, "data": {"protocol_version": protocol.PROTOCOL_VERSION}}
            elif cmd == protocol.CMD_GET_TEMPO:
                resp = {"ok": True, "data": {"bpm": _State.bpm}}
            elif cmd == protocol.CMD_SET_TEMPO:
                _State.bpm = float(params["bpm"])
                resp = {"ok": True, "data": {"bpm": _State.bpm}}
            else:
                resp = {
                    "ok": False,
                    "exc": "FLCommandFailed",
                    "code": "client",
                    "error": f"unknown command: {cmd}",
                }
        else:
            resp = {"ok": False, "error": f"unknown op: {op}"}
        self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))


@pytest.fixture
def mock_server():
    _State.bpm = 120.0
    _State.calls.clear()
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def bridge(mock_server):
    b = TCPBridge(host="127.0.0.1", port=mock_server.server_address[1], default_timeout=2.0)
    return b


def test_bridge_mock(bridge):
    assert bridge.is_alive() is True
    assert bridge.heartbeat_age() is not None

    ping = bridge.call(protocol.CMD_PING)
    assert ping["protocol_version"] == protocol.PROTOCOL_VERSION

    tempo = bridge.call(protocol.CMD_GET_TEMPO)
    assert tempo["bpm"] == 120.0

    changed = bridge.call(protocol.CMD_SET_TEMPO, {"bpm": 128.0})
    assert changed["bpm"] == 128.0

    notes = bridge.apply_notes([{"pitch": 60, "time_bars": 0, "length_bars": 0.25}])
    assert notes["notes_written"] == 1
    assert notes["triggered"] is True

    with pytest.raises(FLCommandFailed) as excinfo:
        bridge.call("not_a_command")
    
    assert excinfo.value.code == "client"

