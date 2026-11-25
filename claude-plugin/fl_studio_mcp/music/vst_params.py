"""Generic VST/AU/native parameter understanding -- pure, plugin-agnostic.

Two jobs, both name-based and side-effect-free:

* ``group_params_by_role`` -- bucket a plugin's parameters into musical roles
  (oscillator/filter/envelope/lfo/amp/fx/...), so a 600-param synth (Vital,
  Serum) presents as a digestible, curated view instead of a flat dump.
* ``classify_param_exposure`` -- decide how controllable a plugin is from the
  host: full (real names + readable value strings), partial (names only), or
  opaque (generic "Param N"). This is the graceful-degradation signal the LLM
  uses to decide between unit-targeted control and raw normalised nudging.

Grounded in probe findings (Serum 541 named params + value strings; Pro-C 100
named + units) and the VST3/AU standard that hosts read per-param names +
value->string. Nothing here talks to FL.
"""

from __future__ import annotations

import re

# Role keyword buckets, checked in PRIORITY order (first match wins) so a param
# lands in its most specific section. Keywords use word-ish fragments that avoid
# obvious false positives. Fuzzy on purpose -- a coarse map, not ground truth.
_ROLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("lfo", ("lfo",)),
    ("envelope", ("env", "attack", "decay", "sustain", "release", "adsr", " hold")),
    ("filter", ("filter", "cutoff", "resonance", "reso", "lpf", "hpf", " q ")),
    ("oscillator", ("osc", "wavetable", "wt ", "waveform", "wave ", "sub", "noise",
                    "warp", "unison", "voices", "detune")),
    ("pitch", ("pitch", "tune", "octave", "semi", "cent", "porta", "glide", "transpose")),
    ("fx", ("reverb", "delay", "chorus", "distort", "phaser", "flanger", "eq ",
            "compress", "drive", "saturat", "fx", "effect")),
    ("mod", ("macro", "mod ", "matrix", "amount", "depth", "lfo depth")),
    ("arp", ("arp", "sequence", "seq ", "step", "rate")),
    ("amp", ("amp", "level", "volume", "gain", "velocity")),
    ("stereo", ("stereo", "width", "spread", "pan")),
    ("master", ("master", "output", "global", "main")),
]

_GENERIC_NAME = re.compile(r"^\s*(param(eter)?\s*\d+|p\d+|cc\d+)\s*$", re.I)


def _role_of(name: str) -> str:
    low = " " + str(name or "").lower() + " "
    for role, kws in _ROLE_KEYWORDS:
        if any(k in low for k in kws):
            return role
    return "other"


def group_params_by_role(params) -> dict:
    """Bucket params into musical roles. Returns ``{role: [param, ...]}`` keeping
    only non-empty roles, preserving input order within each role. PURE.

    Each ``param`` is passed through unchanged (expects at least a ``name`` key;
    ``i``/``v``/``s`` are carried along if present)."""
    out: dict[str, list] = {}
    for p in params or []:
        role = _role_of(p.get("name", "") if isinstance(p, dict) else p)
        out.setdefault(role, []).append(p)
    return out


def is_generic_name(name) -> bool:
    """True if a param name is a generic placeholder like 'Param 12' / 'P3' / ''."""
    s = str(name or "").strip()
    return not s or bool(_GENERIC_NAME.match(s))


def classify_param_exposure(params) -> dict:
    """Classify how controllable a plugin is from the host. PURE.

    Returns ``{tier, total, named, valued, named_fraction, valued_fraction}``
    where tier is:
      * "full"    -- most params have real names AND readable value strings
                     (unit-targeted control + calibration feasible)
      * "partial" -- real names but few/no value strings (normalised control;
                     calibration can still parse the strings that exist)
      * "opaque"  -- mostly generic/empty names (raw normalised nudging only)
      * "empty"   -- no params
    """
    plist = list(params or [])
    total = len(plist)
    if total == 0:
        return {"tier": "empty", "total": 0, "named": 0, "valued": 0,
                "named_fraction": 0.0, "valued_fraction": 0.0}
    named = sum(1 for p in plist if not is_generic_name(p.get("name")))
    valued = sum(1 for p in plist if str(p.get("s") or "").strip())
    nf = named / total
    vf = valued / total
    if nf >= 0.5 and vf >= 0.5:
        tier = "full"
    elif nf >= 0.5:
        tier = "partial"
    else:
        tier = "opaque"
    return {"tier": tier, "total": total, "named": named, "valued": valued,
            "named_fraction": round(nf, 3), "valued_fraction": round(vf, 3)}
