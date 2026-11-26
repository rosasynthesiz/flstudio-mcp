"""Fruity Parametric EQ 2 calibration curves + band layout.

Empirically derived (scripts/calibrate_eq.py, FL 25.2.5):
  freq  : logarithmic, 20 Hz .. 20 kHz (3 decades)   Hz = 20 * 10**(3*norm)
  level : linear, +/-18 dB                            dB = 36*norm - 18
  width : linear, 0..100 %                            %  = 100*norm
  type  : 8 discrete filter types snapped to k/7

These curves are SPECIFIC to Fruity Parametric EQ 2. Other plugins
(Reeverb 2, VST/AU wrappers) have their own mappings -- do not reuse these.

Pure functions only -- no bridge, no I/O -- so they're trivially unit-testable.
"""
from __future__ import annotations

import math

# --- constants (from calibration) -------------------------------------------
FREQ_MIN_HZ = 20.0          # norm 0.0
FREQ_DECADES = 3.0          # 20 Hz * 10**3 = 20000 Hz at norm 1.0
LEVEL_RANGE_DB = 18.0       # +/-18 dB full scale; 0 dB at norm 0.5


def _clamp01(n: float) -> float:
    return 0.0 if n < 0.0 else (1.0 if n > 1.0 else n)


# --- frequency (logarithmic) -------------------------------------------------
def freq_to_norm(hz: float) -> float:
    """Hz -> normalized 0..1 (clamped). 20 Hz->0, 632 Hz->0.5, 20 kHz->1."""
    if hz <= 0:
        return 0.0
    return _clamp01(math.log10(hz / FREQ_MIN_HZ) / FREQ_DECADES)


def norm_to_freq(n: float) -> float:
    """normalized 0..1 -> Hz."""
    return FREQ_MIN_HZ * 10 ** (FREQ_DECADES * _clamp01(n))


# --- level / gain (linear, +/-18 dB) -----------------------------------------
def db_to_norm(db: float) -> float:
    """dB -> normalized 0..1 (clamped). -18 dB->0, 0 dB->0.5, +18 dB->1."""
    return _clamp01((db + LEVEL_RANGE_DB) / (2 * LEVEL_RANGE_DB))


def norm_to_db(n: float) -> float:
    """normalized 0..1 -> dB."""
    return 2 * LEVEL_RANGE_DB * _clamp01(n) - LEVEL_RANGE_DB


# --- width (linear, 0..100 %) ------------------------------------------------
def width_to_norm(pct: float) -> float:
    """percent -> normalized 0..1 (clamped)."""
    return _clamp01(pct / 100.0)


def norm_to_width(n: float) -> float:
    """normalized 0..1 -> percent."""
    return _clamp01(n) * 100.0


# --- filter type (8 discrete, snapped to k/7) --------------------------------
TYPE_NORMS = {
    "disabled": 0 / 7,
    "low_pass": 1 / 7,
    "band_pass": 2 / 7,
    "high_pass": 3 / 7,
    "notch": 4 / 7,
    "low_shelf": 5 / 7,
    "peaking": 6 / 7,
    "high_shelf": 7 / 7,
}


# --- band layout -------------------------------------------------------------
# 7 bands; per-band params are interleaved by group:
#   level: idx 0-6, freq: 7-13, width: 14-20, type: 21-27
# Band N (1-based): level=N-1, freq=6+N, width=13+N, type=20+N
_BAND_OFFSET = {"level": -1, "freq": 6, "width": 13, "type": 20}


def eq2_band_param_index(band: int, which: str) -> int:
    """Param index for (1-based) band N's ``which`` ('level'|'freq'|'width'|'type')."""
    if not 1 <= band <= 7:
        raise ValueError("EQ2 band must be 1..7, got %r" % (band,))
    if which not in _BAND_OFFSET:
        raise ValueError("which must be one of %s, got %r"
                         % (sorted(_BAND_OFFSET), which))
    return _BAND_OFFSET[which] + band
