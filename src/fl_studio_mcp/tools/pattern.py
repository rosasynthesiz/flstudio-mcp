"""Pattern domain tool — v1.2 Phase 3.

Adds ``fl_pattern`` as a consolidated public domain tool for existing safe
pattern operations. Legacy pattern aliases are retired from public registration
in the v1.2 compact surface.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import operations, safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, fetch_all_pages, get_bridge


def register(mcp: FastMCP) -> None:
    """Attach the fl_pattern domain tool to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Pattern domain operation",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_pattern(
        action: Annotated[
            str,
            Field(
                description=(
                    "Pattern action: list, get, get_length, get_selected, find_empty, "
                    "select, rename, set_color, set_length. Pattern deletion is not supported."
                )
            ),
        ],
        params: Annotated[
            dict | None,
            Field(
                description=(
                    "Action parameters. Required keys vary by action:\n"
                    "  list: {} or {start: int}\n"
                    "  get/get_length/select: {index: int}\n"
                    "  get_selected/find_empty: {}\n"
                    "  rename: {index: int, name: str}\n"
                    "  set_color: {index: int, color: int} or {index, r, g, b}\n"
                    "  set_length: {index: int, beats: float > 0}"
                )
            ),
        ] = None,
    ) -> dict:
        """Run one consolidated pattern operation through the operation registry.

        Read-only actions call the bridge after registry validation.
        Persistent writes (select, rename, color, length) use the safety layer:
        snapshot -> write -> readback -> changelog -> rollback restore.

        The ``list`` action is paginated automatically so all patterns are
        returned in a single response.

        Safety: Write-Safe with Rollback for persistent writes; Read-Only
        for pattern reads. Pattern deletion is intentionally unsupported.
        """
        try:
            prepared = operations.prepare_operation("pattern", action, params or {})
        except operations.OperationValidationError as exc:
            raise ValueError(str(exc)) from exc

        bridge = get_bridge()
        if prepared.safety_class == "write-safe":
            return safety.safe_write(
                bridge,
                **prepared.safe_write_kwargs(tool=f"pattern_{prepared.action}"),
            )

        if prepared.safety_class == "read-only":
            if action == "list":
                return _bridge_call_paginated(bridge, prepared.command.command, "patterns")
            return _bridge_call(bridge, prepared.command.command, prepared.command.params)

        raise ValueError(f"unsupported pattern safety class: {prepared.safety_class}")


def _bridge_call(bridge, command: str, params: dict | None = None) -> dict:
    """Call the bridge and translate errors into MCP-friendly messages."""
    try:
        return bridge.call(command, params or {})
    except FLNotRunning as e:
        raise RuntimeError(str(e)) from e
    except FLTimeout as e:
        raise RuntimeError(
            f"{e}. Try fl_transport(action='ping') to confirm the controller is alive."
        ) from e
    except FLCommandFailed as e:
        raise RuntimeError(f"FL Studio rejected the command: {e}") from e


def _bridge_call_paginated(bridge, command: str, list_key: str) -> dict:
    """Paginate a list command and return all items."""
    try:
        return fetch_all_pages(bridge, command, list_key)
    except FLNotRunning as e:
        raise RuntimeError(str(e)) from e
    except FLTimeout as e:
        raise RuntimeError(
            f"{e}. Try fl_transport(action='ping') to confirm the controller is alive."
        ) from e
    except FLCommandFailed as e:
        raise RuntimeError(f"FL Studio rejected the command: {e}") from e
