"""Capability-introspection tool: what's automated vs manual on this install."""
from __future__ import annotations

from fastmcp import FastMCP

from ..capabilities import describe_capabilities


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={
        "title": "Report FL-MCP capabilities",
        "readOnlyHint": True, "idempotentHint": True, "openWorldHint": True,
    })
    def fl_capabilities() -> dict:
        """Report what this FL-MCP install can do automatically vs. what needs a
        manual step, for THIS OS and transport: MIDI-port mode (virtual vs.
        pre-created), note-bridge automation + the one-time arm, and the FL API
        limits. Call this to explain setup or why a note-write might not land."""
        return describe_capabilities()
