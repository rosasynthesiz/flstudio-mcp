"""Parse FL/plugin parameter display strings into (value, unit). Pure.

Plugins report a readable string per parameter value -- e.g. "-16.00 dB",
"3.50:1", "1.2 kHz", "0.725 ms", "50% [-9.0 dB]", "0 semitones". Turning these
into numbers + a canonical unit lets the calibration engine build a norm<->unit
table for ANY plugin, which is what enables unit-targeted control ("set cutoff
to 2 kHz") on synths we've never seen.

Canonical units: "dB", "Hz", "ms", "s", "%", "ratio", "semitone", "oct", or
None (plain number / unrecognised).
"""

from __future__ import annotations

import re

_NUM = re.compile(r"[-+]?\d*\.?\d+")


def _first_number(s: str):
    m = _NUM.search(s)
    return float(m.group()) if m else None


def parse_value_string(s) -> dict:
    """Return ``{"value": float|None, "unit": str|None, "raw": str}``. PURE.

    Recognises ratio (X:1), kHz (folded to Hz), Hz, dB, ms, s/sec, %, semitone,
    oct. For compound strings like "50% [-9.0 dB]" the PRIMARY (left-most) unit
    wins ("%" here); the bracketed dB is secondary and ignored for the primary
    value. Unrecognised -> plain number with unit None.
    """
    raw = "" if s is None else str(s)
    low = raw.lower().strip()
    if not low:
        return {"value": None, "unit": None, "raw": raw}

    # ratio "X:1" (or "1:X") -> take the X on the non-1 side, unit "ratio"
    if ":" in low and "hz" not in low:
        left, _, right = low.partition(":")
        lv, rv = _first_number(left), _first_number(right)
        if lv is not None and rv is not None:
            val = lv if rv == 1 else (rv if lv == 1 else lv)
            return {"value": val, "unit": "ratio", "raw": raw}

    val = _first_number(low)
    if val is None:
        return {"value": None, "unit": None, "raw": raw}

    # Order matters: check kHz before Hz, ms before bare s.
    if "khz" in low:
        return {"value": val * 1000.0, "unit": "Hz", "raw": raw}
    if "hz" in low:
        return {"value": val, "unit": "Hz", "raw": raw}
    if "%" in low:
        return {"value": val, "unit": "%", "raw": raw}
    if "db" in low:
        return {"value": val, "unit": "dB", "raw": raw}
    if "ms" in low:
        return {"value": val, "unit": "ms", "raw": raw}
    if "semi" in low:
        return {"value": val, "unit": "semitone", "raw": raw}
    if "oct" in low:
        return {"value": val, "unit": "oct", "raw": raw}
    # bare seconds: "1.20 s" / "1.2 sec" (avoid matching 'ms', handled above)
    if re.search(r"\d\s*(s|sec)\b", low):
        return {"value": val, "unit": "s", "raw": raw}
    return {"value": val, "unit": None, "raw": raw}


def to_canonical(value: float, unit: str | None) -> tuple[float, str | None]:
    """Fold related units to a canonical base for comparison: seconds -> ms."""
    if unit == "s":
        return value * 1000.0, "ms"
    return value, unit
