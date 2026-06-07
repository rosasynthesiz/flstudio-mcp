"""Mixing-intent MCP tools (Slice B).

High-level, musically-named EQ moves on Fruity Parametric EQ 2. Each intent
picks a FREE band, sets type+freq+gain+width together as ONE rollback unit
(`safety.safe_write_group`), and reports the actual readback value-strings so
the caller can confirm what landed (e.g. "Band 1 -> Peaking, 250Hz, -3.0dB").

Gain scales linearly with intensity: gain_dB = max_dB * intensity, so the
default intensity 0.5 gives half of an intent's full move (e.g. remove_mud at
0.5 = -3 dB; add_air at 0.7 = +4.2 dB). EQ2-specific -- not for other plugins.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from ..music import levels
from ..music import limiter_curves as lc
from ..music import proc3_curves as pc
from ..music import reverb_delay_curves as rd
from ..music.eq_curves import (
    TYPE_NORMS,
    db_to_norm,
    eq2_band_param_index,
    freq_to_norm,
    norm_to_db,
    width_to_norm,
)

EQ2_NAME_HINT = "parametric eq"  # substring match on the plugin name
_FREE_DB_EPS = 0.3  # |gain| below this == effectively flat == free

# intent -> target band config. max_db = gain at intensity 1.0 (None = no gain).
# freq_hz is fixed; freq_range scales lo..hi by intensity instead.
INTENTS = {
    "remove_mud": {"type": "peaking", "freq_hz": 250, "max_db": -6.0, "width_pct": 40},
    "add_air": {"type": "high_shelf", "freq_hz": 12000, "max_db": +6.0, "width_pct": None},
    "remove_harshness": {"type": "peaking", "freq_hz": 3000, "max_db": -6.0, "width_pct": 30},
    "add_presence": {"type": "peaking", "freq_hz": 5000, "max_db": +5.0, "width_pct": None},
    "high_pass": {
        "type": "high_pass",
        "freq_range": (40, 120),
        "max_db": None,
        "width_pct": 56.0,
        "order_norm": 0.0,
    },
    "low_pass": {
        "type": "low_pass",
        "freq_range": (18000, 5000),
        "max_db": None,
        "width_pct": 56.0,
        "order_norm": 0.0,
    },
}
_DEFAULT_WIDTH_PCT = 50.0


def _scan_bands(bridge, track, slot):
    """Read all 7 bands' type-string + gain(dB); flag the free ones."""
    bands = []
    for b in range(1, 8):
        t = bridge.call(
            protocol.CMD_PLUGIN_GET_PARAM,
            {"track": track, "slot": slot, "param": eq2_band_param_index(b, "type")},
        )
        lv = bridge.call(
            protocol.CMD_PLUGIN_GET_PARAM,
            {"track": track, "slot": slot, "param": eq2_band_param_index(b, "level")},
        )
        type_s = t.get("s") or ""
        gain_db = norm_to_db(lv.get("v") if lv.get("v") is not None else 0.5)
        free = type_s.strip().lower() == "disabled" or abs(gain_db) < _FREE_DB_EPS
        bands.append({"band": b, "type": type_s, "gain_db": round(gain_db, 1), "free": free})
    return bands


def _lerp(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, t))


def _plugin_name_at(bridge, track, slot):
    """Plugin name at a mixer slot, or None if empty."""
    listing = bridge.call(protocol.CMD_PLUGIN_LIST, {"track": track})
    return next((s["name"] for s in listing.get("slots", []) if s["slot"] == slot), None)


def _named_params(bridge, track, slot, max_index=None):
    """{name: {i, name, v, s}} for a plugin slot's named params.

    max_index caps the scan (VST wrappers report ~4240 slots but the real
    params sit at low indices) so we don't page the whole 4240 every call.
    """
    if max_index is None:
        params = fetch_all_pages(
            bridge, protocol.CMD_PLUGIN_GET_PARAMS, "params", {"track": track, "slot": slot}
        ).get("params", [])
    else:
        params, start = [], 0
        while start < max_index:
            page = bridge.call(
                protocol.CMD_PLUGIN_GET_PARAMS, {"track": track, "slot": slot, "start": start}
            )
            params.extend(page.get("params", []))
            nxt = page.get("next_start")
            if nxt is None or nxt <= start:
                break
            start = nxt
    return {p["name"]: p for p in params}


# Abstract compression-intent targets (plugin-agnostic). level_offset = how far
# below the measured PEAK to put the threshold when level-aware; blind_thr =
# the preset threshold used as fallback when transport is stopped.
def _comp_target(intent, intensity):
    L = _lerp
    if intent == "heavy_vocal_compression":
        return {
            "ratio": L(4, 8, intensity),
            "attack": 5.0,
            "release": 80.0,
            "makeup": L(3, 6, intensity),
            "style": "Vocal",
            "level_offset": 12.0,
            "blind_thr": L(-6, -14, intensity),
        }
    if intent == "gentle_compression":
        return {
            "ratio": L(1.5, 2.5, intensity),
            "attack": 20.0,
            "release": 150.0,
            "makeup": L(1, 2, intensity),
            "style": "Smooth",
            "level_offset": 4.0,
            "blind_thr": L(-4, -8, intensity),
        }
    if intent == "glue_drums":
        return {
            "ratio": L(2.5, 3.5, intensity),
            "attack": 30.0,
            "release": 120.0,
            "makeup": L(1, 3, intensity),
            "style": "Bus",
            "level_offset": 8.0,
            "blind_thr": L(-6, -10, intensity),
        }
    # punch -- slow attack lets the transient through, fast release
    return {
        "ratio": L(3, 5, intensity),
        "attack": 30.0,
        "release": 40.0,
        "makeup": L(1, 3, intensity),
        "style": "Punch",
        "level_offset": 6.0,
        "blind_thr": L(-6, -10, intensity),
    }


def _param_write(track, slot, idx, value):
    """One entry for safe_write_group (snapshot + set + restore-to-original)."""
    value = 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)
    return {
        "snap_scope": f"plugin_param:{track}:{slot}:{idx}",
        "command": protocol.CMD_PLUGIN_SET_PARAM,
        "params": {"track": track, "slot": slot, "param": idx, "value": value},
        "restore": lambda before: {
            "command": protocol.CMD_PLUGIN_SET_PARAM,
            "params": {
                "track": track,
                "slot": slot,
                "param": before["param"],
                "value": before["v"],
            },
        },
    }


def register(mcp: FastMCP) -> None:
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }
    _WR = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
        "safetyClass": "write-safe",
    }

    @mcp.tool(annotations={"title": "Apply an EQ mixing intent", **_WR})
    def fl_apply_eq_intent(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
        slot: Annotated[
            int, Field(ge=0, le=9, description="Effect slot of a Fruity Parametric EQ 2.")
        ],
        intent: Annotated[
            Literal[
                "remove_mud", "add_air", "remove_harshness", "add_presence", "high_pass", "low_pass"
            ],
            Field(description="Which EQ move to apply."),
        ],
        intensity: Annotated[
            float,
            Field(
                ge=0.0, le=1.0, description="0..1; scales gain (gain=max*intensity). Default 0.5."
            ),
        ] = 0.5,
    ) -> dict:
        """Apply a musical EQ move on a Fruity Parametric EQ 2 using a free band.
        Sets type/freq/gain/width as one undo-able group; returns the band used
        and FL's readback strings. Revert with fl_rollback_last_change.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()

        # 1. confirm the slot really holds a Parametric EQ 2 (curves are EQ2-only)
        pname = _plugin_name_at(bridge, track, slot)
        if not pname or EQ2_NAME_HINT not in pname.lower():
            return {
                "ok": False,
                "error": (
                    f"track {track} slot {slot} is {pname!r}, not a Fruity Parametric EQ 2; "
                    "these EQ curves don't apply to other plugins."
                ),
            }

        spec = INTENTS[intent]
        intensity = max(0.0, min(1.0, float(intensity)))

        # 2. find a free band
        bands = _scan_bands(bridge, track, slot)
        free = next((bd["band"] for bd in bands if bd["free"]), None)
        if free is None:
            return {
                "ok": False,
                "error": (
                    f"no free EQ band on track {track} slot {slot} (all 7 in use); "
                    "free one up or pick another approach."
                ),
                "bands": bands,
            }

        # 3. compute targets
        if "freq_range" in spec:
            lo, hi = spec["freq_range"]
            freq_hz = lo + (hi - lo) * intensity
        else:
            freq_hz = spec["freq_hz"]
        gain_db = (spec["max_db"] * intensity) if spec["max_db"] is not None else 0.0
        width_pct = spec["width_pct"] if spec["width_pct"] is not None else _DEFAULT_WIDTH_PCT

        # 4. one grouped, rollback-able write of type+freq+gain+width
        writes = [
            _param_write(track, slot, eq2_band_param_index(free, "type"), TYPE_NORMS[spec["type"]]),
            _param_write(track, slot, eq2_band_param_index(free, "freq"), freq_to_norm(freq_hz)),
            _param_write(track, slot, eq2_band_param_index(free, "level"), db_to_norm(gain_db)),
            _param_write(
                track, slot, eq2_band_param_index(free, "width"), width_to_norm(width_pct)
            ),
        ]
        if "order_norm" in spec:
            writes.append(
                _param_write(
                    track, slot, eq2_band_param_index(free, "order"), float(spec["order_norm"])
                )
            )
        res = safety.safe_write_group(
            bridge,
            tool="apply_eq_intent",
            scope=f"plugin_eq:{track}:{slot}:band{free}",
            writes=writes,
        )

        if res.get("dry_run"):
            res.update({"intent": intent, "intensity": intensity, "band": free})
            return res

        readback = {p.get("name"): p.get("s") for p in res.get("after", [])}
        return {
            "ok": True,
            "intent": intent,
            "intensity": intensity,
            "band": free,
            "set": {
                "type": spec["type"],
                "freq_hz": round(freq_hz),
                "gain_db": round(gain_db, 2),
                "width_pct": width_pct,
            },
            "readback": readback,
        }

    def _finish(res, *, plugin, intent, intensity, setp, warning, tool, scope):
        if res.get("dry_run"):
            res.update({"intent": intent, "intensity": intensity, "plugin": plugin})
            return res
        out = {
            "ok": True,
            "plugin": plugin,
            "intent": intent,
            "intensity": intensity,
            "set": setp,
            "readback": {p.get("name"): p.get("s") for p in res.get("after", [])},
        }
        if warning:
            out["warning"] = warning
        return out

    @mcp.tool(annotations={"title": "Apply a reverb intent", **_WR})
    def fl_apply_reverb_intent(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=0, le=9, description="Slot of a Fruity Reeverb 2.")],
        intent: Annotated[
            Literal[
                "more_space",
                "tighten_reverb",
                "darker_reverb",
                "brighter_reverb",
                "more_reverb",
                "less_reverb",
            ],
            Field(description="Which reverb move."),
        ],
        intensity: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5,
    ) -> dict:
        """Musical reverb moves on a Fruity Reeverb 2 (decay/wet/high-cut), as one
        undo-able group. Returns readback strings. Revert: fl_rollback_last_change.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        pname = _plugin_name_at(bridge, track, slot)
        if not pname or not any(k in pname.lower() for k in ("reeverb", "reverb")):
            return {
                "ok": False,
                "error": f"track {track} slot {slot} is {pname!r}, not a Fruity Reeverb 2.",
            }
        intensity = max(0.0, min(1.0, float(intensity)))
        P = _named_params(bridge, track, slot)
        writes, setp = [], {}

        def add(name, target_norm):
            writes.append(_param_write(track, slot, P[name]["i"], target_norm))

        if intent == "more_space":
            d = _lerp(1.5, 6.0, intensity)
            add("Decay time", rd.decay_to_norm(d))
            w = min(125.0, rd.norm_to_wet(P["Wet level"]["v"]) + 15.0)
            add("Wet level", rd.wet_to_norm(w))
            setp = {"decay_s": round(d, 2), "wet_pct": round(w)}
        elif intent == "tighten_reverb":
            d = _lerp(1.5, 0.6, intensity)
            add("Decay time", rd.decay_to_norm(d))
            w = max(0.0, rd.norm_to_wet(P["Wet level"]["v"]) - 10.0)
            add("Wet level", rd.wet_to_norm(w))
            setp = {"decay_s": round(d, 2), "wet_pct": round(w)}
        elif intent == "darker_reverb":
            # move the high-cut DOWN toward a dark ~2 kHz floor (works whether it
            # starts at Off or already partway down).
            new = _lerp(P["High cut"]["v"], rd.highcut_to_norm(2000.0), intensity)
            add("High cut", new)
            hz = rd.norm_to_highcut_hz(new)
            setp = {"high_cut": "Off" if hz is None else round(hz)}
        elif intent == "brighter_reverb":
            new = _lerp(P["High cut"]["v"], rd.HIGHCUT_OFF_NORM, intensity)
            add("High cut", new)
            hz = rd.norm_to_highcut_hz(new)
            setp = {"high_cut": "Off" if hz is None else round(hz)}
        elif intent == "more_reverb":
            w = min(125.0, rd.norm_to_wet(P["Wet level"]["v"]) + 30.0 * intensity)
            add("Wet level", rd.wet_to_norm(w))
            setp = {"wet_pct": round(w)}
        elif intent == "less_reverb":
            w = max(0.0, rd.norm_to_wet(P["Wet level"]["v"]) - 30.0 * intensity)
            add("Wet level", rd.wet_to_norm(w))
            setp = {"wet_pct": round(w)}

        res = safety.safe_write_group(
            bridge,
            tool="apply_reverb_intent",
            scope=f"plugin_reverb:{track}:{slot}",
            writes=writes,
        )
        return _finish(
            res,
            plugin=pname,
            intent=intent,
            intensity=intensity,
            setp=setp,
            warning=None,
            tool="apply_reverb_intent",
            scope=f"plugin_reverb:{track}:{slot}",
        )

    @mcp.tool(annotations={"title": "Apply a delay intent", **_WR})
    def fl_apply_delay_intent(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=0, le=9, description="Slot of a Fruity Delay.")],
        intent: Annotated[
            Literal[
                "longer_delay",
                "shorter_delay",
                "more_feedback",
                "less_feedback",
                "more_delay",
                "less_delay",
                "darker_delay",
                "brighter_delay",
            ],
            Field(description="Which delay move."),
        ],
        intensity: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5,
    ) -> dict:
        """Musical delay moves on a Fruity Delay (time division / feedback / wet /
        feedback-cut), as one undo-able group. Feedback is clamped <=100% unless
        intensity>0.9 (warns on self-oscillation risk). Returns readback strings.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        pname = _plugin_name_at(bridge, track, slot)
        if not pname or "delay" not in pname.lower():
            return {
                "ok": False,
                "error": f"track {track} slot {slot} is {pname!r}, not a Fruity Delay.",
            }
        intensity = max(0.0, min(1.0, float(intensity)))
        P = _named_params(bridge, track, slot)
        writes, setp, warning = [], {}, None

        def add(name, target_norm):
            writes.append(_param_write(track, slot, P[name]["i"], target_norm))

        if intent in ("longer_delay", "shorter_delay"):
            cur = P["Time"]["v"]
            before = rd.DIVISIONS[rd.nearest_division_index(cur)][0]
            label, n = rd.step_division(cur, +1 if intent == "longer_delay" else -1)
            add("Time", n)
            setp = {"division_before": before, "division_after": label}
        elif intent in ("more_feedback", "less_feedback"):
            cur = rd.norm_to_feedback(P["Feedback level"]["v"])
            if intent == "more_feedback":
                allow = intensity > 0.9
                tgt = min(cur + 25.0 * intensity, 125.0 if allow else 100.0)
                if tgt > 100.0:
                    warning = f"feedback {tgt:.0f}% >100%: self-oscillation risk"
                add("Feedback level", rd.feedback_to_norm(tgt, allow_oscillation=allow))
            else:
                tgt = max(0.0, cur - 25.0 * intensity)
                add("Feedback level", rd.feedback_to_norm(tgt))
            setp = {"feedback_pct": round(tgt, 1)}
        elif intent in ("more_delay", "less_delay"):
            cur = rd.norm_to_delay_pct(P["Output wet"]["v"])
            tgt = (
                min(100.0, cur + 25.0 * intensity)
                if intent == "more_delay"
                else max(0.0, cur - 25.0 * intensity)
            )
            add("Output wet", rd.delay_pct_to_norm(tgt))
            setp = {"output_wet_pct": round(tgt)}
        elif intent in ("darker_delay", "brighter_delay"):
            cur = rd.norm_to_cutoff_hz(P["Feedback cutoff"]["v"])
            tgt = (
                _lerp(cur, 1500.0, intensity)
                if intent == "darker_delay"
                else _lerp(cur, 21985.0, intensity)
            )
            add("Feedback cutoff", rd.cutoff_hz_to_norm(tgt))
            setp = {"feedback_cutoff_hz": round(tgt)}

        res = safety.safe_write_group(
            bridge,
            tool="apply_delay_intent",
            scope=f"plugin_delay:{track}:{slot}",
            writes=writes,
        )
        return _finish(
            res,
            plugin=pname,
            intent=intent,
            intensity=intensity,
            setp=setp,
            warning=warning,
            tool="apply_delay_intent",
            scope=f"plugin_delay:{track}:{slot}",
        )

    @mcp.tool(annotations={"title": "Get track level (dB)", **_RO})
    def fl_get_track_level(
        track: Annotated[int, Field(ge=0)],
        samples: Annotated[int, Field(ge=1, le=100, description="Reads over ~samples*100ms.")] = 20,
    ) -> dict:
        """Measure a mixer track's level by sampling meter peaks over a short
        window. Requires PLAYBACK -- returns playing=False (avg/peak null) when
        stopped/silent. {track, playing, avg_db, peak_db}.

        Safety: Read-Only.
        """
        return levels.measure_track_level(get_bridge(), track, samples=samples)

    @mcp.tool(annotations={"title": "Apply a compression intent", **_WR})
    def fl_apply_compression_intent(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[
            int, Field(ge=0, le=9, description="Slot of a Fruity Limiter OR FabFilter Pro-C.")
        ],
        intent: Annotated[
            Literal["heavy_vocal_compression", "gentle_compression", "glue_drums", "punch"],
            Field(description="Which compression move."),
        ],
        intensity: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5,
        level_aware: Annotated[
            bool,
            Field(
                description="Measure track level (during playback) and set threshold relative to "
                "it; falls back to the preset threshold if stopped/silent."
            ),
        ] = True,
    ) -> dict:
        """Compress via Fruity Limiter (COMP section) or FabFilter Pro-C. ALWAYS
        sets ratio AND threshold together; ratio/attack/release/makeup (+ Pro-C
        Style) per intent, as ONE rollback unit. When level_aware and the track
        is playing, threshold is set relative to the MEASURED peak (a smart
        starting point, not exact gain-reduction); stopped -> preset fallback +
        a note. Returns readback + the measured level / chosen threshold.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        pname = _plugin_name_at(bridge, track, slot)
        low = (pname or "").lower()
        is_proc = ("pro-c" in low) or ("pro c" in low)
        is_limiter = "limiter" in low
        if not (is_proc or is_limiter):
            return {
                "ok": False,
                "error": (
                    f"track {track} slot {slot} is {pname!r}, not a supported compressor "
                    "(Fruity Limiter or FabFilter Pro-C)."
                ),
            }
        intensity = max(0.0, min(1.0, float(intensity)))
        T = _comp_target(intent, intensity)

        # threshold: level-aware (peak - offset) when playing, else preset.
        measured, note, matched = None, None, False
        threshold_db = T["blind_thr"]
        if level_aware:
            measured = levels.measure_track_level(bridge, track)
            if measured["playing"]:
                # Convert post-fader peak to pre-fader peak by subtracting fader volume
                track_info = bridge.call(protocol.CMD_MIXER_GET_TRACK, {"index": track})
                vol_db = track_info.get("vol_db", 0.0)
                pre_fader_peak = measured["peak_db"] - vol_db

                threshold_db = max(-60.0, min(0.0, pre_fader_peak - T["level_offset"]))
                matched = True
            else:
                note = (
                    "transport stopped/silent -- used preset threshold; "
                    "play + re-run for level-matched"
                )

        # plugin adapter: abstract targets -> (param name, norm) for THIS plugin
        if is_proc:
            pairs = [
                ("Ratio", pc.ratio_to_norm(T["ratio"])),
                ("Threshold", pc.threshold_to_norm(threshold_db)),
                ("Attack", pc.attack_ms_to_norm(T["attack"])),
                ("Release", pc.release_ms_to_norm(T["release"])),
                ("Output Level", pc.makeup_db_to_norm(T["makeup"])),
                ("Style", pc.style_to_norm(T["style"])),
                ("Auto Gain", 0.0),
            ]  # off so manual makeup (Output Level) applies
        else:
            pairs = [
                ("Comp ratio", lc.ratio_to_norm(T["ratio"])),
                ("Comp threshold", lc.threshold_to_norm(threshold_db)),
                ("Comp attack time", lc.attack_ms_to_norm(T["attack"])),
                ("Comp release time", lc.release_ms_to_norm(T["release"])),
                ("Gain", lc.makeup_db_to_norm(T["makeup"])),
            ]

        P = _named_params(bridge, track, slot, max_index=256)
        missing = [nm for nm, _ in pairs if nm not in P]
        if missing:
            return {"ok": False, "error": f"params not found on {pname!r}: {missing}"}
        writes = [_param_write(track, slot, P[nm]["i"], norm) for nm, norm in pairs]

        res = safety.safe_write_group(
            bridge,
            tool="apply_compression_intent",
            scope=f"plugin_comp:{track}:{slot}",
            writes=writes,
        )
        setp = {
            "ratio": "{:.1f}:1".format(T["ratio"]),
            "threshold_db": round(threshold_db, 1),
            "attack_ms": T["attack"],
            "release_ms": T["release"],
            "makeup_db": round(T["makeup"], 1),
        }
        if is_proc:
            setp["style"] = T["style"]
        out = _finish(
            res,
            plugin=pname,
            intent=intent,
            intensity=intensity,
            setp=setp,
            warning=None,
            tool="apply_compression_intent",
            scope=f"plugin_comp:{track}:{slot}",
        )
        if isinstance(out, dict) and out.get("ok"):
            out["level"] = {
                "aware": level_aware,
                "matched": matched,
                "measured": measured,
                "chosen_threshold_db": round(threshold_db, 1),
                "mode": (
                    "level-matched (smart starting point, not exact GR)"
                    if matched
                    else ("preset-fallback" if level_aware else "preset")
                ),
            }
            if note:
                out["note"] = note
        return out
