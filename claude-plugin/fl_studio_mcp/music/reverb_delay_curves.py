"""Fruity Reeverb 2 + Fruity Delay 3 calibration curves (plugin-specific).

Empirically derived (scripts/calibrate_reverb_delay.py, FL 25.2.5).

Reeverb 2 (all linear):
  decay    : 0.1 .. 20 sec        norm = (sec-0.1)/19.9
  wet level: 0 .. 125 %           norm = pct/125   (0.8 = 100%)
  room size: 1 .. 100             norm = (n-1)/99
  high cut : linear Hz, 500..~21k; norm 1.0 == OFF (bypassed)
  low cut  : norm 0.0 == OFF, else linear ~168..3000 Hz

Fruity Delay 3:
  out wet/dry, stereo spread : linear %, norm = pct/100
  feedback level : 0..125 %, norm = pct/125 (clamp to <=100% by default --
                   >100% self-oscillates)
  feedback cutoff: PIECEWISE (shallow low end, steep high end) -> table interp
  time           : tempo-synced musical divisions; steps ~= 16*norm
                   (1 step = 1/16 note). Stepped, not free.

These are SPECIFIC to these two plugins. Pure functions -- no I/O.
"""
from __future__ import annotations


def _clamp01(n: float) -> float:
    return 0.0 if n < 0.0 else (1.0 if n > 1.0 else n)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * _clamp01(t)


# ===========================================================================
# Fruity Reeverb 2
# ===========================================================================
DECAY_MIN_S, DECAY_MAX_S = 0.1, 20.0
WET_MAX_PCT = 125.0
HIGHCUT_HZ_AT_0, HIGHCUT_SPAN_HZ = 500.0, 21580.0   # norm 1.0 == OFF
LOWCUT_HZ_AT_MIN, LOWCUT_SPAN_HZ = 168.0, 2981.0    # at norm 0.05; norm 0.0 == OFF
LOWCUT_MIN_NORM = 0.05


def decay_to_norm(sec: float) -> float:
    return _clamp01((sec - DECAY_MIN_S) / (DECAY_MAX_S - DECAY_MIN_S))


def norm_to_decay(n: float) -> float:
    return DECAY_MIN_S + _clamp01(n) * (DECAY_MAX_S - DECAY_MIN_S)


def wet_to_norm(pct: float) -> float:
    return _clamp01(pct / WET_MAX_PCT)


def norm_to_wet(n: float) -> float:
    return _clamp01(n) * WET_MAX_PCT


def roomsize_to_norm(n: float) -> float:
    return _clamp01((n - 1.0) / 99.0)


def norm_to_roomsize(n: float) -> float:
    return 1.0 + _clamp01(n) * 99.0


# High cut: norm 1.0 is the OFF sentinel.
HIGHCUT_OFF_NORM = 1.0


def highcut_to_norm(hz: float) -> float:
    return _clamp01((hz - HIGHCUT_HZ_AT_0) / HIGHCUT_SPAN_HZ)


def norm_to_highcut_hz(n: float):
    """Hz, or None when the band is OFF (norm >= 1.0)."""
    if n >= 0.999:
        return None
    return HIGHCUT_HZ_AT_0 + _clamp01(n) * HIGHCUT_SPAN_HZ


# Low cut: norm 0.0 is the OFF sentinel.
LOWCUT_OFF_NORM = 0.0


def lowcut_to_norm(hz: float) -> float:
    """<=168 Hz collapses toward the minimum audible norm; norm 0.0 == OFF."""
    if hz <= LOWCUT_HZ_AT_MIN:
        return LOWCUT_MIN_NORM
    return _clamp01(LOWCUT_MIN_NORM + (hz - LOWCUT_HZ_AT_MIN) / LOWCUT_SPAN_HZ)


def norm_to_lowcut_hz(n: float):
    """Hz, or None when OFF (norm <= 0.0)."""
    if n <= 0.0:
        return None
    return LOWCUT_HZ_AT_MIN + (_clamp01(n) - LOWCUT_MIN_NORM) * LOWCUT_SPAN_HZ


# ===========================================================================
# Fruity Delay 3
# ===========================================================================
def delay_pct_to_norm(pct: float) -> float:
    """Output wet / dry / stereo spread -- linear %."""
    return _clamp01(pct / 100.0)


def norm_to_delay_pct(n: float) -> float:
    return _clamp01(n) * 100.0


FEEDBACK_MAX_PCT = 125.0
FEEDBACK_SAFE_PCT = 100.0


def feedback_to_norm(pct: float, allow_oscillation: bool = False) -> float:
    """Feedback %; clamped to <=100% unless allow_oscillation (then up to 125%)."""
    cap = FEEDBACK_MAX_PCT if allow_oscillation else FEEDBACK_SAFE_PCT
    return _clamp01(min(pct, cap) / FEEDBACK_MAX_PCT)


def norm_to_feedback(n: float) -> float:
    return _clamp01(n) * FEEDBACK_MAX_PCT


# Feedback cutoff: measured (norm, Hz) points -> piecewise-linear interpolation.
_CUTOFF_PTS = [
    (0.00, 270.0), (0.05, 312.0), (0.10, 354.0), (0.15, 396.0), (0.20, 438.0),
    (0.25, 479.9), (0.30, 643.8), (0.35, 807.7), (0.40, 971.7), (0.45, 1135.6),
    (0.50, 1299.6), (0.55, 2436.9), (0.60, 3576.6), (0.65, 4716.3), (0.70, 5856.0),
    (0.75, 6995.7), (0.80, 9988.0), (0.85, 12987.3), (0.90, 15986.5),
    (0.95, 18985.8), (1.00, 21985.0),
]


def norm_to_cutoff_hz(n: float) -> float:
    n = _clamp01(n)
    for i in range(1, len(_CUTOFF_PTS)):
        n0, h0 = _CUTOFF_PTS[i - 1]
        n1, h1 = _CUTOFF_PTS[i]
        if n <= n1:
            t = (n - n0) / (n1 - n0) if n1 > n0 else 0.0
            return h0 + t * (h1 - h0)
    return _CUTOFF_PTS[-1][1]


def cutoff_hz_to_norm(hz: float) -> float:
    if hz <= _CUTOFF_PTS[0][1]:
        return _CUTOFF_PTS[0][0]
    if hz >= _CUTOFF_PTS[-1][1]:
        return _CUTOFF_PTS[-1][0]
    for i in range(1, len(_CUTOFF_PTS)):
        n0, h0 = _CUTOFF_PTS[i - 1]
        n1, h1 = _CUTOFF_PTS[i]
        if hz <= h1:
            t = (hz - h0) / (h1 - h0) if h1 > h0 else 0.0
            return n0 + t * (n1 - n0)
    return _CUTOFF_PTS[-1][0]


# Time: tempo-synced musical divisions. steps = 16*norm, 1 step = 1/16 note.
DIVISIONS = [           # ascending; (label, norm)
    ("1/16", 1 / 16),
    ("1/8", 2 / 16),
    ("1/4", 4 / 16),
    ("1/2", 8 / 16),
    ("1/1", 16 / 16),
]


def division_norm(label: str) -> float:
    for nm, n in DIVISIONS:
        if nm == label:
            return n
    raise ValueError("unknown division %r; known: %s"
                     % (label, [d[0] for d in DIVISIONS]))


# Spec alias.
def nearest_division_norm(label: str) -> float:
    return division_norm(label)


def nearest_division_index(norm: float) -> int:
    return min(range(len(DIVISIONS)), key=lambda i: abs(DIVISIONS[i][1] - norm))


def step_division(current_norm: float, steps: int):
    """Return (label, norm) `steps` away (clamped) from the nearest division."""
    i = nearest_division_index(current_norm)
    j = max(0, min(len(DIVISIONS) - 1, i + steps))
    return DIVISIONS[j]
