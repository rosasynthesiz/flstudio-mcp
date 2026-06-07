# Agent Orientation

Compact startup path for LLM agents using FLStudioMCP with FL Studio.

## Startup Protocol

1. Read `fl://agent-briefing`.
2. Read `fl://status`; if the bridge is down, troubleshoot connection before
   live FL work.
3. Use `rg`, `kb_search`, `kb_get`, and capped resources before broad file reads
   or large tool calls.
4. Choose a current workflow/domain tool. Avoid raw FL API calls and removed
   one-off aliases.
5. For writes, plan the rollback unit before mutation.

## Tool-Choice Matrix

| User intent | Preferred high-level/workflow tool | Token-saving domain/read alternative |
|---|---|---|
| Check bridge/session health | `fl://agent-briefing`, `fl://status` | `fl_transport(action="ping")` |
| Project export readiness | `fl_check_project_preflight`, `fl_project_health_overview` | `fl://project`, `fl://mixer`, `fl://channels` |
| Diagnose mix problems | `fl_review_mix`, `fl_review_low_end_stereo` | `fl_mixer(action="list")`, `fl_batch` read batch |
| Review routing | `fl_review_routing`, `fl_plan_routing_cleanup` | `fl_get_routing_all`, `fl_channel(action="list")` |
| Organize names/colors/routes | `fl_plan_project_cleanup`, `fl_apply_project_cleanup_step` | `fl_channel`, `fl_mixer`, `fl_playlist` reads |
| Channel Rack edits | `fl_channel` | `fl://channels` |
| Mixer edits | `fl_mixer` | `fl://mixer` |
| Pattern or playlist metadata | `fl_pattern`, `fl_playlist` | `fl://patterns` |
| Effect slot/native EQ edits | `fl_effect` | `fl_effect` read actions |
| Already-loaded plugin params | `fl_plugin` | `fl_plugin(action="list_params")`, `kb_get_parameter_spec` |
| Piano Roll notes/transforms | `fl_piano_roll` | Readback-limit reports and dry-run plans |
| Many reads or grouped writes | `fl_batch` | Capped resources for first pass |
| Audio file analysis | `fl_analyze_audio`, `fl_extract_melody` | File-level `rg`/path checks first |
| MIDI export | `fl_export_midi` | Validate arrangement spec before file write |
| Values, ranges, mappings, pitfalls | Knowledgebase tools | `kb_search`, then specific `kb_get` |

## Token-Saving Strategy

- Start with `fl://agent-briefing`, `fl://status`, and capped resources.
- Use `rg` before reading large docs, scripts, or controller files.
- Use `kb_search` before opening Knowledgebase files.
- Use domain reads or `fl_batch` for known narrow state; avoid broad workflow
  calls until the user intent is clear.
- Keep detail calls scoped to the active track, channel, pattern, plugin, or
  workflow plan.

## Write Safety Gates

Every persistent FL write must follow:

1. Scoped snapshot.
2. Smallest practical write.
3. Readback verification where supported.
4. Changelog entry.
5. Rollback path.

Multi-step persistent changes must be one named rollback unit unless the split
is explicit and documented. Piano Roll writes stay undo-backed and must state
readback limits.

## Stop And Fallback Rules

- Do not guess normalized values, dB/Hz mappings, REC event IDs, track indices,
  plugin parameter indices, or valid ranges.
- Do not edit MIDI/TCP ports unless the user asks for setup troubleshooting.
- Do not auto-load plugins, insert plugins, delete patterns/clips, edit
  playlist clips, save-as, render, or use raw escape hatches.
- Do not promise Stretch Pro, Normalize, native EQ type, Piano Roll readback, or
  other unsupported FL API behavior.
- If bridge status, target selection, readback, rollback, or API support is
  unclear, switch to read-only, dry-run, probe-only, or manual guidance.

## Definition Of Done

- The selected tool path is current and Knowledgebase-informed.
- Writes, if any, are rollback-backed and verified by readback where supported.
- Unsupported API behavior is stated as a limit, not implied as completed work.
- Docs, roadmap/API audit, and Knowledgebase are updated when public MCP
  behavior changes.
- Verification covers the smallest meaningful resource/tool/test surface.
