"""fl-studio-mcp -- MCP server that controls FL Studio via a MIDI SysEx bridge."""

from __future__ import annotations

try:  # one version: pyproject.toml
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("fl-studio-mcp")
except Exception:  # pragma: no cover - source checkout without metadata
    __version__ = "2.0.0"

from .connection import (
    FLBridge,
    FLBridgeError,
    FLCommandFailed,
    FLNotRunning,
    FLPortMissing,
    FLTimeout,
    fetch_all_pages,
    get_bridge,
    list_ports,
    reset_bridge,
)
from .protocol import (
    PROTOCOL_VERSION,
    port_from_fl_name,
    port_to_fl_name,
)

__all__ = [
    "__version__",
    "FLBridge",
    "FLBridgeError",
    "FLCommandFailed",
    "FLNotRunning",
    "FLPortMissing",
    "FLTimeout",
    "fetch_all_pages",
    "get_bridge",
    "list_ports",
    "reset_bridge",
    "PROTOCOL_VERSION",
    "port_to_fl_name",
    "port_from_fl_name",
]
