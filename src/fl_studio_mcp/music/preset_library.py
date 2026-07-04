"""Read plugin/preset names from disk -- like plugin_library, for PRESETS.

Sources (read-only directory listings; never file contents):
  * FL Presets:  <FL Studio*>/Presets/Plugin presets/<Plugin>/*.fst  (per-plugin)
                 + Channel presets/ + Mixer presets/
  * Serum:       <Documents>/Xfer/Serum 2 Presets/**/*.serumpreset

FL still can't LOAD a preset via the API -- this is suggestion-only (the user
loads the named preset; then Claude tweaks params via the existing plugin tools).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_FL = "FLSTUDIO_MCP_PRESETS"
_ENV_SERUM = "FLSTUDIO_MCP_SERUM_PRESETS"

# Small synonym map so a description like "vintage bass" matches Serum-style
# short names ("BA ...", "Analog ..."). Rough -- Claude refines the final pick.
_SYN = {
    "bass": ("bass", "ba ", "808", "sub"),
    "lead": ("lead", "ld ", "ld_"),
    "pluck": ("pluck", "plk"),
    "pad": ("pad", "pd "),
    "keys": ("keys", "key", "piano", "ky "),
    "arp": ("arp", "seq", "sequence"),
    "chord": ("chord", "chd", "stab"),
    "vintage": ("vintage", "vint", "retro", "analog", "analogue", "classic", "old"),
    "warm": ("warm", "soft", "mellow", "smooth"),
    "bright": ("bright", "air", "crisp", "shiny"),
    "hard": ("hard", "aggress", "dist", "grit", "growl", "dirty"),
    "vocal": ("vocal", "vox", "voice", "choir", "formant"),
    "fx": ("fx", "riser", "sweep", "impact", "noise"),
}


def _fl_studio_dirs():
    home = Path.home()
    for r in (home / "Documents" / "Image-Line", home / "Image-Line"):
        if r.is_dir():
            yield from sorted(r.glob("FL Studio*"), reverse=True)


def find_fl_presets():
    env = os.environ.get(_ENV_FL)
    if env and os.path.isdir(env):
        return env
    for fl in _fl_studio_dirs():
        p = fl / "Presets"
        if p.is_dir():
            return str(p)
    return None


def find_serum_presets():
    env = os.environ.get(_ENV_SERUM)
    if env and os.path.isdir(env):
        return env
    home = Path.home()
    # Base folders that hold a Serum presets subfolder, across platforms:
    #   Windows/cross-platform default: <Documents>/Xfer
    #   macOS user content:             ~/Music/Xfer, ~/Library/Audio/Presets/Xfer Records
    bases = (
        home / "Documents" / "Xfer",
        home / "Music" / "Xfer",
        home / "Library" / "Audio" / "Presets" / "Xfer Records",
    )
    names = ("Serum 2 Presets", "Serum2 Presets", "Serum Presets", "Presets")
    for base in bases:
        if not base.is_dir():
            continue
        for name in names:
            p = base / name
            if p.is_dir():
                return str(p)
    return None


def _names(folder, ext):
    out = set()
    if folder and os.path.isdir(folder):
        for _r, _d, files in os.walk(folder):
            for f in files:
                if f.lower().endswith(ext):
                    out.add(os.path.splitext(f)[0])
    return sorted(out, key=str.lower)


def plugin_presets(presets_root):
    """{plugin: [preset names]} from Presets/Plugin presets/<Plugin>/*.fst."""
    out = {}
    pp = os.path.join(presets_root or "", "Plugin presets")
    if os.path.isdir(pp):
        for plugin in sorted(os.listdir(pp), key=str.lower):
            names = _names(os.path.join(pp, plugin), ".fst")
            if names:
                out[plugin] = names
    return out


def serum_presets():
    return _names(find_serum_presets(), ".serumpreset")


def list_presets(plugin_filter=None):
    """Categorized preset names. No filter -> a SUMMARY (per-plugin counts +
    serum/channel/mixer counts). With plugin_filter -> that plugin's full list."""
    fl, serum_dir = find_fl_presets(), find_serum_presets()
    if not fl and not serum_dir:
        return {"found": False,
                "error": "no preset folders found; set %s / %s." % (_ENV_FL, _ENV_SERUM)}
    pp = plugin_presets(fl) if fl else {}
    serum = serum_presets()

    if plugin_filter:
        f = plugin_filter.lower()
        out = {k: v for k, v in pp.items() if f in k.lower()}
        if "serum" in f and serum:
            out["Serum 2 (Xfer)"] = serum
        return {"found": True, "filter": plugin_filter,
                "fl_presets_path": fl, "serum_path": serum_dir,
                "presets": out, "count": sum(len(v) for v in out.values())}

    summary = {"found": True, "fl_presets_path": fl, "serum_path": serum_dir,
               "plugins_with_presets": {k: len(v) for k, v in pp.items()},
               "serum_preset_count": len(serum)}
    for sub, key in (("Channel presets", "channel_presets"), ("Mixer presets", "mixer_presets")):
        names = _names(os.path.join(fl, sub), ".fst") if fl else []
        if names:
            summary[key] = {"count": len(names), "sample": names[:12]}
    return summary


def _expand(tok):
    out = {tok}
    for key, syns in _SYN.items():
        if tok == key or tok in syns:
            out.add(key)
            out.update(syns)
    return out


def score_presets(names, description, top=15):
    """Rough name match: how many (synonym-expanded) description tokens appear in
    each preset name. Returns the top matches (name-only -- can't hear sound)."""
    toks = [w for w in re.split(r"[^a-z0-9]+", (description or "").lower()) if w]
    expanded = [_expand(t) for t in toks]
    scored = []
    for nm in names:
        low = nm.lower()
        s = sum(1 for syn_set in expanded if any(syn in low for syn in syn_set))
        if s:
            scored.append((s, nm))
    scored.sort(key=lambda x: (-x[0], x[1].lower()))
    return [nm for _s, nm in scored[:top]]
