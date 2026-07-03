"""Phase 1B MCP tools: plugin parameter control.

- fl_plugin_list(track)              -> filled effect slots on a mixer track
- fl_plugin_get_params(track, slot)  -> every named param (name, value, string)
- fl_plugin_set_param(track, slot, param, value)
       ``param`` may be an int index OR a param name (e.g. "Decay time").
       Names are resolved server-side from the live param list. The write
       routes through ``safety.safe_write`` so it is logged + rollback-able.

Native FL plugins (Fruity Parametric EQ 2, Reeverb 2, ...) expose real param
names and small counts, so name-based addressing is reliable for them. VST/AU
wrappers can report thousands of generic slots; for those prefer int indices.

Values are NORMALISED 0..1 (FL's setParamValue domain). The display string
from fl_plugin_get_params (e.g. '3.6dB', '500Hz') tells you what a given
normalised value maps to -- there is no generic unit->normalised conversion.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge


class ParamNotFound(ValueError):
    """Raised when a param name cannot be resolved to a single index."""


def _norm(s) -> str:
    """Lowercase + strip non-alphanumerics, for forgiving name matching."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def resolve_param_index(bridge, track: int, slot: int, param):
    """Resolve ``param`` (int index or str name) to a concrete ``(index, name)``.

    Integer (or integer-like) params are used directly, with the name looked
    up for the response. String params are matched against the live param
    list: exact normalised match first, then a unique substring match.
    Ambiguous or missing names raise :class:`ParamNotFound` with the candidate
    list, so the caller can correct the spelling rather than poke a wrong knob.
    """
    if isinstance(param, bool):                       # guard: bool is an int subclass
        raise ParamNotFound("param must be an index or a name, not a bool")
    if isinstance(param, int) or (isinstance(param, str) and param.lstrip("-").isdigit()):
        idx = int(param)
        one = bridge.call(protocol.CMD_PLUGIN_GET_PARAM,
                          {"track": track, "slot": slot, "param": idx})
        return idx, one.get("name", "")

    want = _norm(param)
    if not want:
        raise ParamNotFound("empty param name")

    dump = fetch_all_pages(bridge, protocol.CMD_PLUGIN_GET_PARAMS, "params",
                           {"track": track, "slot": slot})
    params = dump.get("params", [])

    exact = [p for p in params if _norm(p["name"]) == want]
    if len(exact) == 1:
        return exact[0]["i"], exact[0]["name"]
    if len(exact) > 1:
        raise ParamNotFound("param name %r is ambiguous: %s"
                            % (param, [p["name"] for p in exact]))

    subs = [p for p in params if want in _norm(p["name"])]
    if len(subs) == 1:
        return subs[0]["i"], subs[0]["name"]
    if len(subs) > 1:
        raise ParamNotFound("param name %r matches several: %s"
                            % (param, [p["name"] for p in subs][:12]))

    raise ParamNotFound("no param named %r on track %d slot %d; available: %s"
                        % (param, track, slot, [p["name"] for p in params][:20]))


def filter_params_by_name(params, query, limit=50):
    """Return params whose name contains ALL space-separated tokens in ``query``
    (case-insensitive). Sorted by name; capped at ``limit``. PURE.

    Essential for big generators (Serum/Vital expose hundreds of params) so the
    caller can locate 'filter cutoff' / 'osc a level' without dumping everything.
    """
    toks = [t for t in str(query or "").lower().split() if t]
    if not toks:
        return []
    hits = [p for p in params
            if all(t in str(p.get("name", "")).lower() for t in toks)]
    hits.sort(key=lambda p: str(p.get("name", "")).lower())
    return hits[: max(1, int(limit))]


class PluginParamSet(BaseModel):
    param: int | str = Field(description="Param index (int) or name (str).")
    value: float = Field(ge=0.0, le=1.0, description="Normalised 0..1.")


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "List plugins on a mixer track", **_RO})
    def fl_plugin_list(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
    ) -> dict:
        """List the filled effect slots (0-9) on a mixer track, with plugin names.

        We cannot load NEW plugins (FL API limit) -- this only reports plugins
        already present in the project."""
        return get_bridge().call(protocol.CMD_PLUGIN_LIST, {"track": track})

    @mcp.tool(annotations={"title": "Get plugin parameters", **_RO})
    def fl_plugin_get_params(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=-1, le=9,
            description="Mixer-track effect slot 0-9, OR -1 for the channel-rack "
                        "generator (then `track` is the CHANNEL index).")],
    ) -> dict:
        """Every named parameter of the plugin in this slot: index, name,
        normalised value (0..1) and FL's display string (e.g. '3.6dB',
        '500Hz'). Returns {"total", "params":[{"i","name","v","s"}, ...]}.

        slot=-1 addresses the channel-rack GENERATOR on `track` (a channel
        index) -- e.g. Serum, Vital, Sytrus -- exposing its full synth param
        set. Big synths return hundreds of params (paginated); use
        fl_plugin_find_params to search by name."""
        return fetch_all_pages(get_bridge(), protocol.CMD_PLUGIN_GET_PARAMS, "params",
                               {"track": track, "slot": slot})

    @mcp.tool(annotations={"title": "Set plugin parameter", **_WR})
    def fl_plugin_set_param(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=-1, le=9,
            description="Mixer-track effect slot 0-9, OR -1 for the channel-rack "
                        "generator (then `track` is the CHANNEL index).")],
        param: Annotated[int | str,
                         Field(description="Param index (int) or name (str, e.g. 'Decay time').")],
        value: Annotated[float, Field(ge=0.0, le=1.0, description="Normalised 0..1.")],
    ) -> dict:
        """Set one plugin parameter (normalised 0..1). ``param`` may be an
        index or a name; names are resolved from the live param list. slot=-1
        targets the channel-rack generator on `track` (a channel index). The
        change is logged and undo-able via fl_rollback_last_change. Returns
        before/after plus the resolved {index, name}."""
        bridge = get_bridge()
        idx, name = resolve_param_index(bridge, track, slot, param)
        scope = "plugin_param:%d:%d:%d" % (track, slot, idx)
        result = safety.safe_write(
            bridge, tool="plugin_set_param", scope=scope,
            command=protocol.CMD_PLUGIN_SET_PARAM,
            params={"track": track, "slot": slot, "param": idx, "value": value},
            build_restore=lambda b: {"command": protocol.CMD_PLUGIN_SET_PARAM,
                                     "params": {"track": track, "slot": slot,
                                                "param": idx, "value": b["v"]}})
        if isinstance(result, dict):
            result["resolved_param"] = {"index": idx, "name": name}
        return result

    @mcp.tool(annotations={"title": "Find plugin parameters by name", **_RO})
    def fl_plugin_find_params(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=-1, le=9,
            description="Mixer-track effect slot 0-9, OR -1 for the channel-rack "
                        "generator (then `track` is the CHANNEL index).")],
        query: Annotated[str, Field(
            description="Space-separated substrings; a param matches when ALL appear "
                        "in its name (case-insensitive), e.g. 'filter cutoff'.")],
        limit: Annotated[int, Field(ge=1, le=200, description="Max matches to return.")] = 50,
    ) -> dict:
        """Search a plugin/generator's parameters by name -- essential for big
        synths (Serum/Vital expose hundreds of params) where a full dump is
        unwieldy. Returns the matching {i,name,v,s} entries plus counts."""
        dump = fetch_all_pages(get_bridge(), protocol.CMD_PLUGIN_GET_PARAMS, "params",
                               {"track": track, "slot": slot})
        params = dump.get("params", [])
        matches = filter_params_by_name(params, query, limit)
        return {"track": track, "slot": slot, "query": query,
                "total_params": dump.get("total", len(params)),
                "match_count": len(matches), "params": matches}

    @mcp.tool(annotations={"title": "Set multiple plugin parameters (one undo)", **_WR})
    def fl_plugin_set_params(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=-1, le=9,
            description="Mixer-track effect slot 0-9, OR -1 for the channel-rack "
                        "generator (then `track` is the CHANNEL index).")],
        params: Annotated[list[PluginParamSet], Field(
            description="Params to set together, each {param (index/name), value 0..1}.")],
    ) -> dict:
        """Set several parameters at once as ONE reversible change -- a coherent
        patch move (e.g. shape an oscillator + filter + envelope together) that
        fl_rollback_last_change undoes in a single step. Each param may be an
        index or a name; values are normalised 0..1."""
        if not params:
            return {"ok": False, "error": "no params given"}
        bridge = get_bridge()
        resolved, writes = [], []
        for spec in params:
            idx, name = resolve_param_index(bridge, track, slot, spec.param)
            resolved.append({"index": idx, "name": name, "value": spec.value})
            writes.append({
                "snap_scope": "plugin_param:%d:%d:%d" % (track, slot, idx),
                "command": protocol.CMD_PLUGIN_SET_PARAM,
                "params": {"track": track, "slot": slot, "param": idx, "value": spec.value},
                "restore": (lambda b, i=idx: {"command": protocol.CMD_PLUGIN_SET_PARAM,
                                              "params": {"track": track, "slot": slot,
                                                         "param": i, "value": b["v"]}}),
            })
        result = safety.safe_write_group(bridge, tool="plugin_set_params",
                                         scope="plugin:%d:%d" % (track, slot), writes=writes)
        if isinstance(result, dict):
            result["resolved_params"] = resolved
        return result
