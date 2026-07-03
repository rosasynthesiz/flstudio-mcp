"""Runtime parameter calibration + persistent cache -- the engine behind
unit-targeted control of ANY plugin.

Flow (generalises the offline scripts/calibration/*.py into a live tool):
  1. sweep a parameter across normalised 0..1, reading FL's display string at
     each step and parsing it to (value, unit);
  2. build a monotonic norm<->value table so callers can convert between a
     musical target ("2 kHz", "-6 dB") and the normalised value FL wants;
  3. cache the table on disk, keyed by a signature (plugin name + param count +
     a small sample), and re-validate on load so a plugin update invalidates it.

The sweep snapshots the parameter first and restores it after, so calibration
is a transient probe -- it never leaves the plugin changed.

Pure helpers (build/interp/signature/cache IO) are unit-tested; the sweep is
tested against a fake bridge.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .. import protocol
from .value_parse import parse_value_string, to_canonical

CACHE_DIR = Path(os.environ.get("FLSTUDIO_MCP_CACHE_DIR",
                                str(Path.home() / ".flstudio-mcp" / "calibration")))

DEFAULT_STEPS = 11


# ---------------------------------------------------------------------------
# Pure: interpolation over a monotonic (norm, value) table
# ---------------------------------------------------------------------------
def _interp(q, pts, xi, yi):
    if not pts:
        return None
    if q <= pts[0][xi]:
        return pts[0][yi]
    if q >= pts[-1][xi]:
        return pts[-1][yi]
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        if q <= b[xi]:
            span = b[xi] - a[xi]
            t = (q - a[xi]) / span if span else 0.0
            return a[yi] + t * (b[yi] - a[yi])
    return pts[-1][yi]


def build_curve(table) -> dict:
    """From a list of (norm, value) pairs (value may be None for unparsable
    steps), build a monotonic-ascending curve usable both directions. PURE.

    Drops None values, sorts by norm, and keeps only points that keep ``value``
    monotonic (non-decreasing) so the inverse lookup is well-defined. Returns
    ``{"points": [(norm, value)...], "monotonic": bool, "n": int}``."""
    pairs = sorted((float(n), float(v)) for n, v in table if v is not None)
    mono, last = [], None
    for n, v in pairs:
        if last is None or v >= last:
            mono.append((n, v))
            last = v
    monotonic = len(mono) == len(pairs) and len(pairs) >= 2
    return {"points": mono, "monotonic": monotonic, "n": len(mono)}


def norm_to_value(curve, norm):
    pts = curve.get("points") or []
    return _interp(float(norm), pts, 0, 1)


def value_to_norm(curve, value):
    """Invert: musical value -> normalised 0..1 (clamped to the calibrated range)."""
    pts = curve.get("points") or []
    return _interp(float(value), pts, 1, 0)


# ---------------------------------------------------------------------------
# Pure: cache signature + disk IO
# ---------------------------------------------------------------------------
def signature(plugin_name: str, param_count: int, sample_names) -> str:
    """Stable key for a plugin's param layout. A plugin update that changes the
    count or the sampled names invalidates the cache."""
    sample = "|".join(str(s) for s in (sample_names or [])[:8])
    blob = "%s\x00%d\x00%s" % (plugin_name or "", int(param_count), sample)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _cache_file(sig: str) -> Path:
    return CACHE_DIR / ("%s.json" % sig)


def load_cache(sig: str) -> dict | None:
    try:
        f = _cache_file(sig)
        if f.is_file():
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def save_cache(sig: str, data: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = _cache_file(sig)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Bridge-driven: sweep a parameter and calibrate it
# ---------------------------------------------------------------------------
def sweep_param(bridge, track, slot, index, steps=DEFAULT_STEPS):
    """Sweep ``index`` across 0..1 in ``steps`` points, reading + parsing the
    display string at each. Snapshots first and RESTORES after. Returns
    ``{"table": [(norm, value)...], "unit": str|None, "raw": [(norm, string)...]}``.
    """
    steps = max(2, int(steps))
    orig = bridge.call(protocol.CMD_PLUGIN_GET_PARAM,
                       {"track": track, "slot": slot, "param": index})
    orig_v = orig.get("v", 0.0)
    table, raw, units = [], [], {}
    try:
        for k in range(steps):
            norm = round(k / (steps - 1), 6)
            bridge.call(protocol.CMD_PLUGIN_SET_PARAM,
                        {"track": track, "slot": slot, "param": index, "value": norm})
            # Read the display string on a FRESH call: FL commits many plugin
            # writes on a LATER script-tick, so the SET response's own "s" can be
            # the stale pre-write value. A separate GET reads the settled value.
            got = bridge.call(protocol.CMD_PLUGIN_GET_PARAM,
                              {"track": track, "slot": slot, "param": index})
            s = got.get("s")
            parsed = parse_value_string(s)
            val, unit = to_canonical(parsed["value"], parsed["unit"]) \
                if parsed["value"] is not None else (None, None)
            if unit:
                units[unit] = units.get(unit, 0) + 1
            table.append((norm, val))
            raw.append((norm, parsed["raw"]))
    finally:
        bridge.call(protocol.CMD_PLUGIN_SET_PARAM,
                    {"track": track, "slot": slot, "param": index, "value": orig_v})
    unit = max(units, key=units.get) if units else None
    return {"table": table, "unit": unit, "raw": raw}


def calibrate_param(bridge, track, slot, index, *, plugin_name="", param_count=0,
                    sample_names=None, steps=DEFAULT_STEPS, use_cache=True):
    """Calibrate one param: return {unit, curve, cached}. Uses the on-disk cache
    keyed by (plugin_name, param_count, sample) when available."""
    sig = signature(plugin_name, param_count, sample_names)
    key = "%s:%d:%d" % (sig, slot, index)
    if use_cache:
        cached = load_cache(sig)
        if cached and key in cached:
            entry = cached[key]
            return {"unit": entry.get("unit"), "curve": entry.get("curve"),
                    "cached": True}
    swept = sweep_param(bridge, track, slot, index, steps=steps)
    curve = build_curve(swept["table"])
    entry = {"unit": swept["unit"], "curve": curve}
    if use_cache:
        cached = load_cache(sig) or {}
        cached[key] = entry
        save_cache(sig, cached)
    return {"unit": swept["unit"], "curve": curve, "cached": False}
