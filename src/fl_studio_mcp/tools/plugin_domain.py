"""Plugin domain tool — v1.2 Phase 3.

Adds ``fl_plugin`` as a consolidated public domain tool for already-loaded
plugin parameter operations. Legacy already-loaded plugin parameter aliases are
retired from public registration in the v1.2 compact surface.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import operations, safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, fetch_all_pages, get_bridge
from .plugin import ParamNotFound, resolve_param_index
from .targets import mixer_track_error

_PLUGIN_LOADING_ACTIONS = {
    "add",
    "create",
    "insert",
    "insert_plugin",
    "load",
    "load_plugin",
}


def register(mcp: FastMCP) -> None:
    """Attach the fl_plugin domain tool to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Plugin domain operation",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_plugin(
        action: Annotated[
            str,
            Field(description="Plugin action: list, list_params, get_param, set_param."),
        ],
        params: Annotated[
            dict | None,
            Field(
                description=(
                    "Action parameters. Required keys vary by action:\n"
                    "  list: {track: int}\n"
                    "  list_params: {track: int, slot: int 0-9}\n"
                    "  get_param: {track: int, slot: int 0-9, param: int|str}\n"
                    "  set_param: {track: int, slot: int 0-9, param: int|str, "
                    "value: float 0..1}"
                )
            ),
        ] = None,
    ) -> dict:
        """Run one consolidated already-loaded plugin operation.

        ``list`` and ``list_params`` are read-only. ``get_param`` and
        ``set_param`` resolve string parameter names to concrete integer
        indices before registry dispatch. ``set_param`` uses
        ``safety.safe_write`` with plugin-parameter snapshot/readback and a
        rollback restore payload.

        Plugin loading, insertion, removal, and preset navigation writes are
        intentionally not exposed; loading stays manual.

        Safety: Write-Safe with Rollback for ``set_param``; Read-Only for
        plugin and parameter reads.
        """
        if action in _PLUGIN_LOADING_ACTIONS:
            raise ValueError(
                "plugin loading or insertion is unsupported; configure already-loaded plugins only"
            )

        resolved = dict(params or {})
        bridge = get_bridge()

        track = resolved.get("track")
        if isinstance(track, int):
            error = mixer_track_error(bridge, track, purpose=f"fl_plugin {action}")
            if error is not None:
                return error

        if action == "list_params":
            prepared = _prepare("plugin", "list_params", resolved)
            return _bridge_call_paginated(
                bridge,
                prepared.command.command,
                "params",
                prepared.command.params,
            )

        if action in {"get_param", "set_param"}:
            try:
                idx, name = resolve_param_index(
                    bridge,
                    int(resolved.get("track", -1)),
                    int(resolved.get("slot", -1)),
                    resolved.get("param"),
                )
            except ParamNotFound as exc:
                return {"ok": False, "error": str(exc)}
            resolved["param"] = idx
            prepared = _prepare("plugin", action, resolved)
            if prepared.safety_class == "write-safe":
                result = safety.safe_write(
                    bridge,
                    **prepared.safe_write_kwargs(tool=f"plugin_{prepared.action}"),
                )
                if isinstance(result, dict):
                    result["resolved_param"] = {"index": idx, "name": name}
                return result
            val = _bridge_call(bridge, prepared.command.command, prepared.command.params)
            return {
                "ok": True,
                "track": resolved["track"],
                "slot": resolved["slot"],
                "param_index": idx,
                "param_name": name,
                "value": val.get("v", 0.0),
                "string": val.get("s", ""),
            }

        prepared = _prepare("plugin", action, resolved)
        if prepared.safety_class == "read-only":
            return _bridge_call(bridge, prepared.command.command, prepared.command.params)

        raise ValueError(f"unsupported plugin safety class: {prepared.safety_class}")


def _prepare(domain: str, action: str, params: dict) -> operations.PreparedOperation:
    try:
        return operations.prepare_operation(domain, action, params)
    except operations.OperationValidationError as exc:
        raise ValueError(str(exc)) from exc


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


def _bridge_call_paginated(bridge, command: str, list_key: str, params: dict | None = None) -> dict:
    """Paginate a plugin parameter list command and return all items."""
    try:
        return fetch_all_pages(bridge, command, list_key, params or {}, timeout=10.0, attempts=3)
    except FLNotRunning as e:
        raise RuntimeError(str(e)) from e
    except FLTimeout as e:
        raise RuntimeError(
            f"{e}. Try fl_transport(action='ping') to confirm the controller is alive."
        ) from e
    except FLCommandFailed as e:
        raise RuntimeError(f"FL Studio rejected the command: {e}") from e
