"""Plugin preset tools (E-5): navigate / read a plugin's presets.

The official plugins module (FL 26, confirmed live via fl_api_probe) has
getPresetCount / nextPreset / prevPreset and name reads -- but NO setPreset
and NO preset index, so a true restore is impossible. Live testing also
showed next/prev themselves are best-effort (FL can swallow a step; the
same-RPC name readback lags). Navigation therefore sits OUTSIDE the safety
layer, like fl_undo: no rollback claim, an explicit warning in every
response, and a fresh-tick info re-read so the agent sees the true
post-state.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol
from ..connection import get_bridge

_NO_ROLLBACK = (
    "preset navigation is NOT covered by fl_rollback_last_change: FL 26 "
    "has no setPreset/getPresetIndex, and next/prev themselves are "
    "best-effort (steps can be swallowed). To go back, navigate manually."
)


def register(mcp: FastMCP) -> None:
    # Destructive: next/prev replace the plugin's current settings, which may
    # hold unsaved tweaks, and FL cannot step back to them by index.
    _WR = {"readOnlyHint": False, "destructiveHint": True,
           "idempotentHint": False, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Plugin preset info / next / prev", **_WR})
    def fl_plugin_preset(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
        slot: Annotated[int, Field(ge=-1, le=9,
                                   description="-1 = channel generator; "
                                               "0..9 = mixer FX slot.")] = -1,
        op: Annotated[Literal["info", "next", "prev"],
                      Field(description="info = read-only; "
                                        "next/prev = navigate (no rollback).")] = "info",
    ) -> dict:
        """Read or navigate a plugin's presets. op=info (read-only) returns
        {preset_count, plugin_name, name_f3, name_f6}; name_f6 is the
        CURRENT preset name (via midi.GPN_GetCurrentPreset) -- name_f3 is
        usually empty, don't rely on it. op=next/prev step the preset but
        have NO ROLLBACK (see the response's warning): FL 26 cannot set a
        preset by name/index, and navigation itself is best-effort. The
        response carries a fresh-tick info re-read (`current`) because the
        same-RPC name can lag the navigation."""
        bridge = get_bridge()
        if op == "info":
            return bridge.call(protocol.CMD_PLUGIN_PRESET,
                               {"track": track, "slot": slot, "op": "info"})
        nav = bridge.call(protocol.CMD_PLUGIN_PRESET,
                          {"track": track, "slot": slot, "op": op})
        if (not isinstance(nav, dict) or nav.get("ok") is False
                or nav.get("nav_error")):
            return {"ok": False, "track": track, "slot": slot, "op": op,
                    "nav": nav, "warning": _NO_ROLLBACK}
        current = bridge.call(protocol.CMD_PLUGIN_PRESET,
                              {"track": track, "slot": slot, "op": "info"})
        return {"ok": True, "track": track, "slot": slot, "op": op,
                "nav": nav, "current": current, "warning": _NO_ROLLBACK,
                "rollback": "none"}
