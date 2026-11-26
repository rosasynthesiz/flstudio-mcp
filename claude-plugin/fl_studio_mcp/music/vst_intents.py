"""Generic, plugin-agnostic semantic intents for synths/effects.

Maps musical requests ("brighter", "more attack", "wider") to a parameter role
+ a direction + a relative move. Combined with the calibration engine, this lets
an LLM shape ANY plugin without knowing its exact param names -- it locates the
right knob by keyword, learns its unit curve, and nudges it.

Pure here: the intent table + parameter picker. The actual apply (calibrate ->
compute target -> safe_write) lives in tools/vst.py.
"""

from __future__ import annotations

# intent -> spec:
#   keywords : name fragments identifying the target param (checked lower-cased)
#   direction: +1 raises the value, -1 lowers it
#   mode     : "mul" (scale the current value) | "frac" (move a fraction of range)
INTENTS: dict[str, dict] = {
    "brighter":       {"keywords": ("cutoff", "bright", "tone", "filter freq"), "direction": +1, "mode": "mul"},
    "darker":         {"keywords": ("cutoff", "bright", "tone", "filter freq"), "direction": -1, "mode": "mul"},
    "more_resonance": {"keywords": ("resonance", "reso", " q "), "direction": +1, "mode": "frac"},
    "less_resonance": {"keywords": ("resonance", "reso", " q "), "direction": -1, "mode": "frac"},
    "more_attack":    {"keywords": ("attack",), "direction": +1, "mode": "mul"},
    "less_attack":    {"keywords": ("attack",), "direction": -1, "mode": "mul"},
    "slower_release": {"keywords": ("release",), "direction": +1, "mode": "mul"},
    "faster_release": {"keywords": ("release",), "direction": -1, "mode": "mul"},
    "wider":          {"keywords": ("width", "unison", "detune", "spread", "stereo"), "direction": +1, "mode": "frac"},
    "narrower":       {"keywords": ("width", "unison", "detune", "spread", "stereo"), "direction": -1, "mode": "frac"},
    "more_drive":     {"keywords": ("drive", "distort", "saturat", "warmth"), "direction": +1, "mode": "frac"},
    "less_drive":     {"keywords": ("drive", "distort", "saturat", "warmth"), "direction": -1, "mode": "frac"},
}


def resolve_intent(intent: str) -> dict | None:
    return INTENTS.get(str(intent or "").strip().lower())


def list_intents() -> list[str]:
    return sorted(INTENTS)


def pick_param(params, keywords):
    """Choose the best-matching param for a set of keywords. PURE.

    Scores by number of keyword hits (more specific wins), then prefers the
    shorter name (usually the primary knob, e.g. 'Cutoff' over 'Cutoff Env
    Amount'), then the lower index. Returns the param dict or None.
    """
    kws = tuple(k.strip().lower() for k in keywords if k.strip())
    scored = []
    for p in params or []:
        name = str(p.get("name", "")).lower()
        hits = sum(1 for k in kws if k in name)
        if hits:
            scored.append((hits, -len(name), -int(p.get("i", 0)), p))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][3]


def relative_target(current_value: float, spec: dict, amount: float,
                    value_range: tuple[float, float]) -> float:
    """Compute a new target value from the current one. PURE.

    amount in 0..1 scales the strength. "mul" scales by (1 + 2*amount) up or its
    reciprocal down; "frac" moves ``amount`` of the calibrated range up/down.
    Result is clamped to ``value_range``.
    """
    amount = max(0.0, min(1.0, float(amount)))
    lo, hi = min(value_range), max(value_range)
    direction = spec.get("direction", 1)
    if spec.get("mode") == "mul":
        factor = (1.0 + 2.0 * amount) if direction > 0 else 1.0 / (1.0 + 2.0 * amount)
        target = current_value * factor
    else:  # "frac": move a fraction of the full range
        span = (hi - lo) * amount
        target = current_value + (span if direction > 0 else -span)
    return max(lo, min(hi, target))
