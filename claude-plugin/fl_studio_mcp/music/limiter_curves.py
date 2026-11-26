"""Fruity Limiter COMP-section calibration curves (plugin-specific).

Empirically measured (scripts/calibrate_limiter.py, FL 25.2.5). The COMP params
have no clean closed form, so every converter uses LINEAR TABLE INTERPOLATION
over the measured (norm, value) points. Values are monotonic in norm, so the
inverse direction interpolates the same table by its value column.

CRITICAL -- the bidirectional ratio trap:
  Comp ratio norm < 0.5  -> "1:X"  (upward / expansion)   <- never use
  Comp ratio norm = 0.5  -> "1:1.0" (no compression)
  Comp ratio norm > 0.5  -> "X:1"  (downward compression) <- always use
  ratio_to_norm() clamps ratio to >= 1.0 so it can NEVER return norm < 0.5.

Pure functions only -- no bridge, no I/O.
"""
from __future__ import annotations


def _clamp01(n: float) -> float:
    return 0.0 if n < 0.0 else (1.0 if n > 1.0 else n)


def _interp(q, pts, xi, yi):
    """Linear-interpolate pts[*][yi] for query q against pts[*][xi].

    pts must be sorted ascending by BOTH columns (monotonic). Clamps at ends.
    """
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


# (norm, value) measured tables -- all monotonic ascending in both columns.
_THRESHOLD = [   # norm -> dB
    (0.00, -60.0), (0.05, -35.4), (0.10, -28.9), (0.15, -25.0), (0.20, -22.0),
    (0.25, -19.6), (0.30, -17.6), (0.35, -15.8), (0.40, -14.1), (0.45, -12.6),
    (0.50, -11.2), (0.55, -9.9), (0.60, -8.7), (0.65, -7.5), (0.70, -6.3),
    (0.75, -5.2), (0.80, -4.1), (0.85, -3.0), (0.90, -2.0), (0.95, -1.0), (1.00, 0.0),
]
_RATIO = [       # norm -> compression ratio X (the "X:1" half only, norm >= 0.5)
    (0.50, 1.0), (0.55, 1.2), (0.60, 1.5), (0.65, 1.9), (0.70, 2.5), (0.75, 3.3),
    (0.80, 4.6), (0.85, 6.6), (0.90, 9.4), (0.95, 13.7), (1.00, 20.0),
]
_ATTACK = [      # norm -> ms
    (0.00, 0.0), (0.05, 0.73), (0.10, 1.72), (0.15, 3.08), (0.20, 4.93), (0.25, 7.46),
    (0.30, 10.91), (0.35, 15.62), (0.40, 22.04), (0.45, 30.81), (0.50, 42.77),
    (0.55, 59.09), (0.60, 81.36), (0.65, 111.74), (0.70, 153.21), (0.75, 209.79),
    (0.80, 287.0), (0.85, 392.36), (0.90, 536.13), (0.95, 732.3), (1.00, 1000.0),
]
_RELEASE = [     # norm -> ms
    (0.00, 0.0), (0.05, 1.46), (0.10, 3.45), (0.15, 6.16), (0.20, 9.87), (0.25, 14.92),
    (0.30, 21.82), (0.35, 31.24), (0.40, 44.08), (0.45, 61.61), (0.50, 85.53),
    (0.55, 118.17), (0.60, 162.71), (0.65, 223.49), (0.70, 306.42), (0.75, 419.58),
    (0.80, 574.0), (0.85, 784.72), (0.90, 1072.25), (0.95, 1464.61), (1.00, 2000.0),
]
_MAKEUP = [      # norm -> dB (positive half; global Gain, 0 dB at 0.5)
    (0.50, 0.0), (0.55, 1.9), (0.60, 3.8), (0.65, 5.7), (0.70, 7.5), (0.75, 9.3),
    (0.80, 11.1), (0.85, 12.8), (0.90, 14.6), (0.95, 16.3), (1.00, 18.1),
]


# --- threshold (dB) ---------------------------------------------------------
def norm_to_threshold(n):
    return _interp(n, _THRESHOLD, 0, 1)


def threshold_to_norm(db):
    return _interp(db, _THRESHOLD, 1, 0)


# --- ratio (downward only) --------------------------------------------------
def ratio_to_norm(ratio):
    """Compression ratio X (X:1) -> norm. Clamps ratio to >=1 so the result is
    always >= 0.5 (never expansion)."""
    return _interp(max(1.0, float(ratio)), _RATIO, 1, 0)


def norm_to_ratio(n):
    """norm -> downward ratio X; returns 1.0 for any norm <= 0.5 (no compression)."""
    if n <= 0.5:
        return 1.0
    return _interp(n, _RATIO, 0, 1)


# --- attack / release (ms) --------------------------------------------------
def attack_ms_to_norm(ms):
    return _interp(ms, _ATTACK, 1, 0)


def norm_to_attack_ms(n):
    return _interp(n, _ATTACK, 0, 1)


def release_ms_to_norm(ms):
    return _interp(ms, _RELEASE, 1, 0)


def norm_to_release_ms(n):
    return _interp(n, _RELEASE, 0, 1)


# --- knee (%) linear --------------------------------------------------------
def knee_pct_to_norm(pct):
    return _clamp01((pct + 100.0) / 200.0)


def norm_to_knee_pct(n):
    return 200.0 * _clamp01(n) - 100.0


# --- makeup gain (dB, positive) --------------------------------------------
def makeup_db_to_norm(db):
    return _interp(max(0.0, db), _MAKEUP, 1, 0)


def norm_to_makeup_db(n):
    return _interp(n, _MAKEUP, 0, 1)
