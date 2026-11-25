"""Read FL's installed-plugin DATABASE from disk -- bypasses the API wall.

FL writes a .fst shortcut for every scanned plugin under
  <Documents>/Image-Line/FL Studio*/Presets/Plugin database/Installed/
    Effects/<format>/*.fst      (FX)
    Generators/<format>/*.fst   (instruments)
The .fst BASENAME is the plugin name FL uses. We only read the directory listing
(names) -- never file contents. Read-only; pure filesystem. (FL still can't LOAD
these via the API; this is for library-aware SUGGESTIONS.)
"""
from __future__ import annotations

import os

from ..paths import image_line_dirs

_ENV = "FLSTUDIO_MCP_PLUGIN_DB"     # override: full path to the 'Installed' folder

# Rough keyword buckets for EFFECTS, a convenience for chain suggestions. Fuzzy
# (a name can land in several roles); the full effects list stays authoritative.
_ROLE_KW = {
    "eq": ("equaliz", " eq", "eq ", "pro-q", "proq"),
    "compressor": ("compress", "pro-c", "proc", "vc 76", "vc76", "1176", "la-2a",
                   "opto", "glue", "dynamics", "comp"),
    "reverb": ("reverb", "reeverb", "verb", "rc 48", "rc48", "raum", " room",
               "hall", "plate"),
    "delay": ("delay", "echo", "replika"),
    "de-esser": ("de-ess", "deess", "de ess", "esser"),
    "saturation": ("saturat", "tape", "overdrive", "distort", "drive", "dirt",
                   "exciter", "decapitat", "clipper", "fresh air", "blood", "warmth"),
    "limiter": ("limiter", "maxim", "unlimit"),
    "pitch": ("auto-tune", "autotune", "auto-key", "pitch", "tuner", "newtone"),
    "width": ("imager", "stereo", "width", "widen", "spread"),
    "gate": ("gate", "expander"),
}


def find_plugin_db():
    """Locate FL's 'Installed' plugin-db folder: env override, else discover under
    the user's Documents (handles versioned 'FL Studio NN' folders)."""
    env = os.environ.get(_ENV)
    if env and os.path.isdir(env):
        return env
    for r in image_line_dirs():
        if not r.is_dir():
            continue
        for fl in sorted(r.glob("FL Studio*"), reverse=True):
            p = fl / "Presets" / "Plugin database" / "Installed"
            if p.is_dir():
                return str(p)
    return None


def _names(folder):
    out = set()
    if os.path.isdir(folder):
        for _root, _dirs, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(".fst"):
                    out.add(os.path.splitext(f)[0])
    return out


def list_installed(base=None):
    """De-duped, categorized installed-plugin names:
    {found, path, effects:[...], generators:[...], counts}. Read-only."""
    base = base or find_plugin_db()
    if not base or not os.path.isdir(base):
        return {"found": False, "path": base,
                "error": "FL plugin-db 'Installed' folder not found; set %s to its path." % _ENV}
    eff = sorted(_names(os.path.join(base, "Effects")), key=str.lower)
    gen = sorted(_names(os.path.join(base, "Generators")), key=str.lower)
    return {"found": True, "path": base, "effects": eff, "generators": gen,
            "counts": {"effects": len(eff), "generators": len(gen)}}


def effects_by_role(effect_names):
    """ROUGH keyword grouping of effect names by mixing role (convenience for
    chain suggestions; fuzzy -- a name may land in several roles). Keywords are
    chosen so plain substring matching avoids obvious false positives (e.g. 'eq'
    uses ' eq'/'equaliz', never bare 'eq', so 'Frequency' isn't mis-bucketed)."""
    out = {role: [] for role in _ROLE_KW}
    for nm in effect_names:
        low = nm.lower()
        for role, kws in _ROLE_KW.items():
            if any(k in low for k in kws):
                out[role].append(nm)
    return {role: names for role, names in out.items() if names}
