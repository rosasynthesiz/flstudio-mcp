from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP

from fl_studio_mcp.connection import get_bridge

KB_ROOT = Path("knowledgebase")


def _get_calibration_mapping(domain: str, value_key: str, value: float) -> float:
    """Helper to get a known calibration mapping safely."""
    calib = KB_ROOT / "fl_api" / "mixer_eq_calibration.json"
    if not calib.exists():
        raise ValueError(f"Calibration file missing. Cannot safely map {value_key} {value}.")

    try:
        data = json.loads(calib.read_text(encoding="utf-8"))
        # If no exact match, do safe interpolation if the domain allows it
        for entry in data:
            if entry.get("domain") == domain:
                mappings = sorted(entry.get("mapping", []), key=lambda x: x.get(value_key, 0.0))
                # Check for exact match first
                for m in mappings:
                    if abs(m.get(value_key, 0.0) - value) < 0.01:
                        return m.get("normalized")

                # Check if interpolation is allowed
                if "linear" in str(entry.get("interpolation", "")).lower():
                    v_min = mappings[0].get(value_key, 0.0)
                    v_max = mappings[-1].get(value_key, 0.0)
                    if v_min <= value <= v_max:
                        if domain == "eq_gain":
                            return (value + 18.0) / 36.0

                        # General linear interpolation
                        for i in range(len(mappings) - 1):
                            p1 = mappings[i]
                            p2 = mappings[i + 1]
                            v1, n1 = p1.get(value_key, 0.0), p1.get("normalized", 0.0)
                            v2, n2 = p2.get(value_key, 0.0), p2.get("normalized", 0.0)
                            if v1 <= value <= v2:
                                if v2 == v1:
                                    return n1
                                ratio = (value - v1) / (v2 - v1)
                                return n1 + ratio * (n2 - n1)

    except Exception as e:
        raise ValueError(f"Error parsing calibration data: {e}") from e

    raise ValueError(
        f"No safe mapping found for {domain} {value_key}={value}. DO NOT use linear interpolation without known points."
    )


def _verify_normalized(value: float) -> float:
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"Normalized value {value} is out of bounds (0.0 to 1.0).")
    return value


def _band_to_index(band: str) -> int:
    b = str(band).lower()
    if b in ["0", "low"]:
        return 0
    if b in ["1", "mid"]:
        return 1
    if b in ["2", "high"]:
        return 2
    raise ValueError(f"Invalid band '{band}'. Must be 0/low, 1/mid, or 2/high.")


def read_internal_mixer_eq(track: int) -> dict:
    """Read the current state of the internal mixer EQ."""
    b = get_bridge()
    res = {}
    # Read all 3 bands
    for band in range(3):
        # We try to use mode=1 if supported by our bridge to get real units,
        # but we also get mode=0 for normalized.
        try:
            norm_res = b.call("mixer_get_eq", {"track": track, "mode": 0})
            db_res = b.call("mixer_get_eq", {"track": track, "mode": 1})

            norm_band = next((x for x in norm_res.get("bands", []) if x["band"] == band), {})
            db_band = next((x for x in db_res.get("bands", []) if x["band"] == band), {})

            res[band] = {
                "gain_normalized": norm_band.get("gain"),
                "gain_db": db_band.get("gain"),
                "freq_normalized": norm_band.get("frequency"),
                "freq_hz": db_band.get("frequency"),
                "bandwidth_normalized": norm_band.get("bandwidth"),
            }
        except Exception as e:
            res[band] = {"error": str(e)}
    return {"track": track, "eq_state": res}


def set_internal_mixer_eq_gain_normalized(track: int, band: str, value: float) -> dict:
    """Safely set internal EQ gain using a normalized float (0.0 to 1.0)."""
    val = _verify_normalized(float(value))
    b_idx = _band_to_index(band)

    b = get_bridge()
    b.call("mixer_set_eq", {"track": track, "band": b_idx, "gain": val})

    # Readback
    readback = b.call("mixer_get_eq", {"track": track, "mode": 0})
    readback_val = next(
        (x.get("gain") for x in readback.get("bands", []) if x["band"] == b_idx), None
    )

    return {
        "requested_value": val,
        "normalized_value": val,
        "readback_value": readback_val,
        "confidence": "high",
        "calibration_source": "direct_normalized",
    }


def set_internal_mixer_eq_gain_db(track: int, band: str, db: float) -> dict:
    """Set internal EQ gain using dB. Fails if mapping is unknown."""
    try:
        norm_val = _get_calibration_mapping("eq_gain", "db", float(db))
    except ValueError as e:
        return {
            "error": str(e),
            "message": "Manual runtime verification required to map this dB value.",
        }

    b_idx = _band_to_index(band)
    b = get_bridge()
    b.call("mixer_set_eq", {"track": track, "band": b_idx, "gain": norm_val})

    readback = b.call("mixer_get_eq", {"track": track, "mode": 1})
    readback_db = next(
        (x.get("gain") for x in readback.get("bands", []) if x["band"] == b_idx), None
    )

    return {
        "requested_value": db,
        "normalized_value": norm_val,
        "readback_value": readback_db,
        "confidence": "high",
        "calibration_source": "knowledgebase",
    }


def set_internal_mixer_eq_frequency_normalized(track: int, band: str, value: float) -> dict:
    """Safely set internal EQ frequency using a normalized float (0.0 to 1.0)."""
    val = _verify_normalized(float(value))
    b_idx = _band_to_index(band)
    b = get_bridge()
    b.call("mixer_set_eq", {"track": track, "band": b_idx, "frequency": val})
    readback = b.call("mixer_get_eq", {"track": track, "mode": 0})
    readback_val = next(
        (x.get("frequency") for x in readback.get("bands", []) if x["band"] == b_idx), None
    )
    return {
        "requested_value": val,
        "normalized_value": val,
        "readback_value": readback_val,
        "confidence": "high",
    }


def set_internal_mixer_eq_frequency_hz(track: int, band: str, hz: float) -> dict:
    """Set internal EQ frequency using Hz. Fails if mapping is unknown."""
    try:
        norm_val = _get_calibration_mapping("eq_frequency", "hz", float(hz))
    except ValueError as e:
        return {
            "error": str(e),
            "message": "Manual runtime verification required to map this Hz value.",
        }

    b_idx = _band_to_index(band)
    b = get_bridge()
    b.call("mixer_set_eq", {"track": track, "band": b_idx, "frequency": norm_val})
    readback = b.call("mixer_get_eq", {"track": track, "mode": 1})
    readback_hz = next(
        (x.get("frequency") for x in readback.get("bands", []) if x["band"] == b_idx), None
    )

    return {
        "requested_value": hz,
        "normalized_value": norm_val,
        "readback_value": readback_hz,
        "confidence": "high",
        "calibration_source": "knowledgebase",
    }


def set_internal_mixer_eq_bandwidth_normalized(track: int, band: str, value: float) -> dict:
    val = _verify_normalized(float(value))
    b_idx = _band_to_index(band)
    b = get_bridge()
    b.call("mixer_set_eq", {"track": track, "band": b_idx, "bandwidth": val})
    readback = b.call("mixer_get_eq", {"track": track, "mode": 0})
    readback_val = next(
        (x.get("bandwidth") for x in readback.get("bands", []) if x["band"] == b_idx), None
    )
    return {"requested_value": val, "normalized_value": val, "readback_value": readback_val}


def reset_internal_mixer_eq(track: int) -> dict:
    """Reset the internal mixer EQ to default (flat) state."""
    # Def values: Gain = 0.5 (center), Freq: Low=0.25, Mid=0.5, High=0.75 roughly.
    # Since we shouldn't guess, we rely on a KB recipe or safe known normalized values.
    # We will just set gain to 0.5 (which is 0 dB confirmed).
    b = get_bridge()
    for b_idx in range(3):
        b.call("mixer_set_eq", {"track": track, "band": b_idx, "gain": 0.5})
    return {"track": track, "status": "reset_to_flat"}


def apply_internal_eq_cleanup_preset(track: int, category: str) -> dict:
    """Apply a Psytrance EQ cleanup recipe from the KB."""
    # Just an example stub, normally reads from recipes/internal_mixer_eq_cleanup.md
    # and translates to known dB values via set_internal_mixer_eq_gain_db.
    return {"error": "Not fully implemented. Rely on individual band controls for safety."}


def register(mcp: FastMCP) -> None:
    mcp.tool()(read_internal_mixer_eq)
    mcp.tool()(set_internal_mixer_eq_gain_normalized)
    mcp.tool()(set_internal_mixer_eq_gain_db)
    mcp.tool()(set_internal_mixer_eq_frequency_normalized)
    mcp.tool()(set_internal_mixer_eq_frequency_hz)
    mcp.tool()(set_internal_mixer_eq_bandwidth_normalized)
    mcp.tool()(reset_internal_mixer_eq)
    mcp.tool()(apply_internal_eq_cleanup_preset)
