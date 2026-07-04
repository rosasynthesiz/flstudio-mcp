"""Generic deep VST/AU control tools -- overview, calibration, unit-targeted set.

Built entirely on the EXISTING plugin-param commands (get/set/list params), so
no new controller handlers are needed. Works for mixer-track effects (slot 0-9)
and channel-rack generators (slot=-1). This is the layer that lets an LLM
control any installed plugin deeply: see a digestible role-grouped overview,
calibrate a param's real units on the fly, then set it to a musical target
("cutoff = 2 kHz") -- degrading to normalised control when a plugin is opaque.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from ..music import calibration as cal
from ..music import vst_intents as vin
from ..music import vst_params as vpm
from .plugin import resolve_param_index

_SLOT = Field(ge=-1, le=9, description="Mixer-track effect slot 0-9, OR -1 for the "
              "channel-rack generator (then `track` is the CHANNEL index).")


def _first_page(bridge, track, slot):
    """One page of params -> (plugin_name, total, first_params)."""
    page = bridge.call(protocol.CMD_PLUGIN_GET_PARAMS,
                       {"track": track, "slot": slot, "start": 0})
    return page.get("plugin", ""), page.get("total", 0), page.get("params", [])


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
    _WR = {"readOnlyHint": False, "destructiveHint": False,
           "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "Plugin overview (grouped + controllability)", **_RO})
    def fl_plugin_overview(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, _SLOT],
        per_role: Annotated[int, Field(ge=1, le=20,
            description="Sample params to show per role.")] = 6,
    ) -> dict:
        """A digestible map of a plugin/generator: parameters grouped by musical
        role (oscillator/filter/envelope/lfo/amp/fx/...), plus a controllability
        tier (full / partial / opaque) so you know whether unit-targeted control
        or raw normalised nudging is appropriate. Ideal first call for a big
        synth (Serum/Vital) before diving into specific params."""
        bridge = get_bridge()
        plugin, total, _ = _first_page(bridge, track, slot)
        dump = fetch_all_pages(bridge, protocol.CMD_PLUGIN_GET_PARAMS, "params",
                               {"track": track, "slot": slot})
        params = dump.get("params", [])
        groups = vpm.group_params_by_role(params)
        exposure = vpm.classify_param_exposure(params)
        roles = {role: {"count": len(items),
                        "sample": [{"i": p["i"], "name": p["name"], "s": p.get("s", "")}
                                   for p in items[:per_role]]}
                 for role, items in sorted(groups.items(), key=lambda kv: -len(kv[1]))}
        return {"track": track, "slot": slot, "plugin": plugin,
                "param_count": dump.get("total", total),
                "controllability": exposure, "roles": roles}

    @mcp.tool(annotations={"title": "Calibrate a plugin parameter", **_WR})
    def fl_plugin_calibrate_param(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, _SLOT],
        param: Annotated[int | str, Field(description="Param index or name.")],
        steps: Annotated[int, Field(ge=3, le=41,
            description="Sweep resolution (more = finer curve).")] = 11,
    ) -> dict:
        """Learn a parameter's real-unit mapping by sweeping it 0..1 and reading
        FL's display string at each step (then restoring it). Returns the unit
        (dB/Hz/ms/%/ratio/...) and a norm<->value curve, cached on disk per
        plugin. Enables fl_plugin_set_param_value. The param is left unchanged."""
        bridge = get_bridge()
        idx, name = resolve_param_index(bridge, track, slot, param)
        plugin, total, first = _first_page(bridge, track, slot)
        res = cal.calibrate_param(bridge, track, slot, idx, plugin_name=plugin,
                                  param_count=total, sample_names=[p["name"] for p in first],
                                  steps=steps)
        curve = res.get("curve") or {}
        return {"resolved_param": {"index": idx, "name": name}, "plugin": plugin,
                "unit": res.get("unit"), "monotonic": curve.get("monotonic", False),
                "points": curve.get("points", []), "cached": res.get("cached", False)}

    @mcp.tool(annotations={"title": "Set a plugin parameter to a real-unit value", **_WR})
    def fl_plugin_set_param_value(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, _SLOT],
        param: Annotated[int | str, Field(description="Param index or name.")],
        target: Annotated[float, Field(description="Desired value in the param's real "
                          "unit (e.g. 2000 for 2 kHz cutoff, -6 for -6 dB).")],
        steps: Annotated[int, Field(ge=3, le=41)] = 11,
    ) -> dict:
        """Set a parameter to a MUSICAL target in its real unit (Hz/dB/ms/%/...),
        auto-calibrating first (cached). Falls back with a clear message if the
        plugin is opaque or the param isn't monotonic -- then use
        fl_plugin_set_param with a normalised 0..1 value instead. Reversible via
        fl_rollback_last_change; reports the achieved display string."""
        bridge = get_bridge()
        idx, name = resolve_param_index(bridge, track, slot, param)
        plugin, total, first = _first_page(bridge, track, slot)
        res = cal.calibrate_param(bridge, track, slot, idx, plugin_name=plugin,
                                  param_count=total, sample_names=[p["name"] for p in first],
                                  steps=steps)
        curve = res.get("curve") or {}
        if not curve.get("monotonic") or not curve.get("points"):
            return {"ok": False, "resolved_param": {"index": idx, "name": name},
                    "unit": res.get("unit"),
                    "error": "parameter is not cleanly calibratable (opaque or "
                             "non-monotonic display values); set it normalised via "
                             "fl_plugin_set_param instead."}
        norm = max(0.0, min(1.0, float(cal.value_to_norm(curve, target))))
        scope = "plugin_param:%d:%d:%d" % (track, slot, idx)
        result = safety.safe_write(
            bridge, tool="plugin_set_param_value", scope=scope,
            command=protocol.CMD_PLUGIN_SET_PARAM,
            params={"track": track, "slot": slot, "param": idx, "value": norm},
            build_restore=lambda b: {"command": protocol.CMD_PLUGIN_SET_PARAM,
                                     "params": {"track": track, "slot": slot,
                                                "param": idx, "value": b["v"]}})
        if isinstance(result, dict):
            after = bridge.call(protocol.CMD_PLUGIN_GET_PARAM,
                                {"track": track, "slot": slot, "param": idx})
            result["resolved_param"] = {"index": idx, "name": name}
            result["target"] = target
            result["unit"] = res.get("unit")
            result["applied_norm"] = round(norm, 4)
            result["achieved"] = after.get("s", "")
        return result

    @mcp.tool(annotations={"title": "Apply a semantic plugin intent", **_WR})
    def fl_plugin_intent(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, _SLOT],
        intent: Annotated[str, Field(description="Musical move: brighter, darker, "
            "more_resonance, less_resonance, more_attack, less_attack, "
            "slower_release, faster_release, wider, narrower, more_drive, less_drive.")],
        amount: Annotated[float, Field(ge=0.0, le=1.0,
            description="Strength 0..1 (0.5 = moderate).")] = 0.5,
    ) -> dict:
        """Shape ANY plugin by intent, without knowing its param names: locate
        the relevant knob by keyword (e.g. 'brighter' -> filter cutoff),
        calibrate it, and nudge it in the right direction/amount. Reversible via
        fl_rollback_last_change. Returns the param it moved + achieved value.
        Falls back with a clear message if no matching param or it's opaque."""
        spec = vin.resolve_intent(intent)
        if not spec:
            return {"ok": False, "error": "unknown intent %r" % intent,
                    "valid_intents": vin.list_intents()}
        bridge = get_bridge()
        plugin, total, first = _first_page(bridge, track, slot)
        dump = fetch_all_pages(bridge, protocol.CMD_PLUGIN_GET_PARAMS, "params",
                               {"track": track, "slot": slot})
        params = dump.get("params", [])
        target_param = vin.pick_param(params, spec["keywords"])
        if not target_param:
            return {"ok": False, "intent": intent, "plugin": plugin,
                    "error": "no parameter matching %s found on %r; try "
                             "fl_plugin_find_params to locate it manually."
                             % (list(spec["keywords"]), plugin)}
        idx = int(target_param["i"])
        res = cal.calibrate_param(bridge, track, slot, idx, plugin_name=plugin,
                                  param_count=total, sample_names=[p["name"] for p in first])
        curve = res.get("curve") or {}
        pts = curve.get("points") or []
        if not curve.get("monotonic") or not pts:
            return {"ok": False, "intent": intent, "plugin": plugin,
                    "param": target_param.get("name"),
                    "error": "target param isn't cleanly calibratable; adjust it "
                             "manually via fl_plugin_set_param."}
        cur_norm = target_param.get("v", 0.0)
        current_value = cal.norm_to_value(curve, cur_norm)
        vrange = (pts[0][1], pts[-1][1])
        new_value = vin.relative_target(current_value, spec, amount, vrange)
        norm = max(0.0, min(1.0, float(cal.value_to_norm(curve, new_value))))
        scope = "plugin_param:%d:%d:%d" % (track, slot, idx)
        result = safety.safe_write(
            bridge, tool="plugin_intent", scope=scope,
            command=protocol.CMD_PLUGIN_SET_PARAM,
            params={"track": track, "slot": slot, "param": idx, "value": norm},
            build_restore=lambda b: {"command": protocol.CMD_PLUGIN_SET_PARAM,
                                     "params": {"track": track, "slot": slot,
                                                "param": idx, "value": b["v"]}})
        if isinstance(result, dict):
            after = bridge.call(protocol.CMD_PLUGIN_GET_PARAM,
                                {"track": track, "slot": slot, "param": idx})
            result["intent"] = intent
            result["param"] = {"index": idx, "name": target_param.get("name")}
            result["unit"] = res.get("unit")
            result["from_value"] = round(current_value, 3)
            result["to_value"] = round(new_value, 3)
            result["achieved"] = after.get("s", "")
        return result
