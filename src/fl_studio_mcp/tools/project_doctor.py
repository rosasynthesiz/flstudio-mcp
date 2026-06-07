"""Project-level read-only diagnostics.

These tools aggregate existing safe primitives into high-signal reports.
"""

from __future__ import annotations

from fastmcp import FastMCP

from .. import kb_policy, protocol
from .. import project_templates as templates
from ..connection import fetch_all_pages, get_bridge
from ..music import mix_doctor as md


def _find_duplicate_names(rows: list[dict], key: str) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        name = str(row.get(key) or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return sorted([name for name, c in counts.items() if c > 1])


def _suggest_pattern_name(index: int) -> str:
    return f"Pattern {index}"


def register(mcp: FastMCP) -> None:
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }

    @mcp.tool(annotations={"title": "Project health report", **_RO})
    def fl_project_health_report() -> dict:
        """Build a read-only project health report from safe low-level reads.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        project = bridge.call(protocol.CMD_GET_PROJECT_STATE)
        channels = fetch_all_pages(bridge, protocol.CMD_CHANNEL_LIST, "channels").get(
            "channels", []
        )
        patterns = fetch_all_pages(bridge, protocol.CMD_PATTERN_LIST, "patterns").get(
            "patterns", []
        )
        playlist_tracks = fetch_all_pages(bridge, protocol.CMD_PLAYLIST_LIST_TRACKS, "tracks").get(
            "tracks", []
        )
        mixer_tracks = fetch_all_pages(bridge, protocol.CMD_MIXER_LIST_TRACKS, "tracks").get(
            "tracks", []
        )
        routing = fetch_all_pages(bridge, protocol.CMD_MIXER_GET_ROUTING_ALL, "routing").get(
            "routing", []
        )
        channel_routing = fetch_all_pages(
            bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels"
        ).get("channels", [])
        template_context = templates.classify_topology(
            mixer_tracks, routing, channel_routing
        )

        unassigned_channels = []
        for row in channels:
            idx = int(row.get("i", 0))
            detail = bridge.call(protocol.CMD_CHANNEL_GET, {"index": idx})
            if int(detail.get("target_fx_track", 0)) == 0:
                unassigned_channels.append({"index": idx, "name": detail.get("name", "")})

        findings = []
        if unassigned_channels:
            findings.append(
                {
                    "id": "unassigned_channels",
                    "severity": "medium",
                    "message": "Channels are still routed to Master only.",
                    "count": len(unassigned_channels),
                }
            )

        empty_pattern_names = [p for p in patterns if not str(p.get("name") or "").strip()]
        if empty_pattern_names:
            findings.append(
                {
                    "id": "unnamed_patterns",
                    "severity": "low",
                    "message": "Patterns with empty names found.",
                    "count": len(empty_pattern_names),
                }
            )

        dup_patterns = _find_duplicate_names(patterns, "name")
        if dup_patterns:
            findings.append(
                {
                    "id": "duplicate_pattern_names",
                    "severity": "low",
                    "message": "Duplicate pattern names found.",
                    "names": dup_patterns,
                }
            )

        dup_mixer = _find_duplicate_names(mixer_tracks, "name")
        if dup_mixer:
            findings.append(
                {
                    "id": "duplicate_mixer_names",
                    "severity": "low",
                    "message": "Duplicate mixer track names found.",
                    "names": dup_mixer,
                }
            )

        muted_playlist = [t for t in playlist_tracks if t.get("mute")]
        if muted_playlist:
            findings.append(
                {
                    "id": "muted_playlist_tracks",
                    "severity": "info",
                    "message": "Muted playlist tracks present (intentional or stale).",
                    "count": len(muted_playlist),
                }
            )

        return {
            "ok": True,
            "project": project,
            "summary": {
                "channels": len(channels),
                "patterns": len(patterns),
                "playlist_tracks": len(playlist_tracks),
                "mixer_tracks": len(mixer_tracks),
                "findings": len(findings),
            },
            "template_context": templates.compact_context(template_context),
            "findings": findings,
            "details": {
                "unassigned_channels": unassigned_channels,
            },
        }

    @mcp.tool(annotations={"title": "Export readiness report", **_RO})
    def fl_export_readiness_report() -> dict:
        """Build a read-only readiness report for stem/mix export prep.

        Safety: Read-Only.
        """
        report = fl_project_health_report()
        findings = list(report.get("findings", []))
        blockers = [f for f in findings if f.get("severity") in ("high", "medium")]
        return {
            "ok": True,
            "ready": len(blockers) == 0,
            "blockers": blockers,
            "advisories": [f for f in findings if f.get("severity") in ("low", "info")],
            "kb_policy_refs": kb_policy.rule_refs(["mastering_after_mix_readiness"]),
            "source": report,
        }

    @mcp.tool(annotations={"title": "Project dry-run fix plan", **_RO})
    def fl_project_dry_run_fix_plan(
        include_low_priority: bool = True,
    ) -> dict:
        """Build a read-only, ordered fix plan over existing rollback-safe tools.

        Safety: Read-Only.
        """
        report = fl_project_health_report()
        findings = list(report.get("findings", []))
        details = report.get("details", {})
        channels = fetch_all_pages(get_bridge(), protocol.CMD_CHANNEL_LIST, "channels").get(
            "channels", []
        )
        patterns = fetch_all_pages(get_bridge(), protocol.CMD_PATTERN_LIST, "patterns").get(
            "patterns", []
        )
        playlist_tracks = fetch_all_pages(
            get_bridge(), protocol.CMD_PLAYLIST_LIST_TRACKS, "tracks"
        ).get("tracks", [])

        actions = []
        action_id = 1

        unassigned = details.get("unassigned_channels", [])
        for row in unassigned:
            actions.append(
                {
                    "id": action_id,
                    "priority": "high",
                    "kind": "channel_routing",
                    "tool": "fl_assign_channel_to_free_mixer_track",
                    "params": {"channel": int(row["index"])},
                    "reason": "Channel is routed to Master only.",
                    "rollback": "single safe_write entry",
                }
            )
            action_id += 1

        if include_low_priority:
            unnamed = [p for p in patterns if not str(p.get("name") or "").strip()]
            for p in unnamed:
                idx = int(p.get("index", p.get("pattern", 0)))
                if idx <= 0:
                    continue
                actions.append(
                    {
                        "id": action_id,
                        "priority": "low",
                        "kind": "pattern_naming",
                        "tool": "fl_pattern_rename",
                        "params": {"index": idx, "name": _suggest_pattern_name(idx)},
                        "reason": "Pattern has an empty name.",
                        "rollback": "single safe_write entry",
                    }
                )
                action_id += 1

            duplicate_patterns = _find_duplicate_names(patterns, "name")
            for name in duplicate_patterns:
                dup_rows = [p for p in patterns if str(p.get("name") or "").strip() == name]
                for row in dup_rows[1:]:
                    idx = int(row.get("index", row.get("pattern", 0)))
                    if idx <= 0:
                        continue
                    actions.append(
                        {
                            "id": action_id,
                            "priority": "low",
                            "kind": "pattern_deduplicate",
                            "tool": "fl_pattern_rename",
                            "params": {"index": idx, "name": f"{name} ({idx})"},
                            "reason": "Pattern name duplicates another pattern.",
                            "rollback": "single safe_write entry",
                        }
                    )
                    action_id += 1

            muted_tracks = [t for t in playlist_tracks if t.get("mute")]
            for row in muted_tracks:
                actions.append(
                    {
                        "id": action_id,
                        "priority": "low",
                        "kind": "playlist_review",
                        "tool": "fl_playlist_set_mute",
                        "params": {"index": int(row["index"]), "state": False},
                        "reason": "Track is muted. Unmute only if mute is stale.",
                        "rollback": "single safe_write entry",
                        "manual_review": True,
                    }
                )
                action_id += 1

        actionable = [a for a in actions if a.get("priority") in ("high", "medium")]
        if include_low_priority:
            actionable = actions

        readiness = fl_export_readiness_report()
        return {
            "ok": True,
            "dry_run": True,
            "summary": {
                "findings": len(findings),
                "planned_actions": len(actions),
                "channels_scanned": len(channels),
                "patterns_scanned": len(patterns),
                "playlist_tracks_scanned": len(playlist_tracks),
            },
            "source_report": {
                "ready": readiness.get("ready"),
                "blockers": readiness.get("blockers"),
            },
            "plan": actionable,
            "notes": [
                "This tool is read-only and applies no FL changes.",
                "Execute one action at a time and verify readback before the next write.",
                "Use fl_rollback_last_change immediately if a write result is unexpected.",
            ],
        }

    @mcp.tool(annotations={"title": "Project health overview", **_RO})
    def fl_project_health_overview() -> dict:
        """Aggregates Project Organizer, Routing Review, and Mix Review insights into a single overview.

        Safety: Read-Only.
        """
        bridge = get_bridge()

        # 1. Routing Summary
        chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels").get(
            "channels", []
        )
        unrouted = sum(
            1
            for c in chans
            if not isinstance(c.get("target_mixer_track"), int) or c.get("target_mixer_track") == 0
        )

        # 2. General Health
        patterns = fetch_all_pages(bridge, protocol.CMD_PATTERN_LIST, "patterns").get(
            "patterns", []
        )
        mixer_tracks = fetch_all_pages(bridge, protocol.CMD_MIXER_LIST_TRACKS, "tracks").get(
            "tracks", []
        )
        routing = fetch_all_pages(bridge, protocol.CMD_MIXER_GET_ROUTING_ALL, "routing").get(
            "routing", []
        )
        template_context = templates.classify_topology(mixer_tracks, routing, chans)

        return {
            "status": "Overview Generated",
            "metrics": {
                "total_channels": len(chans),
                "unrouted_channels": unrouted,
                "total_patterns": len(patterns),
                "total_mixer_tracks": len(mixer_tracks),
            },
            "template_context": templates.compact_context(template_context),
            "recommendations": [
                "Run fl_analyze_project_organization to find unnamed/uncolored channels.",
                "Run fl_review_routing to find structural routing issues.",
                "Run fl_inspect_audio_clips to find loud audio clips.",
                "Run fl_review_mix or Mix Review watch mode to find clipping and EQ masking.",
            ],
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "mastering_after_mix_readiness",
                ]
            ),
        }

    @mcp.tool(annotations={"title": "Project preflight check", **_RO})
    def fl_check_project_preflight() -> dict:
        """Export readiness preflight checks including clipping, unrouted channels, and Stretch mode checklists.

        Safety: Read-Only.
        """
        bridge = get_bridge()

        # Basic scan
        chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels").get(
            "channels", []
        )
        routing = fetch_all_pages(bridge, protocol.CMD_MIXER_GET_ROUTING_ALL, "routing").get(
            "routing", []
        )
        template_context = templates.classify_topology(routing, routing, chans)
        unrouted = [
            c
            for c in chans
            if not isinstance(c.get("target_mixer_track"), int) or c.get("target_mixer_track") == 0
        ]

        audio_clips = [c for c in chans if c.get("type", {}).get("label") == "audioclip"]
        loud_audio_clips = [c for c in audio_clips if c.get("vol_norm", c.get("vol", 0)) > 0.8]

        wmax = md.get_watcher().last_max()
        master_peak_db = None
        if wmax and 0 in wmax:
            master_peak_db = md.lin_to_db(wmax.get(0))

        blockers = []
        if unrouted:
            blockers.append(f"{len(unrouted)} channels are unrouted (go straight to Master).")
        if master_peak_db is not None and master_peak_db >= 0.0:
            blockers.append(
                f"Master peak from Mix Review watch is {master_peak_db:.1f} dBFS (output/render clipping risk)."
            )

        advisories = []
        if loud_audio_clips:
            advisories.append(f"{len(loud_audio_clips)} audio clips are very loud (>80% vol).")
        if master_peak_db is not None and -1.0 < master_peak_db < 0.0:
            advisories.append(
                f"Master peak from Mix Review watch is {master_peak_db:.1f} dBFS; leave more headroom before mastering/export."
            )

        manual_checklist = [
            "Run Mix Review watch mode through the loudest section if Master peak data is missing.",
            "Check Audio Clip Stretch Mode manually; automatic Stretch Pro read/write is API-limited.",
            "Check Audio Clip Normalize manually; automatic Normalize read/write is API-limited.",
            "Keep FL Cloud Mastering, render, save, and export workflows manual in this MCP.",
        ]

        return {
            "status": "Ready for Export" if not blockers else "Export Blockers Found",
            "blockers": blockers,
            "advisories": advisories,
            "mix_readiness": {
                "master_peak_db": round(master_peak_db, 1) if master_peak_db is not None else None,
                "master_peak_source": "mix_review_watch" if master_peak_db is not None else None,
            },
            "template_context": templates.compact_context(template_context),
            "manual_checklist": manual_checklist,
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "master_peak_boundary",
                    "mix_doctor_master_output_boundary",
                    "mastering_after_mix_readiness",
                    "fl_cloud_mastering_manual_only",
                ]
            ),
        }

    @mcp.tool(annotations={"title": "Start guided cleanup assistant", **_RO})
    def fl_start_guided_cleanup() -> dict:
        """Start an LLM-orchestrated Guided Cleanup session.

        This tool returns a stateless session blueprint. It analyzes the current project
        using several diagnostic tools and returns the fix policy, prioritization strategy,
        and user-facing prompt instructions. The LLM must then drive the conversation
        using this blueprint.

        Safety: Read-Only (returns a policy and diagnostics, applies no fixes itself).
        """
        health = fl_project_health_overview()
        readiness = fl_check_project_preflight()

        return {
            "workflow_type": "LLM_ORCHESTRATED_WIZARD",
            "state_model": "STATELESS_MCP_AUTHORITATIVE",
            "assistant_instructions": [
                "1. You are now driving Guided Cleanup Mode. You must NOT present all issues at once.",
                "2. Treat MCP readbacks, diagnostics, and the changelog as the authoritative state, NOT your conversation history.",
                "3. Follow the prioritization strategy below. Pick the highest priority issue category.",
                "4. Explain the evidence for that specific issue to the user.",
                "5. Propose exactly ONE fix using an available write-safe tool (e.g. fl_apply_bus_layout, fl_apply_naming_standard, fl_apply_audio_clip_safe_defaults).",
                "6. Ask for the user's approval.",
                "7. Apply the fix. Then immediately read back the affected state and show the before/after result.",
                "8. Offer to rollback (via fl_rollback_last_change) or continue to the next issue.",
                "9. If the user continues, re-check diagnostics (via fl_get_guided_cleanup_context) to find the next issue.",
            ],
            "prioritization_strategy": [
                "Priority 1: Export Blockers (Unrouted channels to Master, Clipping)",
                "Priority 2: Audio Clip Safe Defaults (Loud clips, Stretch mode warnings)",
                "Priority 3: Routing Organization (Bus layouts, grouping)",
                "Priority 4: Project Cleanup (Naming, coloring)",
            ],
            "recommended_next_actions": [
                "Read fl_get_guided_cleanup_context to get the detailed current state.",
                "Present the highest priority finding to the user.",
            ],
            "initial_diagnostics": {"health_overview": health, "project_preflight": readiness},
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "mastering_after_mix_readiness",
                    "source_or_bus_trim_before_master_trim",
                ]
            ),
        }

    @mcp.tool(annotations={"title": "Get guided cleanup context", **_RO})
    def fl_get_guided_cleanup_context() -> dict:
        """Reconstruct the current Guided Cleanup context from fresh diagnostics.

        Use this tool during Guided Cleanup to get the latest, authoritative project state
        without relying on conversational history.

        Safety: Read-Only.
        """
        health = fl_project_health_overview()
        readiness = fl_check_project_preflight()

        # We instruct the LLM to run the deeper analyzers for the active priority
        return {
            "context_type": "FRESH_DIAGNOSTICS",
            "current_health_summary": health,
            "current_preflight_status": readiness,
            "instruction_to_llm": "Based on the summary above, determine the highest remaining priority. If you need deep details to propose a fix, run the corresponding analyzer:",
            "analyzer_mapping": {
                "Priority 1 (Routing Blockers)": "Run fl_review_routing",
                "Priority 2 (Audio Clips)": "Run fl_inspect_audio_clips",
                "Priority 3 (Bus Layouts)": "Run fl_review_routing",
                "Priority 4 (Naming/Coloring)": "Run fl_analyze_project_organization",
                "Priority 5 (Mix Headroom)": "Run fl_review_mix",
            },
            "changelog_state_hint": "Run fl_get_change_log_summary to review recently applied fixes if needed.",
            "kb_policy_refs": kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "mastering_after_mix_readiness",
                    "source_or_bus_trim_before_master_trim",
                ]
            ),
        }
