"""Standalone MIDI bridge daemon (v0.3 split transport).

Why this exists
---------------
The MCP server is launched by the MCP *client* (Claude Desktop, Claude Code,
Cursor, ...). Some clients -- notably the Microsoft Store / MSIX build of
Claude Desktop -- launch their child MCP-server process in an environment
where the Windows MIDI subsystem does not deliver input data: the loopMIDI
ports still enumerate and open without error, but no MIDI ever arrives. A
process started normally (a terminal, a login-startup task) has full MIDI
access.

To make the bridge work under *every* client, all MIDI I/O lives in this
daemon, which the user runs as an ordinary process. The MCP server then talks
to the daemon over a localhost TCP socket -- and TCP is unaffected by the
client's launch context (this is also why socket-based MCPs like AbletonMCP
"just work" everywhere).

    MCP client --stdio--> MCP server --TCP(localhost)--> daemon --MIDI--> FL

Run it::

    fl-studio-mcp-daemon            # or: python -m fl_studio_mcp.daemon

Then point the MCP server at it by setting ``FLSTUDIO_MCP_TRANSPORT=tcp`` in
the client's MCP config env.

Wire protocol (newline-delimited JSON, one object per line):

    -> {"op": "health"}
    <- {"alive": bool, "heartbeat_age": float|null}

    -> {"op": "call", "cmd": str, "params": {...}|null, "timeout": float}
    <- {"ok": true, "data": ...}
       {"ok": false, "exc": "FLTimeout"|"FLNotRunning"|..., "error": str, "code": str}
"""

from __future__ import annotations

import json
import logging
import os
import socketserver
import threading

from . import __version__
from . import protocol
from .connection import (
    FLBridge,
    FLBridgeError,
    FLCommandFailed,
    FLNotRunning,
    FLPortMissing,
    FLTimeout,
)
from .connection import DEFAULT_TCP_HOST, DEFAULT_TCP_PORT


logger = logging.getLogger("fl_studio_mcp.daemon")


_bridge: FLBridge | None = None
_bridge_lock = threading.Lock()


def _get_bridge() -> FLBridge:
    """Return the singleton FLBridge, opening it lazily.

    Re-tried on every request until the virtual MIDI ports exist, so the
    daemon can be started before FL and the ports are ready.
    """
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            b = FLBridge()
            b.open()  # raises FLPortMissing if virtual MIDI ports are absent
            _bridge = b
        return _bridge


def _handle_request(req: dict) -> dict:
    op = req.get("op")

    if op == "health":
        try:
            bridge = _get_bridge()
        except FLPortMissing as e:
            return {"alive": False, "heartbeat_age": None, "error": str(e)}
        return {"alive": bridge.is_alive(), "heartbeat_age": bridge.heartbeat_age()}

    if op == "call":
        command = req.get("cmd")
        params = req.get("params")
        timeout = req.get("timeout")
        try:
            data = _get_bridge().call(command, params, timeout=timeout)
            return {"ok": True, "data": data}
        except FLCommandFailed as e:
            return {"ok": False, "exc": "FLCommandFailed", "error": str(e),
                    "code": getattr(e, "code", "error")}
        except FLNotRunning as e:
            return {"ok": False, "exc": "FLNotRunning", "error": str(e)}
        except FLTimeout as e:
            return {"ok": False, "exc": "FLTimeout", "error": str(e)}
        except FLPortMissing as e:
            return {"ok": False, "exc": "FLPortMissing", "error": str(e)}
        except FLBridgeError as e:
            return {"ok": False, "exc": "FLBridgeError", "error": str(e)}
        except Exception as e:  # pragma: no cover - defensive
            return {"ok": False, "exc": "Error",
                    "error": "%s: %s" % (type(e).__name__, e)}

    if op == "apply_notes":
        # Daemon-side note authoring: generate the .pyscript with notes baked
        # in, write it, force-focus FL, and fire the platform run-last-script
        # shortcut. Runs here (normal process) so it works even when the MCP
        # server is MSIX-sandboxed.
        try:
            trigger = req.get("trigger", True)
            ensured = None
            if trigger:                       # auto-open the piano roll first
                try:
                    ensured = _get_bridge().call(protocol.CMD_ENSURE_PIANO_ROLL, {}, timeout=5.0)
                except Exception as e:
                    ensured = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
            from .pianoroll import apply_notes
            res = apply_notes(req.get("notes") or [], req.get("mode", "replace"), trigger=trigger,
                              quantize=req.get("quantize"), snap_ends=req.get("snap_ends", False))
            if isinstance(res, dict):
                res["piano_roll_ensured"] = ensured
            return res
        except Exception as e:
            return {"ok": False, "exc": "Error",
                    "error": "%s: %s" % (type(e).__name__, e)}

    return {"ok": False, "exc": "Error", "error": "unknown op: %r" % (op,)}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        logger.debug("client connected: %s", self.client_address)
        try:
            for raw in self.rfile:  # one request per line
                line = raw.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line.decode("utf-8"))
                except Exception as e:
                    resp = {"ok": False, "exc": "Error", "error": "bad json: %s" % e}
                else:
                    resp = _handle_request(req)
                try:
                    body = json.dumps(protocol.sanitize_for_json(resp), allow_nan=False)
                except ValueError as e:
                    # The command has already run. Report the invalid result
                    # without changing values to null or replaying the write.
                    body = json.dumps({
                        "ok": False, "exc": "FLCommandFailed", "code": "invalid_result",
                        "error": "%s. Command may have applied; inspect state before retrying." % e,
                    }, allow_nan=False)
                self.wfile.write((body + "\n").encode("utf-8"))
                self.wfile.flush()
        except Exception:  # pragma: no cover - defensive
            logger.exception("handler error")
        finally:
            logger.debug("client disconnected: %s", self.client_address)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("FLSTUDIO_MCP_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("FLSTUDIO_MCP_TCP_HOST", DEFAULT_TCP_HOST)
    port = int(os.environ.get("FLSTUDIO_MCP_TCP_PORT", DEFAULT_TCP_PORT))

    # Pre-open so port problems surface in the log immediately. Non-fatal:
    # health/call retry until the ports exist.
    try:
        _get_bridge()
        logger.info("MIDI bridge open.")
    except FLPortMissing as e:
        logger.warning("MIDI ports not ready yet: %s", e)
        logger.warning(
            "Create the virtual MIDI ports and start FL; the daemon will pick "
            "them up on the next request."
        )

    server = _Server((host, port), _Handler)
    logger.info("fl-studio-mcp daemon %s listening on %s:%d", __version__, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
