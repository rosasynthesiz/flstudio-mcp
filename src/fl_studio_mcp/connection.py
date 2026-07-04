"""MIDI SysEx bridge client used by the MCP server.

Opens two virtual MIDI ports (loopMIDI on Windows, IAC Driver on macOS):
  * port_to_fl    -- server OUTPUT, FL INPUT  (commands)
  * port_from_fl  -- server INPUT,  FL OUTPUT (responses + heartbeats)

Sends a request as a SysEx message and blocks on a threading.Event keyed by
the request id. A background callback dispatches incoming SysEx messages.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import socket
import sys
import threading
import time
from typing import Any

try:
    import mido
except ImportError as _e:  # pragma: no cover -- surfaced at runtime
    mido = None  # type: ignore[assignment]
    _mido_import_error = _e
else:
    _mido_import_error = None

from . import protocol
from .protocol import (
    DEFAULT_TIMEOUT_SECONDS,
    DIR_HEARTBEAT,
    DIR_REQUEST,
    DIR_RESPONSE,
    HEARTBEAT_STALE_SECONDS,
)

logger = logging.getLogger(__name__)


class FLBridgeError(RuntimeError):
    """Base class for bridge transport errors."""


class FLNotRunning(FLBridgeError):
    """Heartbeat is missing or stale."""


class FLCommandFailed(FLBridgeError):
    """FL returned ok=false for a command."""

    def __init__(self, message: str, *, code: str = "error"):
        super().__init__(message)
        self.code = code


class FLTimeout(FLBridgeError):
    """No response arrived inside the timeout window."""


class FLPortMissing(FLBridgeError):
    """One of the virtual MIDI ports could not be opened."""


# ---------------------------------------------------------------------------
# Pending-request slot
# ---------------------------------------------------------------------------

class _Slot:
    __slots__ = ("event", "payload")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.payload: dict | None = None


# ---------------------------------------------------------------------------
# Port discovery
# ---------------------------------------------------------------------------

def _ensure_mido() -> None:
    if mido is None:
        raise FLPortMissing(
            "mido is not installed. Run: pip install mido python-rtmidi  "
            "(original error: %s)" % _mido_import_error
        )


def _find_port(pattern: str, names: list[str]) -> str | None:
    """Case-insensitive substring match. Returns the first match or None."""
    needle = pattern.lower()
    for name in names:
        if needle in name.lower():
            return name
    return None


def _virtual_ports_enabled() -> bool:
    """Whether to self-create virtual MIDI ports when the named ports are absent.

    ``FLSTUDIO_MCP_VIRTUAL_PORTS`` = ``1``/``true``/``on`` forces on, ``0``/
    ``false``/``off`` forces off. Default (``auto``): on for macOS/Linux, whose
    CoreMIDI/ALSA backends support virtual ports; off on Windows (MME can't).
    """
    val = os.environ.get("FLSTUDIO_MCP_VIRTUAL_PORTS", "auto").strip().lower()
    if val in ("1", "true", "on", "yes"):
        return True
    if val in ("0", "false", "off", "no"):
        return False
    return sys.platform != "win32"


def list_ports() -> dict:
    """Return the OS-visible MIDI ports. Useful for `--list-ports`."""
    _ensure_mido()
    return {
        "inputs": list(mido.get_input_names()),
        "outputs": list(mido.get_output_names()),
    }


# ---------------------------------------------------------------------------
# The bridge
# ---------------------------------------------------------------------------

class FLBridge:
    """Holds open MIDI ports for the lifetime of the MCP server process."""

    def __init__(
        self,
        port_to_fl: str | None = None,
        port_from_fl: str | None = None,
        *,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        _ensure_mido()
        self._port_to_fl_pattern = port_to_fl or protocol.port_to_fl_name()
        self._port_from_fl_pattern = port_from_fl or protocol.port_from_fl_name()
        self.default_timeout = default_timeout

        self._lock = threading.Lock()
        self._pending: dict[str, _Slot] = {}
        self._last_heartbeat: float = 0.0
        self._heartbeat_payload: dict | None = None

        self._out_port = None
        self._in_port = None
        self._opened = False
        self._virtual = False

    # -- lifecycle -----------------------------------------------------------

    def open(self) -> None:
        if self._opened:
            return
        out_names = mido.get_output_names()
        in_names = mido.get_input_names()
        out_match = _find_port(self._port_to_fl_pattern, out_names)
        in_match = _find_port(self._port_from_fl_pattern, in_names)

        # macOS/Linux can create CoreMIDI/ALSA *virtual* ports on demand, so the
        # user doesn't have to pre-create IAC buses. If the named ports don't
        # already exist and virtual mode applies, create them here. (Windows'
        # MME backend can't create virtual ports -- loopMIDI is still required.)
        if (out_match is None or in_match is None) and _virtual_ports_enabled():
            self._open_virtual()
            return

        if out_match is None:
            raise FLPortMissing(
                "No OUTPUT MIDI port matching %r. Available: %s. "
                "Create the port in loopMIDI (Windows) or IAC Driver (macOS), "
                "or set FLSTUDIO_MCP_PORT_TO_FL to an existing port name."
                % (self._port_to_fl_pattern, out_names)
            )
        if in_match is None:
            raise FLPortMissing(
                "No INPUT MIDI port matching %r. Available: %s. "
                "Create the port in loopMIDI (Windows) or IAC Driver (macOS), "
                "or set FLSTUDIO_MCP_PORT_FROM_FL to an existing port name."
                % (self._port_from_fl_pattern, in_names)
            )
        logger.info("Opening MIDI ports: out=%r, in=%r", out_match, in_match)
        self._out_port = mido.open_output(out_match)
        self._in_port = mido.open_input(in_match, callback=self._on_midi)
        self._opened = True
        self._virtual = False
        atexit.register(self.close)

    def _open_virtual(self) -> None:
        """Create the two bridge ports as virtual CoreMIDI/ALSA ports.

        Our virtual OUTPUT (``port_to_fl``) appears to FL as an INPUT it can
        enable; our virtual INPUT (``port_from_fl``) appears to FL as an OUTPUT.
        This matches the protocol and removes the manual IAC-setup step on macOS.
        """
        to_fl = self._port_to_fl_pattern
        from_fl = self._port_from_fl_pattern
        logger.info("Creating VIRTUAL MIDI ports: out=%r, in=%r", to_fl, from_fl)
        try:
            self._out_port = mido.open_output(to_fl, virtual=True)
            self._in_port = mido.open_input(from_fl, virtual=True, callback=self._on_midi)
        except Exception as e:
            raise FLPortMissing(
                "Could not create virtual MIDI ports (%s). On macOS this should "
                "work out of the box; on Windows use loopMIDI and set the port "
                "names. Ports wanted: %r / %r." % (e, to_fl, from_fl)
            ) from e
        self._opened = True
        self._virtual = True
        atexit.register(self.close)

    def close(self) -> None:
        if self._in_port is not None:
            with contextlib.suppress(Exception):  # pragma: no cover
                self._in_port.close()
        if self._out_port is not None:
            with contextlib.suppress(Exception):  # pragma: no cover
                self._out_port.close()
        self._in_port = None
        self._out_port = None
        self._opened = False
        self._virtual = False
        with contextlib.suppress(Exception):  # pragma: no cover
            atexit.unregister(self.close)

    def __del__(self):  # pragma: no cover - best-effort cleanup on GC
        with contextlib.suppress(Exception):
            self.close()

    # -- health --------------------------------------------------------------

    def heartbeat_age(self) -> float | None:
        if self._last_heartbeat == 0.0:
            return None
        return max(0.0, time.monotonic() - self._last_heartbeat)

    def is_alive(self) -> bool:
        age = self.heartbeat_age()
        return age is not None and age <= HEARTBEAT_STALE_SECONDS

    def wait_for_heartbeat(self, timeout: float = HEARTBEAT_STALE_SECONDS) -> bool:
        """Block briefly waiting for the first heartbeat after open()."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_alive():
                return True
            time.sleep(0.05)
        return self.is_alive()

    def check_alive(self) -> None:
        if not self._opened:
            self.open()
        if self._last_heartbeat == 0.0:
            # First call after open(): give FL a moment to send a heartbeat.
            self.wait_for_heartbeat()
        if not self.is_alive():
            raise FLNotRunning(
                "FL Studio controller is not responding. Verify:\n"
                "  1. FL Studio is open.\n"
                "  2. FLStudioMCP is selected as the Controller type for the "
                "virtual MIDI input port in Options > MIDI Settings.\n"
                "  3. The OUTPUT virtual MIDI port has the same Port number as "
                "the INPUT port so the script can route SysEx back to the server.\n"
                "  4. View > Script output shows '[FLStudioMCP] Ready'."
            )

    # -- request / response --------------------------------------------------

    def call(
        self,
        command: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        self.check_alive()

        request_id = protocol.new_request_id()
        request = protocol.make_request(command, params)
        encoded = protocol.encode_message(DIR_REQUEST, request_id, request)
        eff_timeout = timeout or self.default_timeout

        slot = _Slot()
        with self._lock:
            self._pending[request_id] = slot

        try:
            msg = mido.Message("sysex", data=encoded)
            self._out_port.send(msg)
            if not slot.event.wait(eff_timeout):
                raise FLTimeout(
                    "FL Studio did not respond to %r within %.1fs."
                    % (command, eff_timeout)
                )
            resp = slot.payload or {}
            if resp.get("ok"):
                return resp.get("data")
            raise FLCommandFailed(
                resp.get("error", "FL returned an error"),
                code=resp.get("code", "error"),
            )
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def apply_notes(self, notes, mode="replace", trigger=True, quantize=None, snap_ends=False):
        """Author piano-roll notes locally (direct mode: this process writes
        the generated .pyscript and triggers FL itself). Auto-opens the Piano
        roll first so the trigger has a target. ``quantize`` (grid in bars)
        instead snaps existing notes to that grid."""
        from .pianoroll import apply_notes as _apply
        ensured = None
        if trigger:
            try:
                ensured = self.call(protocol.CMD_ENSURE_PIANO_ROLL, {}, timeout=5.0)
            except Exception as e:
                ensured = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        res = _apply(notes, mode, trigger=trigger, quantize=quantize, snap_ends=snap_ends)
        if isinstance(res, dict) and ensured is not None:
            res["piano_roll_ensured"] = ensured
        return res

    # -- inbound MIDI callback -----------------------------------------------

    def _on_midi(self, msg) -> None:
        """Called from a background MIDI thread."""
        if msg.type != "sysex":
            return
        decoded = protocol.decode_message(msg.data)
        if decoded is None:
            return  # Not one of ours -- ignore.
        direction, request_id, payload = decoded

        if direction == DIR_HEARTBEAT:
            self._last_heartbeat = time.monotonic()
            self._heartbeat_payload = payload
            return

        if direction == DIR_RESPONSE:
            with self._lock:
                slot = self._pending.get(request_id)
            if slot is None:
                # Stale response -- the caller already timed out. Drop it.
                logger.debug("Stale response for %s", request_id)
                return
            slot.payload = payload
            slot.event.set()
            return

        # DIR_REQUEST coming from FL is a protocol error; we don't handle it.
        logger.warning("Unexpected direction %d from FL", direction)


# ---------------------------------------------------------------------------
# TCP bridge -- talks to the standalone MIDI daemon instead of doing MIDI
# itself. Used when FLSTUDIO_MCP_TRANSPORT=tcp so the MCP server works even
# under MCP clients that launch their servers in a MIDI-restricted context
# (e.g. the Microsoft Store / MSIX build of Claude Desktop). See daemon.py.
# ---------------------------------------------------------------------------

DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 9787


class TCPBridge:
    """Drop-in replacement for :class:`FLBridge` that proxies to the daemon.

    Implements the subset of the FLBridge interface the tools use
    (``call`` / ``heartbeat_age`` / ``is_alive``) over a newline-delimited
    JSON socket. All MIDI work happens in the daemon process.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        *,
        default_timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.host = host or os.environ.get("FLSTUDIO_MCP_TCP_HOST", DEFAULT_TCP_HOST)
        self.port = int(port or os.environ.get("FLSTUDIO_MCP_TCP_PORT", DEFAULT_TCP_PORT))
        self.default_timeout = default_timeout
        self._lock = threading.Lock()

    # -- transport -----------------------------------------------------------

    def _rpc(self, req: dict, timeout: float) -> dict:
        with self._lock, socket.create_connection((self.host, self.port), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        if not buf:
            raise FLBridgeError("daemon closed the connection without replying")
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))

    def _daemon_unreachable(self, exc: Exception) -> FLPortMissing:
        return FLPortMissing(
            "Cannot reach the fl-studio-mcp daemon at %s:%d. Start it (run "
            "`fl-studio-mcp-daemon` in a normal terminal / on login) so MIDI "
            "works regardless of which app launched the MCP server. (%s)"
            % (self.host, self.port, exc)
        )

    # -- health --------------------------------------------------------------

    def heartbeat_age(self) -> float | None:
        try:
            resp = self._rpc({"op": "health"}, timeout=5.0)
        except OSError:
            # Daemon down -> report "no heartbeat" so fl_ping degrades cleanly.
            return None
        return resp.get("heartbeat_age")

    def is_alive(self) -> bool:
        try:
            resp = self._rpc({"op": "health"}, timeout=5.0)
        except OSError:
            return False
        return bool(resp.get("alive"))

    # -- request / response --------------------------------------------------

    def call(
        self,
        command: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        t = timeout or self.default_timeout
        try:
            resp = self._rpc(
                {"op": "call", "cmd": command, "params": params, "timeout": t},
                timeout=t + 5.0,
            )
        except OSError as e:
            raise self._daemon_unreachable(e) from e
        if resp.get("ok"):
            return resp.get("data")
        exc = resp.get("exc")
        msg = resp.get("error", "daemon returned an error")
        if exc == "FLCommandFailed":
            raise FLCommandFailed(msg, code=resp.get("code", "error"))
        if exc == "FLNotRunning":
            raise FLNotRunning(msg)
        if exc == "FLTimeout":
            raise FLTimeout(msg)
        if exc == "FLPortMissing":
            raise FLPortMissing(msg)
        raise FLBridgeError(msg)

    def apply_notes(self, notes, mode="replace", trigger=True, quantize=None, snap_ends=False):
        """Author piano-roll notes via the daemon (write generated .pyscript +
        fire the platform run-last-script shortcut). ``quantize`` (grid in
        bars) instead snaps existing notes."""
        try:
            return self._rpc(
                {"op": "apply_notes", "notes": notes, "mode": mode, "trigger": trigger,
                 "quantize": quantize, "snap_ends": snap_ends},
                timeout=30.0,
            )
        except OSError as e:
            raise self._daemon_unreachable(e) from e

    def open(self) -> None:  # pragma: no cover - parity with FLBridge
        return None

    def close(self) -> None:  # pragma: no cover - parity with FLBridge
        return None


# Module-level singleton.
_bridge: FLBridge | TCPBridge | None = None


def get_bridge() -> FLBridge | TCPBridge:
    """Return the process-wide bridge.

    ``FLSTUDIO_MCP_TRANSPORT=tcp`` selects the daemon-backed :class:`TCPBridge`
    (universal: works under any MCP client); anything else uses the in-process
    :class:`FLBridge` (needs no daemon, but the launching client must have MIDI
    access).
    """
    global _bridge
    if _bridge is None:
        transport = os.environ.get("FLSTUDIO_MCP_TRANSPORT", "direct").lower()
        if transport == "tcp":
            _bridge = TCPBridge()
        else:
            _bridge = FLBridge()
            _bridge.open()
    return _bridge


def reset_bridge() -> None:
    """Drop the cached bridge. Useful in tests."""
    global _bridge
    if _bridge is not None:
        _bridge.close()
    _bridge = None


# ---------------------------------------------------------------------------
# Budget-paginated list helper
# ---------------------------------------------------------------------------

def fetch_all_pages(bridge, command, list_key, params=None, *, max_pages=500):
    """Drive a payload-budget-paginated list command to completion.

    SysEx payloads above ~1.5 KB are dropped by the MIDI layer, so list
    commands on the FL side return one bounded page at a time:

        {"total": int, "start": int, "next_start": int|None, <list_key>: [...]}

    This loops -- call with start=0, then start=next_start -- until
    ``next_start`` is None, concatenating the pages. Works with any bridge that
    exposes ``.call`` (both :class:`FLBridge` and :class:`TCPBridge`).

    Returns ``{"total": int, <list_key>: [all items]}``.
    """
    base = dict(params or {})
    items: list = []
    total = None
    start = 0
    for _ in range(max_pages):
        base["start"] = start
        resp = bridge.call(command, base)
        total = resp.get("total", total)
        items.extend(resp.get(list_key) or [])
        nxt = resp.get("next_start")
        if nxt is None or int(nxt) <= start:   # done, or no forward progress
            break
        start = int(nxt)
    return {"total": total, list_key: items}
