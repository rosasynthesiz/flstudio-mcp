"""Channel domain tool — v1.2 Phase 3.

Adds ``fl_channel`` as a consolidated public domain tool that dispatches
through the operation registry or existing helpers, mirroring the pattern
established by ``fl_mixer`` in Slice 06.

Legacy channel aliases covered by this domain tool are retired from public
registration in the v1.2 compact surface.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import operations, protocol, safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, fetch_all_pages, get_bridge


def register(mcp: FastMCP) -> None:
    """Attach the fl_channel domain tool to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Channel domain operation",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_channel(
        action: Annotated[
            str,
            Field(
                description=(
                    "Channel action: list, get, get_selected, get_steps, classify, "
                    "select, set_color, set_mute, set_mixer_target, set_name, set_pan, "
                    "set_solo, set_steps, set_volume."
                )
            ),
        ],
        params: Annotated[
            dict | None,
            Field(
                description=(
                    "Action parameters. Required keys vary by action:\n"
                    "  list: {} or {start: int}\n"
                    "  get: {channel: int}\n"
                    "  get_selected: {}\n"
                    "  get_steps: {channel: int, steps: int (1-64), pattern: int|null}\n"
                    "  classify: {}\n"
                    "  select: {channel: int}\n"
                    "  set_color: {channel: int, color: int} or {channel, r, g, b}\n"
                    "  set_mute: {channel: int, state: bool}\n"
                    "  set_mixer_target: {channel: int, track: int}\n"
                    "  set_name: {channel: int, name: str}\n"
                    "  set_pan: {channel: int, value: float (-1..1)}\n"
                    "  set_solo: {channel: int, state: bool}\n"
                    "  set_steps: {channel: int, pattern: int, steps: list[dict]}\n"
                    "  set_volume: {channel: int, value: float, unit: 'normalized'|'db'}"
                )
            ),
        ] = None,
    ) -> dict:
        """Run one consolidated channel operation through the operation registry.

        Read-only actions call the bridge after registry validation.
        Persistent writes (name, volume, pan, mute, solo, color, mixer_target,
        steps, select) use the safety layer: snapshot -> write -> readback
        -> changelog -> rollback restore.

        The ``list`` action is paginated automatically so all channels are
        returned in a single response regardless of channel count.

        The ``classify`` action groups all channels by detected type
        (AudioClip, Sampler, GenPlug, etc.) without mutating FL state.

        The ``get_steps`` action reads the step sequencer grid for a channel;
        ``set_steps`` writes and rollbacks the full grid atomically.

        Safety: Write-Safe with Rollback for persistent writes; Read-Only
        for channel reads.
        """
        resolved = params or {}

        # classify is a compound read-only action not in the operation registry.
        if action == "classify":
            return _classify_channels()

        try:
            prepared = operations.prepare_operation("channel", action, resolved)
        except operations.OperationValidationError as exc:
            raise ValueError(str(exc)) from exc

        bridge = get_bridge()

        if prepared.safety_class == "write-safe":
            # set_steps requires resolving the current pattern when none supplied.
            if action == "set_steps" and "pattern" not in resolved:
                selected = _bridge_call(bridge, protocol.CMD_PATTERN_SELECTED)
                pattern_index = int(selected.get("selected", 1))
                # Re-prepare with the resolved pattern so snapshot scope is correct.
                new_params = dict(resolved)
                new_params["pattern"] = pattern_index
                try:
                    prepared = operations.prepare_operation("channel", action, new_params)
                except operations.OperationValidationError as exc:
                    raise ValueError(str(exc)) from exc

            return safety.safe_write(
                bridge,
                **prepared.safe_write_kwargs(tool=f"channel_{prepared.action}"),
            )

        if prepared.safety_class == "read-only":
            if action == "list":
                return _bridge_call_paginated(bridge, prepared.command.command, "channels")
            return _bridge_call(bridge, prepared.command.command, prepared.command.params)

        raise ValueError(f"unsupported channel safety class: {prepared.safety_class}")


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


def _classify_channels() -> dict:
    """Group all channels by their detected type.

    Read-only. Mirrors the legacy fl_classify_channels tool.
    """
    bridge = get_bridge()
    chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")
    grouped: dict[str, list[dict]] = {}
    for c in chans.get("channels", []):
        ctype = c.get("type", {}).get("label", "unknown")
        grouped.setdefault(ctype, []).append(
            {
                "channel": c.get("channel"),
                "name": c.get("name"),
                "target_mixer_track": c.get("target_mixer_track"),
            }
        )
    return {
        "summary": {k: len(v) for k, v in grouped.items()},
        "groups": grouped,
    }
