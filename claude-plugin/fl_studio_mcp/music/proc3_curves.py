"""FabFilter Pro-C 3 calibration curves (plugin-specific).

Empirically measured (scripts/calibrate_proc3.py, FL 25.2.5). Pro-C ratio is a
clean X:1 (no bidirectional trap, unlike Fruity Limiter). Threshold/knee/range/
mix are LINEAR; ratio/attack/release use table interpolation; Style is discrete.

Pure functions only.
"""
from __future__ import annotations


def _clamp01(n):
    return 0.0 if n < 0.0 else (1.0 if n > 1.0 else n)


def _interp(q, pts, xi, yi):
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


# --- linear params ----------------------------------------------------------
def threshold_to_norm(db):            # dB = 60*norm - 60  (-60..0 dB)
    return _clamp01((db + 60.0) / 60.0)


def norm_to_threshold(n):
    return 60.0 * _clamp01(n) - 60.0


def knee_to_norm(db):                 # dB = 72*norm  (0..72 dB)
    return _clamp01(db / 72.0)


def norm_to_knee(n):
    return 72.0 * _clamp01(n)


def range_to_norm(db):                # dB = 60*norm  (0..60 dB)
    return _clamp01(db / 60.0)


def norm_to_range(n):
    return 60.0 * _clamp01(n)


def mix_to_norm(pct):                 # % = 200*norm  (100% at norm 0.5)
    return _clamp01(pct / 200.0)


def norm_to_mix(n):
    return 200.0 * _clamp01(n)


def makeup_db_to_norm(db):            # Output Level upper half: dB = 72*(norm-0.5)
    return _clamp01(0.5 + max(0.0, db) / 72.0)


def norm_to_makeup_db(n):
    return 72.0 * (_clamp01(n) - 0.5)


# --- table-interp params (norm, value), monotonic ascending -----------------
_RATIO = [
    (0.00, 1.0), (0.05, 1.05), (0.10, 1.10), (0.15, 1.17), (0.20, 1.25), (0.25, 1.38),
    (0.30, 1.50), (0.35, 1.75), (0.40, 2.0), (0.45, 2.38), (0.50, 2.75), (0.55, 3.38),
    (0.60, 4.0), (0.65, 5.0), (0.70, 6.0), (0.75, 7.0), (0.80, 8.0), (0.85, 9.0),
    (0.90, 10.0), (0.95, 24.4), (1.00, 100.0),
]
_ATTACK = [
    (0.00, 0.005), (0.05, 0.036), (0.10, 0.255), (0.15, 0.849), (0.20, 2.005),
    (0.25, 3.911), (0.30, 6.755), (0.35, 10.72), (0.40, 16.0), (0.45, 22.79),
    (0.50, 31.25), (0.55, 41.6), (0.60, 54.0), (0.65, 68.66), (0.70, 85.75),
    (0.75, 105.5), (0.80, 128.0), (0.85, 153.5), (0.90, 182.3), (0.95, 214.3), (1.00, 250.0),
]
_RELEASE = [
    (0.00, 10.0), (0.05, 12.9), (0.10, 21.62), (0.15, 36.14), (0.20, 56.5), (0.25, 82.74),
    (0.30, 115.0), (0.35, 153.3), (0.40, 198.2), (0.45, 250.0), (0.50, 309.5), (0.55, 377.7),
    (0.60, 456.3), (0.65, 547.7), (0.70, 655.4), (0.75, 784.9), (0.80, 944.9), (0.85, 1151.0),
    (0.90, 1429.0), (0.95, 1835.0), (1.00, 2500.0),
]


def ratio_to_norm(ratio):
    return _interp(max(1.0, float(ratio)), _RATIO, 1, 0)


def norm_to_ratio(n):
    return _interp(_clamp01(n), _RATIO, 0, 1)


def attack_ms_to_norm(ms):
    return _interp(ms, _ATTACK, 1, 0)


def norm_to_attack_ms(n):
    return _interp(_clamp01(n), _ATTACK, 0, 1)


def release_ms_to_norm(ms):
    return _interp(ms, _RELEASE, 1, 0)


def norm_to_release_ms(n):
    return _interp(_clamp01(n), _RELEASE, 0, 1)


# --- Style (discrete; norm at the centre of each style's range) -------------
STYLE_NORMS = {
    "clean": 0.00, "versatile": 0.05, "smooth": 0.15, "punch": 0.20, "upward": 0.30,
    "ttm": 0.35, "op-el": 0.45, "vari-mu": 0.50, "classic": 0.60, "opto": 0.70,
    "vocal": 0.75, "mastering": 0.85, "bus": 0.90, "pumping": 1.00,
}


def style_to_norm(name):
    return STYLE_NORMS[str(name).strip().lower()]
