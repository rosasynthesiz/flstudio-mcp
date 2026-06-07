"""MCP tools for Mix Review: diagnose the whole mix + apply gated adjustments.

fl_review_mix is READ-ONLY (thin paginated snapshot + transparent threshold
diagnosis). fl_apply_mix_adjustment applies ONE proposed adjustment through the safety layer
(snapshot -> write -> FRESH readback -> rollback-able). Diagnosis never writes;
apply is a separate explicit call so the human approves each adjustment in conversation.

Grouping and EQ moves are surfaced as proposals but applied via the existing
fl_group_tracks / fl_apply_eq_intent tools (reuse, not re-implement).
"""

from __future__ import annotations

import math
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import kb_policy, operations, protocol, safety
from ..connection import fetch_all_pages, get_bridge
from ..music import mix_doctor as md
from ..project_templates import compact_context


def _compact_kb_fields(row: dict) -> dict:
    """Compact KB metadata for per-finding/proposal tool output."""
    rule_ids = [str(rule_id) for rule_id in (row.get("kb_rule_ids") or []) if rule_id]
    if not rule_ids:
        return {}
    out = {"kb_rule_ids": rule_ids}
    confidence = {}
    for rule_id in rule_ids:
        ref = kb_policy.rule_ref(rule_id)
        level = ref.get("confidence_level")
        if level is not None:
            confidence[rule_id] = level
    if confidence:
        out["kb_confidence_levels"] = confidence
    if row.get("safety_limits"):
        out["safety_limits"] = row["safety_limits"]
    return out


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
        "idempotentHint": False,
        "openWorldHint": True,
        "safetyClass": "write-safe",
    }

    def _result(snap):
        """Diagnose + plan a gathered snapshot -> the common tool payload."""
        diag = md.diagnose(snap)
        plan = md.plan_fixes(snap)
        proposals = []
        for p in plan["plans"]:
            prop = {
                "id": p["id"],
                "kind": p["kind"],
                "severity": p["severity"],
                "actionable": bool(p.get("actionable")),
                "human": p["human"],
                "reason": p.get("reason", ""),
            }
            if p["kind"] == "trim_volume":
                prop["track"] = p["track"]
                prop["target_db"] = p["target_fader_db"]
            elif p["kind"] == "group":
                prop["tracks"] = p.get("args")
            prop.update(_compact_kb_fields(p))
            proposals.append(prop)
        findings = []
        used_rule_ids = set()
        for f in diag["findings"]:
            row = {k: f[k] for k in ("rule", "severity", "track", "evidence", "message")}
            row.update(_compact_kb_fields(f))
            used_rule_ids.update(f.get("kb_rule_ids") or [])
            findings.append(row)
        for p in proposals:
            used_rule_ids.update(p.get("kb_rule_ids") or [])
        return {
            "track_count": snap["track_count"],
            "levels_valid": snap.get("levels_valid"),
            "template_context": compact_context(diag.get("template_context") or {}),
            "summary": plan["summary"],
            "findings": findings,
            "proposals": proposals,
            "notes": plan["notes"],
            "kb_policy_refs": kb_policy.rule_refs(sorted(used_rule_ids)),
        }

    def _low_end_stereo_result(snap):
        report = md.low_end_stereo_safety(snap)
        findings = []
        manual_checks = []
        used_rule_ids = set()
        for f in report["findings"]:
            row = {k: f[k] for k in ("rule", "severity", "track", "evidence", "message")}
            row.update(_compact_kb_fields(f))
            used_rule_ids.update(f.get("kb_rule_ids") or [])
            findings.append(row)
        for check in report["manual_checks"]:
            row = {k: check[k] for k in ("topic", "check", "reason")}
            row.update(_compact_kb_fields(check))
            used_rule_ids.update(check.get("kb_rule_ids") or [])
            manual_checks.append(row)
        return {
            "track_count": report["track_count"],
            "levels_valid": report["levels_valid"],
            "template_context": compact_context(report.get("template_context") or {}),
            "summary": report["summary"],
            "low_end_tracks": report["low_end_tracks"],
            "findings": findings,
            "manual_checks": manual_checks,
            "notes": report["notes"],
            "analysis_limits": report["analysis_limits"],
            "kb_policy_refs": kb_policy.rule_refs(sorted(used_rule_ids)),
        }

    @mcp.tool(annotations={"title": "Review mix", **_RO})
    def fl_review_mix() -> dict:
        """Scan the WHOLE mix and report problems + proposed fixes. READ-ONLY.

        Transparent threshold rules (clipping, headroom, level imbalance, missing
        high-pass, ungrouped tracks, EQ clashes) on a thin paginated snapshot;
        returns findings (severity + exact evidence) + concrete proposals.

        IMPORTANT: this samples peaks over only ~1.2s -- one MOMENT of the song,
        so it can MISS clipping in a drop/chorus that isn't playing right now. For
        full-song-accurate levels use WATCH mode: fl_mix_watch_start -> play the
        whole song -> fl_mix_watch_stop. If stopped, level rules are skipped
        (needs_playback). Applies nothing.

        Safety: Read-Only.
        """
        try:
            snap = md.gather_snapshot(get_bridge())
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        playing = snap["playing"]
        guidance = (
            "Project STOPPED -- press PLAY and call again, or use watch mode "
            "(fl_mix_watch_start -> play full song -> fl_mix_watch_stop)."
            if not playing
            else "NOTE: ~1.2s sample (one moment). For full-song peaks (catch the "
            "drop/chorus) use fl_mix_watch_start -> play -> fl_mix_watch_stop."
        )
        return {
            "ok": True,
            "playing": playing,
            "needs_playback": not playing,
            "peak_source": snap.get("peak_window", {}).get("source"),
            "guidance": guidance,
            **_result(snap),
        }

    @mcp.tool(annotations={"title": "Review low-end and stereo safety", **_RO})
    def fl_review_low_end_stereo() -> dict:
        """Report bass/sub mono compatibility, stereo-width risk, and Master
        headroom. READ-ONLY.

        Uses the same mixer snapshot path as Mix Review, plus mixer pan and
        stereo-separation metadata where the controller exposes it. This does
        not measure true phase correlation, mono-sum cancellation, or a spectral
        low band; those remain manual checks in the returned report.

        Safety: Read-Only.
        """
        try:
            bridge = get_bridge()
            wmax = md.get_watcher().last_max()
            snap = md.gather_snapshot(bridge, with_params=False, peaks_override=wmax or None)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        levels_valid = bool(wmax or snap.get("levels_valid"))
        guidance = (
            "Structural pan/stereo checks are available. For reliable hot low-end "
            "and Master-headroom evidence, press PLAY or use watch mode "
            "(fl_mix_watch_start -> play -> fl_mix_watch_stop)."
            if not levels_valid
            else "Read-only report. Treat stereo/phase items as manual checks; "
            "apply no widening, mid-side EQ, mastering, render, or plugin-loading "
            "automation from this assistant."
        )
        return {
            "ok": True,
            "playing": snap.get("playing"),
            "needs_levels": not levels_valid,
            "peak_source": "watch (full-song)"
            if wmax
            else snap.get("peak_window", {}).get("source"),
            "guidance": guidance,
            **_low_end_stereo_result(snap),
        }

    @mcp.tool(annotations={"title": "Apply mix adjustment (gated)", **_WR})
    def fl_apply_mix_adjustment(
        kind: Annotated[
            str, Field(description="Fix kind. Currently 'trim_volume' (the proven, safe one).")
        ],
        track: Annotated[
            int | None, Field(ge=0, description="Mixer track index (for trim_volume).")
        ] = None,
        target_db: Annotated[
            float | None, Field(description="Absolute target fader level in dB, e.g. -3.0.")
        ] = None,
    ) -> dict:
        """Apply ONE Mix Review adjustment via the safety layer: snapshot -> write ->
        FRESH readback -> rollback-able with fl_rollback_last_change.

        Call this ONLY after the user approves the exact change in conversation
        (Mix Review never auto-applies). 'trim_volume' sets a mixer track's fader
        to target_db. For grouping use fl_group_tracks; for EQ use
        fl_apply_eq_intent.

        Safety: Write-Safe with Rollback.
        """
        if kind != "trim_volume":
            return {
                "ok": False,
                "error": "only 'trim_volume' is wired here; use "
                "fl_group_tracks (grouping) or fl_apply_eq_intent (EQ moves).",
            }
        if track is None or target_db is None:
            return {"ok": False, "error": "trim_volume needs both track and target_db."}
        try:
            bridge = get_bridge()
            prepared = operations.prepare_operation(
                "mixer", "set_volume", {"track": track, "value": target_db, "unit": "db"}
            )
            res = safety.safe_write(
                bridge,
                **prepared.safe_write_kwargs(tool="mixer_set_volume"),
            )
            if res.get("dry_run"):
                return {"ok": True, "dry_run": True, "planned": res.get("planned")}
            before, after = res.get("before") or {}, res.get("after") or {}
            applied = after.get("vol_db") is not None and abs(after["vol_db"] - target_db) <= 0.6
            return {
                "ok": True,
                "kind": kind,
                "track": track,
                "name": after.get("name") or before.get("name"),
                "before_db": before.get("vol_db"),
                "after_db": after.get("vol_db"),
                "target_db": target_db,
                "applied": applied,
                "undo": "call fl_rollback_last_change to revert this",
            }
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @mcp.tool(annotations={"title": "Start full-song peak watch (Mix Review)", **_RO})
    def fl_mix_watch_start(
        interval_ms: Annotated[
            int, Field(ge=50, le=1000, description="Poll interval per round in ms (default 150).")
        ] = 150,
    ) -> dict:
        """Begin a peak-HOLD watch: continuously sample every mixer track's peak,
        keeping a RUNNING MAX per track, until fl_mix_watch_stop. Tell the user to
        PLAY the whole song (or at least the loudest section / the drop) while this
        runs -- then stop for full-song-accurate level diagnosis. Read-only.

        Safety: Read-Only.
        """
        try:
            bridge = get_bridge()
            tracks = fetch_all_pages(bridge, protocol.CMD_MIXER_LIST_TRACKS, "tracks").get(
                "tracks", []
            )
            indices = [t.get("i", t.get("index")) for t in tracks]
            r = md.get_watcher().start(bridge, indices, interval_ms=interval_ms)
            if not r.get("ok"):
                return {
                    "ok": False,
                    "error": r.get("error"),
                    "hint": "a watch is already running -- call fl_mix_watch_stop to finish it",
                }
            return {
                "ok": True,
                "watching_tracks": r["watching"],
                "interval_ms": r["interval_ms"],
                "message": "Watching peaks (running max). PLAY the full song / the drop, "
                "then call fl_mix_watch_stop for full-song diagnosis.",
            }
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @mcp.tool(annotations={"title": "Peak watch status (Mix Review)", **_RO})
    def fl_mix_watch_status() -> dict:
        """Is a peak watch running, and for how long / how many polls so far?

        Safety: Read-Only.
        """
        return {"ok": True, **md.get_watcher().status()}

    @mcp.tool(annotations={"title": "Stop peak watch + review mix", **_RO})
    def fl_mix_watch_stop() -> dict:
        """Stop the peak watch and diagnose on the FULL-SONG running-max peaks
        captured across the whole watch (accurate clipping/headroom/imbalance vs
        the ~1.2s snapshot). Read-only -- proposes fixes, applies nothing.

        Safety: Read-Only.
        """
        try:
            peaks_lin, reads, elapsed = md.get_watcher().stop()
            if not peaks_lin or reads == 0 or max(peaks_lin.values(), default=0.0) <= 0.0:
                return {
                    "ok": False,
                    "reads": reads,
                    "elapsed_s": round(elapsed, 1),
                    "error": "no peaks captured -- was the song playing during the watch?",
                }
            snap = md.gather_snapshot(get_bridge(), peaks_override=peaks_lin)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {
            "ok": True,
            "peak_source": "watch (full-song running max)",
            "watch": {"reads": reads, "elapsed_s": round(elapsed, 1)},
            "guidance": "Levels are full-song maxima -- trustworthy for clipping/headroom.",
            **_result(snap),
        }

    @mcp.tool(annotations={"title": "Review gain staging", **_RO})
    def fl_gain_stage() -> dict:
        """Propose per-track fader trims so each track's peak sits in a healthy
        band (~-12..-6 dBFS, aim -9) and the Master keeps -3..-6 dB headroom.
        READ-ONLY proposals -- apply approved ones via fl_apply_mix_adjustment (rollback).

        Uses FULL-SONG peaks from a recent watch (fl_mix_watch_start -> play ->
        fl_mix_watch_stop) when available; else a ~1.2s snapshot (prefer watch).
        FL's fader is POST-chain, so this sets a track's OUTPUT level, not a true
        pre-plugin input trim.

        Safety: Read-Only.
        """
        try:
            bridge = get_bridge()
            wmax = md.get_watcher().last_max()
            snap = md.gather_snapshot(bridge, peaks_override=wmax or None)
            if not (wmax or snap.get("levels_valid")):
                return {
                    "ok": True,
                    "needs_levels": True,
                    "guidance": "No level data -- press PLAY (or run watch mode: "
                    "fl_mix_watch_start -> play -> fl_mix_watch_stop) then call again.",
                }
            plan = md.gain_stage_plan(snap)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        proposals = [
            {
                "id": p["id"],
                "kind": p["kind"],
                "severity": p["severity"],
                "track": p["track"],
                "track_name": p["track_name"],
                "target_db": p["target_fader_db"],
                "actionable": True,
                "alternative": p.get("alternative", False),
                "human": p["human"],
                "reason": p["reason"],
                **_compact_kb_fields(p),
            }
            for p in plan["plans"]
        ]
        used_rule_ids = sorted(
            {rule_id for proposal in proposals for rule_id in (proposal.get("kb_rule_ids") or [])}
        )
        return {
            "ok": True,
            "peak_source": "watch (full-song)"
            if wmax
            else snap.get("peak_window", {}).get("source"),
            "aim_db": plan["target_db"],
            "healthy_band_db": plan["band"],
            "proposals": proposals,
            "notes": plan["notes"],
            "kb_policy_refs": kb_policy.rule_refs(used_rule_ids),
            "guidance": "Apply approved trims: fl_apply_mix_adjustment(kind='trim_volume', track, "
            "target_db=<proposal.target_db>). One at a time; undo via "
            "fl_rollback_last_change. Skip the 'alternative' Master trim if you "
            "already applied the source trims.",
        }

    @mcp.tool(annotations={"title": "Reference match (level/balance)", **_RO})
    def fl_reference_match(
        reference_audio_path: Annotated[
            str, Field(description="Path to a reference WAV/MP3 to compare against.")
        ],
    ) -> dict:
        """Compare your mix's LEVEL + rough tonal BALANCE to a reference track.
        READ-ONLY. Analyzes the reference FILE (overall level + low/mid/high
        spectral-band shares) and your mix (Master peak for level + a ROUGH
        name-based band estimate). HONEST: a level/balance compare, NOT a spectral
        match -- FL doesn't expose its output audio, so the your-mix balance is
        estimated from track names + peaks. Suggests adjustments; applies nothing.

        Safety: Read-Only.
        """
        import os

        if not os.path.isfile(reference_audio_path):
            return {"ok": False, "error": f"file not found: {reference_audio_path}"}
        try:
            from .audio import analyze_bands

            ref = analyze_bands(reference_audio_path)
            wmax = md.get_watcher().last_max()
            snap = md.gather_snapshot(get_bridge(), peaks_override=wmax or None)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if not (wmax or snap.get("levels_valid")):
            return {
                "ok": True,
                "needs_levels": True,
                "reference": ref,
                "guidance": "Reference analyzed, but no mix level data -- press PLAY or run "
                "watch mode (fl_mix_watch_start -> play -> stop), then call again.",
            }
        bal = md.mix_band_balance(snap)
        master = next((t for t in snap["tracks"] if t.get("index") == 0), None)
        mix_peak = master.get("peak_db") if master else None
        level_delta = (
            round(mix_peak - ref["peak_db"], 1)
            if (mix_peak is not None and ref.get("peak_db") is not None)
            else None
        )
        band_cmp = {}
        for b in ("low", "mid", "high"):
            r = ref.get("bands_pct", {}).get(b, 0.0)
            m = bal["bands_pct"][b]
            band_cmp[b] = {
                "reference_pct": r,
                "your_mix_pct": m,
                "delta_pct": round(m - r, 1),
                "rough_db": round(10 * math.log10((m or 0.01) / (r or 0.01)), 1),
            }
        return {
            "ok": True,
            "reference": ref,
            "your_mix_balance": bal,
            "your_mix_peak_db": mix_peak,
            "peak_source": "watch (full-song)"
            if wmax
            else snap.get("peak_window", {}).get("source"),
            "level_delta_db": level_delta,
            "band_comparison": band_cmp,
            "honest": "Level + ROUGH name-based balance only. Your-mix balance is estimated from "
            "track names + peaks, NOT FL's output spectrum. Reference bands are real "
            "(file analysis). +level_delta = your mix hotter; +band delta_pct = your "
            "mix has more energy in that band than the reference.",
            "kb_policy_refs": kb_policy.rule_refs(
                ["master_peak_boundary", "mix_doctor_existing_plugin_only"]
            ),
            "guidance": "Nudge via fl_apply_eq_intent (balance) / fl_apply_mix_adjustment (level): e.g. "
            "positive low delta -> high-pass/trim lows; negative high delta -> add_air.",
        }
