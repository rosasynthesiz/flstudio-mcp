"""Phase 1B MCP tools: plugin parameter control.

- fl_plugin_list(track)              -> filled effect slots on a mixer track
- fl_plugin_get_params(track, slot)  -> every named param (name, value, string)
- fl_plugin_set_param(track, slot, param, value)
       ``param`` may be an int index OR a param name (e.g. "Decay time").
       Names are resolved server-side from the live param list. The write
       routes through ``safety.safe_write`` so it is logged + rollback-able,
       and is VERIFIED: a re-read that misses the requested value (by more
       than +-0.02) triggers up to 3 re-writes 0.4 s apart before the answer
       reports ``verified`` / ``attempts`` / ``hint``.
- fl_plugin_set_params(track, slot, writes=[{"param","value"}, ...])
       the same thing for several params of ONE plugin: one rollback unit
       (``safety.safe_write_group``), writes paced 0.4 s apart, per-param
       verification, one changelog entry.

Native FL plugins (Fruity Parametric EQ 2, Reeverb 2, ...) expose real param
names and small counts, so name-based addressing is reliable for them. VST/AU
wrappers can report thousands of generic slots; for those prefer int indices.

Values are NORMALISED 0..1 (FL's setParamValue domain). The display string
from fl_plugin_get_params (e.g. '3.6dB', '500Hz') tells you what a given
normalised value maps to -- there is no generic unit->normalised conversion.

Writes are VERIFIED on FL 26 rather than assumed: levels/gains take an
arbitrary 0..1 value, stepped params (filter types, orders, selectors) snap to
their own grid steps, some params (EQ2 band widths) ignore writes entirely,
and an open plugin window (pickup mode) did not block script writes in our
test. Whatever the cause, a miss is retried and then reported honestly as
``verified: false`` with ``after`` showing what FL actually holds.
"""

from __future__ import annotations

from typing import Annotated, Union

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge

# How far a re-read may sit from the requested normalised value and still
# count as "landed" (FL rounds some params on the way back out).
_VERIFY_TOL = 0.02
# Live pacing between writes/retries -- the session-measured 0.3-0.5 s window.
# Not the 0.06 s toggle coalescing window in safety._verify_retry.
_WRITE_DELAY = 0.4
# Re-writes after the first attempt (so up to 4 writes total, worst case).
_MAX_ATTEMPTS = 3
_MAX_BATCH = 16
_HINT = ("FL did not land this value. Measured on FL 26: some params ignore "
         "writes entirely (EQ2 band widths), stepped params (types, orders, "
         "selectors) snap to their own grid steps, and only some continuous "
         "params (levels, gains) take an arbitrary 0..1 value. The plugin's "
         "window being open did NOT block writes in our test (pickup mode "
         "affects controller gestures). after.v / after.s show what FL "
         "actually holds -- trust those over the request.")


class ParamNotFound(ValueError):
    """Raised when a param name cannot be resolved to a single index."""


class ParamWrite(BaseModel):
    """One entry of ``fl_plugin_set_params.writes``."""

    param: Annotated[int | str,
                     Field(description="Param index (int) or name (str, e.g. 'Band 1 level').")]
    value: Annotated[float, Field(ge=0.0, le=1.0, description="Normalised 0..1.")]


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


def _param_scope(track: int, slot: int, idx: int) -> str:
    return f"plugin_param:{track}:{slot}:{idx}"


def _param_write(track: int, slot: int, idx: int, value: float) -> dict:
    """One ``safe_write_group`` entry: set this param, restore its old value."""
    return {
        "snap_scope": _param_scope(track, slot, idx),
        "command": protocol.CMD_PLUGIN_SET_PARAM,
        "params": {"track": track, "slot": slot, "param": idx, "value": value},
        # defaults bind the per-write identity; ``b`` is the snapshot
        "restore": lambda b, _t=track, _s=slot, _i=idx: {
            "command": protocol.CMD_PLUGIN_SET_PARAM,
            "params": {"track": _t, "slot": _s, "param": _i, "value": b["v"]}},
    }


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
        slot: Annotated[int, Field(ge=0, le=9, description="Effect slot index 0-9.")],
    ) -> dict:
        """Every named parameter of the plugin in this slot: index, name,
        normalised value (0..1) and FL's display string (e.g. '3.6dB',
        '500Hz'). Returns {"total", "params":[{"i","name","v","s"}, ...]}."""
        return fetch_all_pages(get_bridge(), protocol.CMD_PLUGIN_GET_PARAMS, "params",
                               {"track": track, "slot": slot})

    @mcp.tool(annotations={"title": "Set plugin parameter", **_WR})
    def fl_plugin_set_param(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=0, le=9)],
        param: Annotated[Union[int, str],
                         Field(description="Param index (int) or name (str, e.g. 'Decay time').")],
        value: Annotated[float, Field(ge=0.0, le=1.0, description="Normalised 0..1.")],
    ) -> dict:
        """Set one plugin parameter (normalised 0..1), then VERIFY it landed.

        ``param`` may be an index or a name; names are resolved from the live
        param list. The change is logged ONCE and undo-able via
        fl_rollback_last_change. Returns before/after (unchanged shape) plus
        the resolved {index, name} and, because the value is checked on a
        fresh re-read, ``verified: bool`` and ``attempts: int`` (1 = it stuck
        first try); ``attempts`` can reach 4 (1 write + 3 retries) and a
        ``hint`` explains a ``verified: false``.

        RECIPE (FL API limits, measured on FL 26): ``verified`` is the source
        of truth, not the request. Levels/gains take an arbitrary 0..1 value;
        stepped params (filter types, orders, selectors) snap to their own
        grid, so an off-grid request comes back ``verified: false`` with the
        snapped value in ``after``; some params (EQ2 band widths) ignore
        writes entirely. An open plugin window (pickup mode) did not block
        script writes in our test. Values are the normalised 0..1 domain shown
        by fl_plugin_get_params -- read ``after.s`` for the display string.
        """
        bridge = get_bridge()
        idx, name = resolve_param_index(bridge, track, slot, param)
        w = _param_write(track, slot, idx, value)
        result = safety.safe_write(
            bridge, tool="plugin_set_param", scope=w["snap_scope"],
            command=w["command"], params=w["params"], build_restore=w["restore"],
            verify_value=("v", value, _VERIFY_TOL),
            verify_attempts=_MAX_ATTEMPTS, verify_delay=_WRITE_DELAY,
        )
        if isinstance(result, dict):
            result["resolved_param"] = {"index": idx, "name": name}
            if result.get("verified") is False:
                result["hint"] = _HINT
        return result

    @mcp.tool(annotations={"title": "Set several plugin parameters", **_WR})
    def fl_plugin_set_params(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=0, le=9)],
        writes: Annotated[list[ParamWrite],
                          Field(min_length=1, max_length=_MAX_BATCH,
                                description=f"1..{_MAX_BATCH} {{param, value}} "
                                            "entries, all for this ONE plugin.")],
    ) -> dict:
        """Set several parameters of ONE plugin as a single rollback unit.

        Every entry of ``writes`` (``{param, value}``; ``param`` is an index
        or a name) is written through ONE safety.safe_write_group call: one
        changelog entry, so fl_rollback_last_change restores ALL of them back
        to their original values in one step. Writes are paced 0.4 s apart
        (FL drops back-to-back writes), each is re-read and retried up to 3
        times if it did not land, and ``results`` reports per-param
        ``{param, ok, verified, requested, attempts, before, after}``.

        RECIPE: same FL 26 limits as fl_plugin_set_param -- trust ``verified``,
        not the request: stepped params snap to their grid, some params ignore
        writes entirely, values are the normalised 0..1 domain (see that
        tool's docstring for the full map). Prefer this over repeated
        fl_plugin_set_param calls whenever 2+ knobs change: it is one undo
        step and one paced burst instead of several. Worst case (every param
        refused) is ~1.6 s of retries per entry, so a full 16-entry batch can
        take ~25 s -- keep batches focused on the knobs you mean to change.
        """
        bridge = get_bridge()
        resolved = [resolve_param_index(bridge, track, slot, w.param)
                    for w in writes]
        res = safety.safe_write_group(
            bridge, tool="plugin_set_params",
            scope=f"plugin_params:{track}:{slot}",
            writes=[_param_write(track, slot, idx, w.value)
                    for w, (idx, _n) in zip(writes, resolved, strict=True)],
            delay=_WRITE_DELAY,
            verify_values=[("v", w.value, _VERIFY_TOL) for w in writes],
            verify_attempts=_MAX_ATTEMPTS, verify_delay=_WRITE_DELAY,
        )
        if not isinstance(res, dict) or res.get("dry_run"):
            return res                    # dry-run answers carry `planned` only
        ver, att = res.get("verified") or [], res.get("attempts") or []
        befores, afters = res.get("before") or [], res.get("after") or []
        results = []
        for k, (idx, name) in enumerate(resolved):
            results.append({
                "param": {"index": idx, "name": name},
                "requested": writes[k].value,
                "ok": bool(res.get("ok")),
                "verified": ver[k] if k < len(ver) else None,
                "attempts": att[k] if k < len(att) else None,
                "before": befores[k] if k < len(befores) else None,
                "after": afters[k] if k < len(afters) else None,
            })
        out = {"ok": True, "count": len(results), "results": results}
        if any(r["verified"] is False for r in results):
            out["hint"] = _HINT
        return out
