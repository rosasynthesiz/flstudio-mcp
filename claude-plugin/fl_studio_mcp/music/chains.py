"""Genre processing-chain recipes -> map to a track's EXISTING plugins (PURE).

A recipe is an ordered list of (role, kind, intent). plan_chain matches each step
to a loaded plugin of that kind (eq / comp / reverb) and emits the existing-intent
call to make; steps whose plugin isn't loaded are reported as MISSING (FL can't
load plugins -- the user adds them manually). No bridge, no writes here.
"""
from __future__ import annotations

# kind -> plugin-name substrings to match, the existing intent tool, a human "needs".
_MATCH = {"eq": ("eq",),
          "comp": ("comp", "pro-c", "pro c", "limiter"),
          "reverb": ("reeverb", "reverb")}
_TOOL = {"eq": "fl_apply_eq_intent",
         "comp": "fl_apply_compression_intent",
         "reverb": "fl_apply_reverb_intent"}
_NEEDS = {"eq": "a Parametric EQ (e.g. Fruity Parametric EQ 2)",
          "comp": "a compressor/limiter (Fruity Limiter or FabFilter Pro-C)",
          "reverb": "a reverb (Fruity Reeverb 2)"}

# (role, kind, intent) -- intents are the REAL ones the existing tools accept.
RECIPES = {
    "vocal": [("high-pass", "eq", "high_pass"),
              ("compression", "comp", "heavy_vocal_compression"),
              ("presence", "eq", "add_presence"),
              ("air", "eq", "add_air"),
              ("space", "reverb", "more_space")],
    "drum_bus": [("glue", "comp", "glue_drums"),
                 ("low cleanup", "eq", "remove_mud"),
                 ("air", "eq", "add_air")],
    "bass": [("low-mid control", "eq", "remove_mud"),
             ("compression", "comp", "gentle_compression")],
    "master": [("glue", "comp", "glue_drums"),
               ("air", "eq", "add_air")],
}


def available():
    return sorted(RECIPES)


def describe():
    """Recipes as human-readable step lists (for fl_list_chains)."""
    return {name: [{"role": r, "needs": _NEEDS[k], "intent": i} for r, k, i in steps]
            for name, steps in RECIPES.items()}


def _find(plugins, substrs):
    for p in plugins or []:
        nm = (p.get("name") or "").lower()
        if any(s in nm for s in substrs):
            return p
    return None


def plan_chain(chain_type, plugins):
    """Map a recipe to the track's loaded plugins. Returns
    {ok, chain_type, steps:[{role,kind,tool,slot,plugin,intent}], missing:[...]}.
    Several steps may target the SAME EQ slot (different bands) -- that's fine,
    fl_apply_eq_intent uses a free band each call."""
    recipe = RECIPES.get((chain_type or "").lower())
    if recipe is None:
        return {"ok": False, "error": "unknown chain_type %r" % chain_type,
                "available": available()}
    steps, missing = [], []
    for role, kind, intent in recipe:
        match = _find(plugins, _MATCH[kind])
        if match is None:
            missing.append({"role": role, "needs": _NEEDS[kind], "intent": intent})
            continue
        steps.append({"role": role, "kind": kind, "tool": _TOOL[kind],
                      "slot": match.get("slot", match.get("index")),
                      "plugin": match.get("name"), "intent": intent})
    return {"ok": True, "chain_type": (chain_type or "").lower(),
            "steps": steps, "missing": missing}
