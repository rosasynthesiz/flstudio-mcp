#!/usr/bin/env python3
"""Offline test: the controller script and the server speak the same SysEx
protocol. Loads device_FLStudioMCP.py with stub FL modules (no FL needed).

    python scripts/test_protocol_sync.py
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fl_studio_mcp import protocol as P  # noqa: E402

_FL_MODULES = ["channels", "device", "general", "midi", "mixer", "patterns",
               "playlist", "plugins", "transport", "ui", "arrangement", "utils"]

_P = _F = 0


def check(label, cond, detail=""):
    global _P, _F
    _P += 1 if cond else 0
    _F += 0 if cond else 1
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", label, ("  -- " + detail) if detail else ""))


def load_controller():
    for name in _FL_MODULES:
        sys.modules.setdefault(name, types.ModuleType(name))
    path = ROOT / "fl_controller" / "FLStudioMCP" / "device_FLStudioMCP.py"
    spec = importlib.util.spec_from_file_location("device_FLStudioMCP", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    dev = load_controller()
    for const in ("PROTOCOL_VERSION", "SYSEX_MANUFACTURER", "SYSEX_MAGIC",
                  "DIR_REQUEST", "DIR_RESPONSE", "DIR_HEARTBEAT", "REQUEST_ID_LEN"):
        check("%s matches" % const, getattr(dev, const) == getattr(P, const),
              "%r vs %r" % (getattr(dev, const), getattr(P, const)))

    req = P.make_request("ping", {"x": 1})
    rid = P.new_request_id()
    decoded = dev._decode_message(P.encode_message(P.DIR_REQUEST, rid, req))
    check("controller decodes a server request",
          decoded == (P.DIR_REQUEST, rid, req), repr(decoded))

    resp = {"v": P.PROTOCOL_VERSION, "ok": True, "data": {"bpm": 150.0, "name": "Lead"}}
    decoded = P.decode_message(dev._encode_message(P.DIR_RESPONSE, rid, resp))
    check("server decodes a controller response",
          decoded == (P.DIR_RESPONSE, rid, resp), repr(decoded))

    check("controller ignores foreign SysEx", dev._decode_message(b"\x41\x10\x42\x12") is None)
    check("all bytes are 7-bit (valid SysEx data)",
          all(b < 0x80 for b in P.encode_message(P.DIR_REQUEST, rid, req)))

    print("\n%d passed, %d failed" % (_P, _F))
    return 1 if _F else 0


if __name__ == "__main__":
    sys.exit(main())
