"""Playlist domain tool — v1.2 Phase 3.

Adds ``fl_playlist`` as a consolidated public domain tool for playlist track
metadata/control operations. Playlist clip placement, movement, deletion, and
editing remain out of scope.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import operations, safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, fetch_all_pages, get_bridge


def register(mcp: FastMCP) -> None:
    """Attach the fl_playlist domain tool to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Playlist domain operation",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_playlist(
        action: Annotated[
            str,
            Field(
                description=(
                    "Playlist action: list, get, select, set_color, set_mute, "
                    "set_name, set_solo. Clip editing and deletion are not supported."
                )
            ),
        ],
        params: Annotated[
            dict | None,
            Field(
                description=(
                    "Action parameters. Required keys vary by action:\n"
                    "  list: {} or {start: int}\n"
                    "  get: {index: int}\n"
                    "  select: {index: int, state: bool|null}\n"
                    "  set_color: {index: int, color: int} or {index, r, g, b}\n"
                    "  set_mute/set_solo: {index: int, state: bool}\n"
                    "  set_name: {index: int, name: str}"
                )
            ),
        ] = None,
    ) -> dict:
        """Run one consolidated playlist track operation through the registry.

        Read-only actions call the bridge after registry validation.
        Persistent writes (track selection, color, mute, name, solo) use the
        safety layer: snapshot -> write -> readback -> changelog -> rollback
        restore.

        The ``list`` action is paginated automatically so all playlist tracks
        are returned in a single response.

        Safety: Write-Safe with Rollback for persistent track metadata/control
        writes; Read-Only for playlist track reads. Playlist clip editing,
        placement, movement, and deletion are intentionally unsupported.
        """
        try:
            prepared = operations.prepare_operation("playlist", action, params or {})
        except operations.OperationValidationError as exc:
            raise ValueError(str(exc)) from exc

        bridge = get_bridge()
        if prepared.safety_class == "write-safe":
            return safety.safe_write(
                bridge,
                **prepared.safe_write_kwargs(tool=f"playlist_{prepared.action}"),
            )

        if prepared.safety_class == "read-only":
            if action == "list":
                return _bridge_call_paginated(bridge, prepared.command.command, "tracks")
            return _bridge_call(bridge, prepared.command.command, prepared.command.params)

        raise ValueError(f"unsupported playlist safety class: {prepared.safety_class}")


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
