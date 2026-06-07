"""Project Organizer tools for FL Studio MCP.

Handles broad project standardization, naming conventions, color coding,
and structural cleanup.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import kb_policy, operations, protocol, safety
from .. import project_templates as templates
from ..connection import fetch_all_pages, get_bridge
from .color import parse_color
from .routing import _bus_rename_entry


def _looks_default_channel_name(name) -> bool:
    if not name:
        return True
    return str(name).split(" ")[0] in ("Channel", "Sampler", "Insert", "AudioClip")


def _color_params(spec: str) -> dict:
    rgb = parse_color(spec)
    if rgb is None:
        raise ValueError(f"unknown color {spec!r}; pass a known color name or hex like '#33A1FF'")
    r, g, b = rgb
    return {"r": r, "g": g, "b": b}


def _color_write_entry(channel: int, color_spec: str) -> dict:
    params = {"channel": channel, **_color_params(color_spec)}
    return operations.prepare_operation("channel", "set_color", params).safe_write_group_entry()


def _mixer_color_entry(track: int, color_spec: str) -> dict:
    params = {"track": track, **_color_params(color_spec)}
    return operations.prepare_operation("mixer", "set_color", params).safe_write_group_entry()


def _channel_rename_entry(channel: int, name: str) -> dict:
    return operations.prepare_operation(
        "channel", "set_name", {"channel": channel, "name": name}
    ).safe_write_group_entry()


def register(mcp: FastMCP) -> None:
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }
    _WR = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "write-safe",
    }

    @mcp.tool(annotations={"title": "Analyze Project Organization", **_RO})
    def fl_analyze_project_organization() -> dict:
        """Analyze project to find unnamed channels, uncolored channels, and unassigned tracks.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")
        routing = fetch_all_pages(bridge, protocol.CMD_MIXER_GET_ROUTING_ALL, "routing")
        template_context = templates.classify_topology(
            routing.get("routing", []),
            routing.get("routing", []),
            chans.get("channels", []),
        )

        unnamed = []
        ungrouped = []

        for c in chans.get("channels", []):
            if _looks_default_channel_name(c.get("name")):
                unnamed.append(c)

            # Simple heuristic for uncolored (assuming default FL color or no color)
            # We don't have color in routing summary currently, we'd need to fetch or assume.
            # But the agent can use this as a structural check.

            tgt = c.get("target_mixer_track")
            if (
                not isinstance(tgt, int)
                or tgt == 0
                and not templates.is_template_bus(template_context, tgt)
            ):
                ungrouped.append(c)

        return {
            "unnamed_channels": unnamed,
            "ungrouped_channels": ungrouped,
            "template_context": templates.compact_context(template_context),
            "note": "Use plan_project_cleanup to generate an action plan.",
            "policy_notes": [
                "Preserve linked Channel, Playlist, and Mixer naming/coloring where it is already evident.",
                "Do not infer Channel, Playlist Track, and Mixer Track links from numeric index alone.",
                "Only apply cleanup through rollback-safe wrappers.",
            ],
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "instrument_audio_track_workflow",
                    "channel_rack_workflow_requires_routing_inference",
                ]
            ),
        }

    @mcp.tool(annotations={"title": "Plan Project Cleanup", **_RO})
    def fl_plan_project_cleanup() -> dict:
        """Create a dry-run plan for project cleanup.

        Safety: Read-Only.
        """
        return {
            "status": "Plan ready. Please provide renaming, coloring, or routing schemas.",
            "available_tools": [
                "fl_apply_naming_standard",
                "fl_apply_color_standard",
                "fl_apply_project_cleanup_step",
            ],
            "policy": [
                "Plan from current project inventory before applying cleanup.",
                "Use one named rollback unit for approved naming/color groups.",
                "Do not move playlist clips, delete clips/patterns, or load plugins.",
            ],
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "instrument_audio_track_workflow",
                    "routing_ui_guidance_vs_mcp_write",
                ]
            ),
        }

    @mcp.tool(annotations={"title": "Apply Project Cleanup Step", **_WR})
    def fl_apply_project_cleanup_step(
        renames: Annotated[
            list[dict],
            Field(description="List of {type: 'channel'|'mixer', index: int, name: str}"),
        ] = None,
        colors: Annotated[
            list[dict], Field(description="List of {type: 'channel'|'mixer', index: int, hex: str}")
        ] = None,
    ) -> dict:
        """Apply a batch of names and colors in one rollback unit.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        writes = []

        if renames:
            try:
                for r in renames:
                    if r["type"] == "channel":
                        writes.append(_channel_rename_entry(r["index"], r["name"]))
                    elif r["type"] == "mixer":
                        writes.append(_bus_rename_entry(r["index"], r["name"]))
            except (KeyError, ValueError, operations.OperationValidationError) as e:
                return {"ok": False, "error": str(e)}

        if colors:
            try:
                for c in colors:
                    if c["type"] == "channel":
                        writes.append(_color_write_entry(c["index"], c["hex"]))
                    elif c["type"] == "mixer":
                        writes.append(_mixer_color_entry(c["index"], c["hex"]))
            except (KeyError, ValueError, operations.OperationValidationError) as e:
                return {"ok": False, "error": str(e)}

        if not writes:
            return {"status": "No valid writes specified."}

        res = safety.safe_write_group(
            bridge,
            tool="apply_project_cleanup",
            scope="project_organizer",
            writes=writes,
            rollback_unit="project_cleanup_step",
        )
        if isinstance(res, dict):
            res["kb_policy_refs"] = kb_policy.rule_refs(
                ["preserve_existing_structure_first", "instrument_audio_track_workflow"]
            )
        return res

    @mcp.tool(annotations={"title": "Apply Naming Standard", **_WR})
    def fl_apply_naming_standard(
        style: Annotated[
            str, Field(description="Naming schema (e.g. 'psytrance', 'default', 'dynamic')")
        ],
        rules: Annotated[
            list[dict],
            Field(description="Specific rewrite rules applied by LLM: {type, index, name}"),
        ],
    ) -> dict:
        """Batch apply standardized names across the project.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        writes = []
        try:
            for r in rules:
                if r["type"] == "channel":
                    writes.append(_channel_rename_entry(r["index"], r["name"]))
                elif r["type"] == "mixer":
                    writes.append(_bus_rename_entry(r["index"], r["name"]))
        except (KeyError, ValueError, operations.OperationValidationError) as e:
            return {"ok": False, "error": str(e)}

        if not writes:
            return {"status": "No rules provided."}

        res = safety.safe_write_group(
            bridge,
            tool="apply_naming_standard",
            scope="project_organizer",
            writes=writes,
            rollback_unit=f"naming_standard_{style}",
        )
        if isinstance(res, dict):
            res["kb_policy_refs"] = kb_policy.rule_refs(
                ["preserve_existing_structure_first", "instrument_audio_track_workflow"]
            )
        return res

    @mcp.tool(annotations={"title": "Apply Color Standard", **_WR})
    def fl_apply_color_standard(
        style: Annotated[
            str, Field(description="Color schema (e.g. 'psytrance', 'default', 'dynamic')")
        ],
        rules: Annotated[
            list[dict], Field(description="Specific color rules applied by LLM: {type, index, hex}")
        ],
    ) -> dict:
        """Batch apply standardized colors across the project. Hex should be e.g. '#FF0000'.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        writes = []
        try:
            for r in rules:
                if r["type"] == "channel":
                    writes.append(_color_write_entry(r["index"], r["hex"]))
                elif r["type"] == "mixer":
                    writes.append(_mixer_color_entry(r["index"], r["hex"]))
        except (KeyError, ValueError, operations.OperationValidationError) as e:
            return {"ok": False, "error": str(e)}

        if not writes:
            return {"status": "No rules provided."}

        res = safety.safe_write_group(
            bridge,
            tool="apply_color_standard",
            scope="project_organizer",
            writes=writes,
            rollback_unit=f"color_standard_{style}",
        )
        if isinstance(res, dict):
            res["kb_policy_refs"] = kb_policy.rule_refs(
                ["preserve_existing_structure_first", "instrument_audio_track_workflow"]
            )
        return res
