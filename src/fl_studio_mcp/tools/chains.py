"""Genre processing-chain setup -- map a recipe to a track's EXISTING plugins.

fl_setup_chain reads the track's loaded plugins and returns a PLAN: which existing
intents to apply (with the matched slot) for a genre chain, + which steps can't be
done because the plugin isn't loaded (FL can't load plugins -- add manually). Apply
the plan via the existing fl_apply_eq_intent / fl_apply_compression_intent /
fl_apply_reverb_intent after the user approves. fl_list_chains lists the recipes.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import kb_policy, protocol
from ..connection import get_bridge
from ..music import chains as ch
from ..music import plugin_library as pl


def register(mcp: FastMCP) -> None:
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }

    @mcp.tool(annotations={"title": "List genre chains", **_RO})
    def fl_list_chains() -> dict:
        """List the built-in genre processing-chain recipes (vocal, drum_bus,
        bass, master) and their ordered steps.

        Safety: Read-Only.
        """
        return {"ok": True, "chains": ch.describe()}

    @mcp.tool(annotations={"title": "List installed plugins (FL DB on disk)", **_RO})
    def fl_list_installed_plugins(
        kind: Annotated[str, Field(description="'all', 'effects', or 'generators'.")] = "all",
    ) -> dict:
        """Read FL's installed-plugin DATABASE from disk (the .fst shortcuts FL
        writes for every scanned plugin) -> a de-duped, categorized list of what
        you OWN. Bypasses the FL API (which only sees LOADED plugins). FL still
        can't LOAD these -- it's for library-aware suggestions. effects_by_role is
        a rough keyword grouping (the LLM assistant should apply its own plugin knowledge).
        Read-only (directory listing only).

        Safety: Read-Only.
        """
        lib = pl.list_installed()
        if not lib.get("found"):
            return {"ok": False, **lib}
        out = {"ok": True, "path": lib["path"], "counts": lib["counts"]}
        kind = (kind or "all").lower()
        if kind in ("all", "effects"):
            out["effects"] = lib["effects"]
            out["effects_by_role"] = pl.effects_by_role(lib["effects"])
        if kind in ("all", "generators"):
            out["generators"] = lib["generators"]
        return out

    @mcp.tool(annotations={"title": "Set up a genre chain (plan)", **_RO})
    def fl_setup_chain(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
        chain_type: Annotated[
            str, Field(description="Recipe: 'vocal', 'drum_bus', 'bass', 'master'.")
        ],
    ) -> dict:
        """Plan a genre-appropriate processing chain over a track's EXISTING
        plugins. READ-ONLY plan: returns the ordered intent calls (each with the
        matched plugin + slot) and which steps are MISSING because the needed
        plugin isn't loaded (FL can't load plugins -- add those manually). After
        the user approves, apply each step by calling its 'apply' tool+args
        (fl_apply_eq_intent / fl_apply_compression_intent / fl_apply_reverb_intent
        -- each logged + rollback-able). e.g. vocal: HP -> comp -> presence ->
        air -> reverb.

        Safety: Read-Only.
        """
        try:
            plugin_listing = get_bridge().call(protocol.CMD_PLUGIN_LIST, {"track": track}) or {}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        plugins = plugin_listing.get("slots", [])
        plan = ch.plan_chain(chain_type, plugins)
        if not plan.get("ok"):
            return plan
        steps = [
            {
                "role": s["role"],
                "plugin": s["plugin"],
                "apply": {
                    "tool": s["tool"],
                    "args": {"track": track, "slot": s["slot"], "intent": s["intent"]},
                },
            }
            for s in plan["steps"]
        ]
        lib = pl.list_installed()  # what the user OWNS (disk DB)
        owned = pl.effects_by_role(lib["effects"]) if lib.get("found") else {}
        kb_refs = ["mix_doctor_existing_plugin_only"]
        if plan["chain_type"] == "master":
            kb_refs += ["mastering_after_mix_readiness", "maximus_loaded_plugin_only"]
        return {
            "ok": True,
            "track": track,
            "chain_type": plan["chain_type"],
            "loaded_plugins": [p.get("name") for p in plugins],
            "configure_now": steps,
            "missing_roles": plan["missing"],
            "library_found": bool(lib.get("found")),
            "installed_effects_by_role": owned,
            "kb_policy_refs": kb_policy.rule_refs(kb_refs),
            "guidance": (
                "1) CONFIGURE: after the user oks, apply each 'configure_now' step's "
                "apply(tool,args) on the plugins ALREADY loaded. 2) SUGGEST ADDS: for each "
                "'missing_roles' entry, recommend a plugin the user OWNS from "
                "installed_effects_by_role (pick the best fit -- apply your own plugin "
                "knowledge, the buckets are rough) and tell them to ADD it to the track "
                "(FL can't load plugins via the API). They re-run to configure it once added. "
                "Nothing applied here. For master-chain plans, run mix readiness checks first "
                "and keep rendering/export/manual mastering outside MCP automation."
            ),
        }
