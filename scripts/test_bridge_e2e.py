#!/usr/bin/env python3
"""End-to-end test over REAL MIDI ports without FL: starts scripts/fake_fl.py
(the real controller script with fake FL modules), the real daemon and the
real MCP server, and drives tools through the whole chain (reads, a write
through the safety layer, and its undo).

    python scripts/test_bridge_e2e.py

Windows needs the loopMIDI ports and FL Studio CLOSED (else FL answers too);
macOS/Linux create virtual ports. Exits 77 (skip) when that's not possible.
"""
from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 9796
SKIP = 77
_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def skip(reason):
    print("SKIP: " + reason)
    sys.exit(SKIP)


def preflight():
    if sys.platform == "win32":
        tasks = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FL64.exe"], capture_output=True,
                               text=True).stdout
        if "FL64.exe" in tasks:
            skip("FL Studio is running; close it, the fake FL would share its MIDI ports")
        import mido
        names = mido.get_input_names() + mido.get_output_names()
        if not any(n.startswith("FLStudioMCP RX") for n in names):
            skip("loopMIDI ports FLStudioMCP RX/TX not found")


def start(args, env, **kw):
    return subprocess.Popen([sys.executable] + args, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, **kw)


def stop(proc):
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.terminate()
    try:
        return proc.communicate(timeout=10)[0] or ""
    except Exception:
        return ""


def main() -> int:
    preflight()
    home = tempfile.mkdtemp(prefix="flmcp_e2e_")     # keep the user's undo log out of it
    env = dict(os.environ, FLSTUDIO_MCP_TCP_PORT=str(PORT), FLSTUDIO_MCP_TRANSPORT="tcp",
               HOME=home, USERPROFILE=home,
               PYTHONPATH=str(ROOT / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    fake = start([str(ROOT / "scripts" / "fake_fl.py")], env)
    seen = ""
    for _ in range(50):                        # the controller prints its own lines first
        line = fake.stdout.readline()
        seen += line
        if not line or line.startswith("fake FL ready"):
            break
    if "fake FL ready" not in seen:
        out = seen + stop(fake)
        if "MIDI client" in out or "ALSA" in out:
            skip("no working MIDI system here: " + out.strip().splitlines()[-1])
        check("fake FL starts", False, out.strip()[-300:])
        return 1
    daemon = start(["-c", "from fl_studio_mcp.daemon import main; main()"], env)
    server = None
    try:
        sock = None
        for _ in range(100):
            try:
                sock = socket.create_connection(("127.0.0.1", PORT), timeout=10)
                break
            except OSError:
                time.sleep(0.2)
        check("daemon listens", sock is not None)
        if sock is None:
            return 1
        f = sock.makefile("rwb")

        def daemon_call(req):
            f.write((json.dumps(req) + "\n").encode())
            f.flush()
            return json.loads(f.readline())

        alive = False
        for _ in range(50):
            alive = daemon_call({"op": "health"}).get("alive")
            if alive:
                break
            time.sleep(0.1)
        check("heartbeat from the controller arrives over MIDI", alive)
        ping = daemon_call({"op": "call", "cmd": "ping", "params": {}, "timeout": 5})
        check("ping round trip over MIDI",
              ping.get("ok") and "Fake FL" in ping["data"].get("fl_version", ""), str(ping)[:150])

        # The MCP server, started like Claude starts it, through the daemon.
        server = subprocess.Popen([sys.executable, "-c",
                                   "from fl_studio_mcp.server import main; main()"],
                                  env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
        lines: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: [lines.put(r) for r in server.stdout], daemon=True).start()
        ids = iter(range(1, 1000))

        def mcp(method, params=None):
            i = next(ids)
            msg = {"jsonrpc": "2.0", "id": i, "method": method}
            if params is not None:
                msg["params"] = params
            server.stdin.write((json.dumps(msg) + "\n").encode())
            server.stdin.flush()
            while True:
                m = json.loads(lines.get(timeout=60))
                if m.get("id") == i:
                    return m

        def tool(name, args=None):
            r = mcp("tools/call", {"name": name, "arguments": args or {}})["result"]
            sc = r.get("structuredContent")
            if sc is not None:
                return sc.get("result", sc) if set(sc) == {"result"} else sc
            return json.loads(r["content"][0]["text"])

        mcp("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "e2e", "version": "1"}})
        server.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        server.stdin.flush()

        check("fl_ping via MCP", tool("fl_ping").get("alive") is True)
        check("fl_get_tempo via MCP", tool("fl_get_tempo").get("bpm") == 128.0)
        state = tool("fl_get_project_state")
        check("fl_get_project_state over MIDI",
              state.get("channel_count") == 3 and state.get("mixer_track_count") == 4, str(state))
        names = [t["name"] for t in tool("fl_get_mixer_state").get("tracks", [])]
        check("fl_get_mixer_state reads the mixer", names[:2] == ["Master", "Keys"], str(names))
        w = tool("fl_set_mixer_volume", {"track": 1, "value": -6.0, "unit": "db"})
        check("fl_set_mixer_volume writes over MIDI (safety layer)",
              w.get("ok") and abs(w["after"]["vol_db"] + 6.0) < 0.1, str(w)[:200])
        tool("fl_rollback_last_change")
        back = [t for t in tool("fl_get_mixer_state")["tracks"] if t["i"] == 1][0]
        check("undo restores the volume", abs(back["vol_db"]) < 0.1, str(back))
    except queue.Empty:
        check("MCP server answered in time", False)
    finally:
        if server is not None:
            server.kill()
        stop(daemon)
        stop(fake)

    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
