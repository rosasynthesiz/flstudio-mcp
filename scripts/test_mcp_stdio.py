#!/usr/bin/env python3
"""Offline test: start the MCP server the way Claude does (stdio, JSON-RPC),
initialize, list tools and call fl_ping. No FL needed.

    python scripts/test_mcp_stdio.py                       # server from src/
    python scripts/test_mcp_stdio.py <server command>      # an installed server
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = 76

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def main() -> int:
    cmd = sys.argv[1:] or [sys.executable, "-c", "from fl_studio_mcp.server import main; main()"]
    print("server:", " ".join(cmd))
    env = dict(os.environ, FLSTUDIO_MCP_TRANSPORT="tcp", FLSTUDIO_MCP_TCP_PORT="9798",
               PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    proc = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(raw) for raw in proc.stdout], daemon=True).start()

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()

    def answer(msg_id, timeout=60):
        while True:
            raw = lines.get(timeout=timeout)       # raises queue.Empty on timeout
            try:
                msg = json.loads(raw)
            except ValueError:
                check("stdout carries only JSON-RPC", False, raw[:80].decode(errors="replace"))
                continue
            if msg.get("id") == msg_id:
                return msg

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "ci", "version": "1"}}})
        init = answer(1)
        check("initialize", "result" in init, str(init)[:120])
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = answer(2).get("result", {}).get("tools", [])
        check("tools/list returns %d tools" % EXPECTED_TOOLS, len(tools) == EXPECTED_TOOLS,
              "got %d" % len(tools))

        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "fl_ping", "arguments": {}}})
        ping = answer(3)
        check("fl_ping answers (FL is not running here)", "result" in ping or "error" in ping,
              str(ping)[:120])
    except queue.Empty:
        check("server answered in time", False)
    finally:
        proc.kill()
        proc.wait(timeout=10)

    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
