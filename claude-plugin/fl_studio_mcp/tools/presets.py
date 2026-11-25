"""Preset suggester -- read preset NAMES from disk (FL Presets + Serum) and
suggest matches by name. Read-only.

FL can't LOAD a preset via the API, so this is SUGGESTION-ONLY: Claude reads the
names + tells the user which to load; after the user loads it, Claude can tweak
its params via the existing plugin tools (fl_plugin_set_param / fl_apply_*_intent).
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastmcp import FastMCP
from pydantic import Field

from ..music import preset_library as pre

_CAP = 200


def register(mcp: FastMCP) -> None:
    _RO = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}

    @mcp.tool(annotations={"title": "List presets (from disk)", **_RO})
    def fl_list_presets(
        plugin_filter: Annotated[Optional[str], Field(description="Plugin to narrow to (e.g. 'Serum', 'Fruity Parametric EQ 2'); omit for a summary.")] = None,
    ) -> dict:
        r"""Read preset NAMES from disk: FL Presets\ (per-plugin 'Plugin presets',
        plus Channel/Mixer presets) + Serum 2 Presets (.serumpreset). With NO
        filter -> a SUMMARY (which plugins have presets + counts). With
        plugin_filter -> that plugin's full preset list. Read-only. FL can't LOAD
        presets via the API -- this is for suggestions (you load the named preset,
        then Claude can tweak it)."""
        lib = pre.list_presets(plugin_filter=plugin_filter)
        if not lib.get("found"):
            return {"ok": False, **lib}
        if plugin_filter:
            presets = lib.get("presets", {})
            out = {"ok": True, "filter": plugin_filter, "count": lib["count"],
                   "presets": {k: v[:_CAP] for k, v in presets.items()}}
            if not presets:
                out["note"] = ("no presets for that plugin; call fl_list_presets() (no filter) "
                               "to see which plugins have presets.")
            elif lib["count"] > _CAP:
                out["note"] = "capped to %d per category -- narrow the filter or use fl_suggest_preset." % _CAP
            return out
        return {"ok": True, **lib}

    @mcp.tool(annotations={"title": "Suggest a preset by description", **_RO})
    def fl_suggest_preset(
        description: Annotated[str, Field(description="The sound you want, e.g. 'vintage bass', 'bright pluck'.")],
        plugin: Annotated[str, Field(description="Plugin whose presets to search, e.g. 'Serum'.")],
    ) -> dict:
        """Suggest presets from YOUR library matching a description, for a given
        plugin. Reads the plugin's preset NAMES from disk + ranks by name match.
        Name-only (can't hear the sound) -- apply your own knowledge of preset
        naming. FL can't LOAD presets via the API: recommend which to load in the
        plugin manually; AFTER the user loads it you can tweak its params via
        fl_plugin_set_param / fl_apply_*_intent."""
        lib = pre.list_presets(plugin_filter=plugin)
        if not lib.get("found"):
            return {"ok": False, **lib}
        allnames = [n for v in lib.get("presets", {}).values() for n in v]
        if not allnames:
            return {"ok": True, "plugin": plugin, "matches": [], "available": 0,
                    "note": "No presets found for %r. Run fl_list_presets() to see which "
                            "plugins have presets." % plugin}
        matches = pre.score_presets(allnames, description)
        return {"ok": True, "plugin": plugin, "description": description,
                "available": len(allnames), "matches": matches or allnames[:15],
                "matched_by": "preset NAME vs description (name-only -- no sound)",
                "guidance": ("Recommend the best 2-4 of 'matches' (apply your own knowledge: e.g. "
                             "Serum 'BA'=bass, 'LD'=lead). FL can't load presets via the API -- tell "
                             "the user to load the chosen one in %s, then tweak its params via "
                             "fl_plugin_set_param / fl_apply_*_intent." % plugin)}
