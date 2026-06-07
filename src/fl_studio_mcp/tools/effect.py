"""Effect domain tool — v1.2 Phase 3.

Adds ``fl_effect`` as a consolidated public domain tool for effect-slot and
native mixer EQ operations. Legacy effect and EQ aliases are retired from
public registration in the v1.2 compact surface.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import operations, protocol, safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, get_bridge
from .targets import mixer_track_error


def register(mcp: FastMCP) -> None:
    """Attach the fl_effect domain tool to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Effect domain operation",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_effect(
        action: Annotated[
            str,
            Field(
                description=(
                    "Effect action: get_slot, list_slots, get_track_slots_enabled, "
                    "set_slot_enabled, set_slot_mix, set_track_slots_enabled, "
                    "get_eq, set_eq_band."
                )
            ),
        ],
        params: Annotated[
            dict | None,
            Field(
                description=(
                    "Action parameters. Required keys vary by action:\n"
                    "  get_slot: {track: int, slot: int 0-9}\n"
                    "  list_slots: {track: int}\n"
                    "  get_track_slots_enabled: {track: int}\n"
                    "  set_slot_enabled: {track: int, slot: int 0-9, enabled: bool}\n"
                    "  set_slot_mix: {track: int, slot: int 0-9, mix: float 0..1}\n"
                    "  set_track_slots_enabled: {track: int, enabled: bool}\n"
                    "  get_eq: {track: int}\n"
                    "  set_eq_band: {track: int, band: int 0-2, gain?: float 0..1, "
                    "frequency?: float 0..1, bandwidth?: float 0..1, type?: int}"
                )
            ),
        ] = None,
    ) -> dict:
        """Run one consolidated effect or native EQ operation.

        Read-only actions call the bridge after operation-registry validation.
        Persistent writes (slot mix, slot enabled, track slots enabled, native
        EQ band parameters) use ``safety.safe_write``: scoped snapshot -> write
        -> readback -> changelog -> rollback restore.

        Native EQ type writes remain documented-unconfirmed on current live
        evidence and are only safe where readback verifies the change; plugin
        loading, insertion, removal, and full chain restore are not supported.

        Safety: Write-Safe with Rollback for persistent writes; Read-Only for
        effect and native EQ reads.
        """
        resolved = params or {}
        domain, registry_action = _registry_target(action)

        if action == "list_slots":
            _validate_effect_track(resolved)
            bridge = get_bridge()
            error = mixer_track_error(bridge, resolved["track"], purpose="fl_effect list_slots")
            if error is not None:
                return error
            return _list_slots(bridge, resolved["track"])

        try:
            prepared = operations.prepare_operation(domain, registry_action, resolved)
        except operations.OperationValidationError as exc:
            raise ValueError(str(exc)) from exc

        bridge = get_bridge()
        track = prepared.params.get("track")
        if isinstance(track, int):
            error = mixer_track_error(bridge, track, purpose=f"fl_effect {action}")
            if error is not None:
                return error

        if prepared.safety_class == "write-safe":
            return safety.safe_write(
                bridge,
                **prepared.safe_write_kwargs(tool=f"{domain}_{prepared.action}"),
            )

        if prepared.safety_class == "read-only":
            return _bridge_call(bridge, prepared.command.command, prepared.command.params)

        raise ValueError(f"unsupported effect safety class: {prepared.safety_class}")


def _registry_target(action: str) -> tuple[str, str]:
    aliases = {
        "get_eq": ("eq", "get"),
        "set_eq_band": ("eq", "set_band"),
    }
    return aliases.get(action, ("effect", action))


def _validate_effect_track(params: dict) -> None:
    try:
        operations.prepare_operation("effect", "get_track_slots_enabled", params)
    except operations.OperationValidationError as exc:
        raise ValueError(str(exc)) from exc


def _list_slots(bridge, track: int) -> dict:
    slots = [
        _bridge_call(bridge, protocol.CMD_MIXER_GET_SLOT, {"track": track, "slot": slot})
        for slot in range(10)
    ]
    return {"ok": True, "track": track, "slots": slots}


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
