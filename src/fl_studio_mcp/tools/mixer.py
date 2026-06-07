"""Mixer domain tool — v1.2 Phase 3.

Adds ``fl_mixer`` as a consolidated public domain tool that dispatches
through the operation registry or existing helpers, mirroring the pattern
established by ``fl_transport`` in Slice 05.

Legacy mixer aliases covered by this domain tool are retired from public
registration in the v1.2 compact surface.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import operations, safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, fetch_all_pages, get_bridge
from .targets import mixer_track_error


def register(mcp: FastMCP) -> None:
    """Attach the fl_mixer domain tool to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Mixer domain operation",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_mixer(
        action: Annotated[
            str,
            Field(
                description=(
                    "Mixer action: list, get, get_selected, get_route, "
                    "select, set_color, set_mute, set_name, set_pan, "
                    "set_route, set_solo, set_stereo_separation, set_volume."
                )
            ),
        ],
        params: Annotated[
            dict | None,
            Field(
                description=(
                    "Action parameters. Required keys vary by action:\n"
                    "  list: {} or {start: int}\n"
                    "  get: {track: int}\n"
                    "  get_selected: {}\n"
                    "  get_route: {track: int}\n"
                    "  select: {track: int}\n"
                    "  set_color: {track: int, color: int} or {track, r, g, b}\n"
                    "  set_mute: {track: int, state: bool}\n"
                    "  set_name: {track: int, name: str}\n"
                    "  set_pan: {track: int, value: float (-1..1)}\n"
                    "  set_route: {src: int, dst: int, enabled: bool}\n"
                    "  set_solo: {track: int, state: bool}\n"
                    "  set_stereo_separation: {track: int, value: float (-1..1)}\n"
                    "  set_volume: {track: int, value: float, unit: 'normalized'|'db'}"
                )
            ),
        ] = None,
    ) -> dict:
        """Run one consolidated mixer operation through the operation registry.

        Read-only actions call the bridge after registry validation.
        Persistent writes (name, volume, pan, mute, solo, color, route,
        stereo separation, select) use the safety layer: snapshot -> write
        -> readback -> changelog -> rollback restore.

        The ``list`` action is paginated automatically so all tracks are
        returned in a single response regardless of mixer size.

        Safety: Write-Safe with Rollback for persistent writes; Read-Only
        for mixer reads.
        """
        resolved = params or {}

        try:
            prepared = operations.prepare_operation("mixer", action, resolved)
        except operations.OperationValidationError as exc:
            raise ValueError(str(exc)) from exc

        bridge = get_bridge()

        # Validate track existence for track-scoped operations.
        if action in {
            "get",
            "get_route",
            "select",
            "set_color",
            "set_mute",
            "set_name",
            "set_pan",
            "set_solo",
            "set_stereo_separation",
            "set_volume",
        }:
            track = resolved.get("track")
            if isinstance(track, int):
                error = mixer_track_error(bridge, track, purpose=f"fl_mixer {action}")
                if error is not None:
                    return error

        # Route validation for set_route.
        if action == "set_route":
            for key, label in (("src", "mixer route source"), ("dst", "mixer route destination")):
                idx = resolved.get(key)
                if isinstance(idx, int):
                    error = mixer_track_error(bridge, idx, purpose=label)
                    if error is not None:
                        return error

        if prepared.safety_class == "write-safe":
            return safety.safe_write(
                bridge,
                **prepared.safe_write_kwargs(tool=f"mixer_{prepared.action}"),
            )

        if prepared.safety_class == "read-only":
            # Paginate list actions automatically.
            if action == "list":
                return _bridge_call_paginated(bridge, prepared.command.command, "tracks")
            return _bridge_call(bridge, prepared.command.command, prepared.command.params)

        raise ValueError(f"unsupported mixer safety class: {prepared.safety_class}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
