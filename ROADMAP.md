# FL Studio AI Assistant Roadmap

## Purpose
This file is the active execution roadmap for the branch.

## Current Implementation Scope
1. Safety primitives and change history
2. API-backed project organization and routing workflows
3. Product-level project preparation workflows
4. Creative intelligence and experimental infrastructure

## Current Stable Capabilities
- Mix Review
- Low-End/Stereo Safety Assistant
- Knowledgebase & Safe Wrappers
- Full-song peak watch
- Plugin parameter control
- Gain staging
- Reference match
- Bulk track control
- Track/channel coloring
- MIDI export
- Audio analysis basics
- Channel Type Classifier
- Project Organizer MVP
- Naming Standard Assistant
- Color Standardizer
- Routing Review 2.0
- Audio Clip Inspector
- Audio Clip Safe Defaults Assistant
- Project Health Overview MVP
- Project Preflight MVP
- Guided Cleanup Mode
- Change Log / Rollback UX improvements

## Verified FL Studio API Capabilities
- `channels.setChannelName` works
- `channels.setTargetFxTrack` works
- `channels.getChannelType` works and can distinguish `CT_AudioClip`, `CT_Sampler`, `CT_GenPlug`, etc.
- Mixer fader dB read/write calibration exists via empirical calibration table
- Controller/build-specific behavior must remain documented with build markers

## Known FL Studio API Limitations
- Stretch Mode cannot currently be read or set through the verified FL Python API path.
- Normalize cannot currently be read or set through the verified FL Python API path.
- Deep sample parameters are not exposed reliably.
- AudioClip handling may rename, route, color, lower volume, and produce manual checklists, but must not claim automatic Stretch Pro or Normalize handling.
- Native EQ type / high-pass configuration remains documented-unconfirmed unless a verified rollback-safe API path exists.
- Plugin loading/insertion remains manual.
- Playlist clip editing/deletion and destructive pattern/clip deletion remain out of scope.

## Completed Release Milestones

### v1.1.0 — Project Organization & Routing Intelligence
- [x] Channel Type Classifier
- [x] Project Organizer MVP
- [x] Naming Standard Assistant
- [x] Color Standardizer
- [x] Routing Review 2.0
- [x] Audio Clip Inspector
- [x] Audio Clip Safe Defaults Assistant
- [x] Project Health Overview MVP
- [x] Project Preflight MVP
- [x] Guided Cleanup Mode
- [x] Change Log / Rollback UX improvements

Verified live against FL Studio via TCP bridge on macOS, including guided cleanup workflow and EQ parameter application.

## Active Roadmap

### P0 — Safety and Evidence
- Keep safety primitives current
- Keep rollback by ID reliable
- Keep Knowledgebase entries updated
- Keep API capability audit updated
- Keep live verification checkpoints documented
- Preserve build-specific evidence with FL Studio build and controller marker

### P0.5 — Architecture Foundation & Tool Efficiency
- Regenerate the current tool inventory and lock the exact low-level
  consolidation scope before implementation.
- Consolidate redundant getter/setter tools into a compact low-level/domain
  surface; the target is roughly 19 low-level/domain tools plus retained
  product workflow tools.
- Keep high-value workflow tools such as Mix Review, Project Health, Routing
  Review, Project Organizer, audio analysis, MIDI export, resources, and
  Knowledgebase tools unless a later roadmap item explicitly removes them.
- Add an internal operation registry and validation layer before exposing new
  consolidated write paths.
- Strengthen grouped write safety before generic batching: pre-validate all
  operations, snapshot all write scopes before mutation, verify readback where
  supported, and handle partial failures with immediate rollback attempts.
- Add domain tools additively, then remove legacy low-level aliases only after
  parity tests, registration checks, documentation updates, and safety audit
  pass.
- Implement `fl_batch` with strict validation, a max 50 operation limit, one
  named rollback unit for persistent writes, and no mixed
  persistent/transient/external/Piano Roll batches without a separate safety
  design.
- Preserve the rollback contract; the safety audit must remain at 0 write gaps.

### P1 — Jam-to-Project / Structured Cleanup Workflows
- Jam Session Analyzer
- Jam Session Cleanup Plan Generator
- Grouped cleanup application with named rollback units
- Existing-structure preservation mode
- Bus placement policy:
  - default: `before_group`
  - supported: `before_group`, `after_group`, `central_front`, `central_end`, `preserve_existing`
- Send channel preparation
- Global automation lane preparation
- Send automation lane preparation
- Final Project Health / Preflight integration

### P2 — Product-level Workflows
- Export & Delivery Assistant
- Stem Export Manager
- Session Setup Templates
- Plugin Chain Assistant 2.0
- Arrangement Coach
- Energy Curve Analyzer
- Transition Review
- Sidechain Assistant
- Creative Block Breaker
- Explain My Mix
- Reference Track Deconstruction
- Handoff Report

### P3 — Later / Experimental / API-dependent
- Hook / Motif Coach
- Automation Analyzer
- Automation Pack Generator
- A/B Variant Manager
- Plugin Replacement Assistant
- CPU / Performance Review
- Compare Project Against Reference Structure
- Deep Sample & Loop Intelligence
- Optional TCP/push-event transport research
- Piano Roll readback research
- REC automation write/readback probes

## Current Next Release Candidates

### v2.0.0 — Architecture Foundation & Tool Efficiency

Goal:
Reduce LLM token consumption, tool-selection noise, and avoidable MCP
round-trips by consolidating redundant low-level getter/setter tools into a
compact domain-driven surface. The target is roughly 19 low-level/domain tools
plus retained product workflow tools, not a total cap for the whole MCP server.

Current baseline:
- 2026-06-07 registration baseline after legacy low-level alias removal:
  87 registered public FastMCP tools with 87 unique public names.
- Static audit baseline: 166 audited tool definitions, including 86 legacy
  low-level aliases intentionally absent from public registration.
- Registered safety-class summary: 33 `write-safe`, 41 `read-only`, 4
  `server-state`, 2 `external-write`, and 7 Knowledgebase tools registered
  outside the static AST audit pattern.
- The duplicate `project_doctor_tools.register(mcp)` call was removed as
  behavior-preserving registration cleanup.
- Phase 0 inventory and registration baseline is complete as of 2026-06-04.
  Full keep/consolidate/remove/blocked classification remains the next scope
  item before consolidation work starts.
- Phase 1 operation registry skeleton is complete as of 2026-06-04 with an
  internal, unregistered `OperationSpec` model covering representative mixer,
  channel, and tempo writes.
- Phase 1 expansion A is complete as of 2026-06-04. The internal registry now
  covers existing transport, mixer, and channel read, transient, and
  rollback-backed write primitives without public tool registration changes.
- Phase 1 expansion B is complete as of 2026-06-04. The internal registry now
  covers existing pattern, playlist track, effect-slot, native mixer EQ, and
  plugin-parameter primitives without public tool registration changes.
- Phase 2 verified grouped write safety is complete as of 2026-06-04.
  `safe_write_group` now pre-validates grouped writes, snapshots all scopes
  before mutation, performs per-write readback where supported, enforces
  explicit verify readback pairs, and attempts immediate reverse rollback after
  partial execution failure.
- Phase 3 additive domain tool transport is complete as of 2026-06-04.
  `fl_transport` validates through the operation registry and dispatches
  persistent transport writes through the existing rollback-backed safe-write
  path. As of 2026-06-05 it also exposes `ping`, and legacy transport aliases
  are no longer registered.
- Phase 3 additive domain tool mixer is complete as of 2026-06-04.
  `fl_mixer` validates through the operation registry and dispatches
  persistent mixer writes through the existing rollback-backed safe-write
  path. Legacy mixer aliases covered by `fl_mixer` are no longer registered.
- Phase 3 additive domain tool channel is complete as of 2026-06-04.
  `fl_channel` validates through the operation registry and dispatches
  persistent channel writes through the existing rollback-backed safe-write
  path. Actions: list, get, get_selected, get_steps, classify, select,
  set_color, set_mute, set_mixer_target, set_name, set_pan, set_solo,
  set_steps, set_volume. Legacy channel aliases covered by `fl_channel` are no
  longer registered.
- Phase 3 additive domain tools pattern and playlist are complete as of
  2026-06-04. `fl_pattern` and `fl_playlist` validate through the operation
  registry and dispatch persistent writes through the existing rollback-backed
  safe-write path. Playlist scope is track metadata/control only; playlist clip
  editing and pattern deletion remain unsupported.
- Phase 3 additive domain tools effect and plugin are complete as of
  2026-06-04. `fl_effect` and `fl_plugin` validate through the operation
  registry and dispatch persistent effect-slot, native EQ, and already-loaded
  plugin-parameter writes through the existing rollback-backed safe-write path.
  Plugin loading/insertion, plugin removal, preset navigation writes, and full
  effect-chain restore remain unsupported.
- Phase 3 additive domain tool Piano Roll is complete as of 2026-06-04.
  `fl_piano_roll` consolidates existing undo-backed note writes, transforms,
  marker helpers, and explicit readback-limit reports. Legacy Piano Roll
  one-off aliases are no longer registered. Piano Roll writes stay outside
  generic persistent batching because rollback is FL undo-backed and
  note/marker readback remains API-limited.
- Phase 4 read-only batch is complete as of 2026-06-04. `fl_batch` now accepts
  only strict-whitelisted operation-registry read specs, rejects raw protocol
  commands and script text, enforces a hard 50-operation limit, and supports
  `continue_on_error` for runtime read failures.
- Phase 4 persistent write batch is complete as of 2026-06-05. `fl_batch` now
  accepts homogeneous persistent-write registry specs through
  `safety.safe_write_group` as one named rollback unit, rejects
  `continue_on_error` for writes, and rejects mixed read/write/transient or
  excluded batches before mutation.
- Phase 4 persistent write batch review is complete as of 2026-06-05.
  `safe_write_group` now includes the current attempted write in immediate
  reverse rollback, covering bridge failures that mutate FL state before
  raising. Focused review checks remain green with 0 write gaps.
- Phase 5 product workflow internal refactor is complete as of 2026-06-05.
  Routing Review bus/route grouped writes and Mix Review trim-volume writes now
  prepare through the operation registry before dispatching through the
  existing safety layer. Project Organizer channel rename and hex color paths
  were intentionally left unchanged because their public input shapes do not
  exactly match current registry validation.
- Phase 6 legacy low-level removal is complete as of 2026-06-05. Redundant
  one-off aliases covered by domain tools were removed from public registration
  without deprecation wrappers. Product workflows, safety/history tools,
  resources, Knowledgebase tools, plugin preset guidance, and specialized
  workflow tools remain registered. Direct Internal EQ wrapper registration was
  removed in favor of `fl_effect`'s rollback-backed native EQ path.
- Product workflow Knowledgebase policy pass is complete as of 2026-06-06.
  Mix Review findings/proposals now carry source-qualified KB policy metadata
  and distinguish Master/output clipping from insert-track headroom risk.
  Project Health, Routing Review, Project Organizer, and Chain Planner expose
  relevant KB policy references without adding new FL write capabilities.
  Project Organizer color writes now prepare through operation-registry RGB
  validation instead of raw hex payloads.
- Product workflows remain in scope unless explicitly removed by a later
  roadmap item.
- Live macOS Smoke Test is complete as of 2026-06-06. Confirmed connection,
  heartbeat, ping (build marker `channels-v38`), and correct runtime behavior
  of all read-only Sweep tools. Verified rollback-safe mixer track color
  modification on Track 20 ("Toploop") from `#ABA362` to `#FF0080` and back
  to original.
- Focused product workflow regression coverage is complete as of 2026-06-06.
  Offline tests now lock the live-verified KB policy contracts for Project
  Health preflight/watch peaks, Routing Review index-preservation rules,
  Project Organizer registry-backed RGB color writes and invalid-color
  fail-fast behavior, and Chain Planner loaded-plugin/mastering boundaries.
  This adds no new FL Studio API claims or write paths.
- Mix Review output polish is complete as of 2026-06-06. User-facing findings
  and proposals now keep compact per-row KB metadata (`kb_rule_ids`,
  `kb_confidence_levels`, and `safety_limits`) while full source-qualified rule
  details remain centralized in top-level `kb_policy_refs`. This reduces token
  noise without changing diagnosis, planning, write paths, or safety behavior.
- Product workflow naming pass is complete as of 2026-06-06 as an intentional
  API-breaking cleanup. Public product workflow tool names now use Mix Review,
  Routing Review/Cleanup, Project Health/Preflight, and Guided Cleanup naming
  without compatibility aliases. Safety behavior and rollback-backed write
  paths are unchanged.
- Product workflow naming live smoke is complete as of 2026-06-07 on macOS.
  The current public names executed successfully against FL Studio Producer
  Edition v25.2.5 [build 5055] with controller marker `channels-v38`, and
  `fl_apply_mix_adjustment` passed a rollback-safe Track 20 fader write/readback
  test with exact restoration.
- Low-End/Stereo Safety Assistant is complete as of 2026-06-07. The new
  read-only `fl_review_low_end_stereo` tool reports bass/sub
  mono-compatibility risks, mixer pan and stereo-separation metadata, low-end
  layering, and Master headroom with compact KB policy references. Controller
  build marker `channels-v39` adds `stereo_sep` to `mixer_list_tracks` for
  efficient readback. Live FL verification is complete as of 2026-06-06, successfully reviewing stereo separation and low-end metadata across a loaded project.

- Data-driven standard template recognition is complete as of 2026-06-07. The
  template classifier now loads compact Knowledgebase profiles, scores live
  mixer/routing/channel readbacks against profile topology, annotates runtime
  roles and tool-policy suppression flags, and feeds Mix Review,
  Low-End/Stereo Review, Routing Review/Cleanup, Project Health/Preflight, and
  Project Organizer through the same template context. All fl studio advanced
  template names are represented; structurally identical pairs are reported as
  ambiguous candidate lists instead of false exact matches. This remains
  read-only and adds no FL write capability.
- Agent orientation resource is complete as of 2026-06-07. `fl://agent-briefing`
  provides a compact, read-only startup entrypoint with bridge/status summary,
  current domain/workflow tool guidance, Knowledgebase-first behavior, safety
  gates, and stop rules. It adds no FL write capability and is safe when the
  bridge is down.

Proposed scope:
- **Phase 0**: Inventory and registration baseline. Status: completed
  2026-06-04
  with `scripts/check_tool_registration_baseline.py`; duplicate Project Health
  registration does not affect the public tool count or tool-name set.
- **Phase 1**: Operation registry and validation layer sourced from existing
  safe primitives and Knowledgebase data where available. Status: skeleton
  completed 2026-06-04; transport/mixer/channel expansion A completed
  2026-06-04; pattern/playlist/effect/plugin expansion B completed
  2026-06-04.
- **Phase 2**: Verified grouped write safety. `safe_write_group` is already used
  by user-facing tools. Status: completed 2026-06-04 with stronger readback,
  explicit verify-pair enforcement, validation, and partial-failure rollback
  handling. Generic batch exposure remains a later phase and must still enforce
  strict operation whitelist rules.
- **Phase 3**: Add domain tools additively for parity testing. Status:
  transport, mixer, channel, pattern, playlist, effect, plugin, and Piano Roll
  completed 2026-06-04; remaining domain tool is optional `fl_safety`.
- **Phase 4**: Add `fl_batch` with strict whitelist validation and a hard max
  50 operation limit. Status: read-only batch completed 2026-06-04; persistent
  writes completed 2026-06-05 through verified grouped write safety.
- **Phase 5**: Refactor product workflows internally only where the operation
  registry reduces meaningful duplication without weakening safety. Status:
  completed 2026-06-05 for routing route writes, mixer bus renames, and Mix
  Review trim-volume writes.
- **Phase 6**: Remove legacy low-level tools without deprecation wrappers after
  parity tests, docs, Knowledgebase updates, registration checks, and safety
  audit pass. Status: completed 2026-06-05.

Safety:
- Consolidation and batching must not weaken the rollback contract.
- Persistent write batches must pre-validate every operation before mutation,
  snapshot all scopes before the first write, execute as one named rollback
  unit, and reject unsafe mixes of persistent writes, transient controls,
  external file writes, and Piano Roll undo-backed edits.
- `continue_on_error` is acceptable only for read-only batches unless a future
  safety design proves rollback-safe partial writes.
- `scripts/audit_tool_safety.py --fail-on-gaps` must remain green with 0 write
  gaps throughout the rollout.

### v2.1.0 — Jam-to-Project Assistant

Goal:
Turn an unstructured jam session into a structured, production-ready FL Studio project.
Reuse the v1.2 operation registry, domain tools, and batch infrastructure where
they are available and rollback-safe.

Proposed scope:
- `fl_analyze_jam_session()`
- `fl_plan_jam_session_cleanup()`
- `fl_apply_jam_session_cleanup_step(plan_id, step_id)`
- `fl_apply_jam_session_cleanup_group(plan_id, group_id)`
- `fl_finalize_jam_session_cleanup()`

The assistant should detect and organize inconsistent or missing names across:
- patterns
- playlist tracks
- channels/generators
- mixer tracks

It should also prepare or propose:
- consistent colors
- channel-to-mixer routing
- bus layout
- send channels
- global automation lanes
- send automation lanes
- final preflight checks

Safety:
- Plan first.
- No large cleanup without user approval.
- Each applied step or group must be one named rollback unit.
- Preserve recognizable existing structure when detected.
- Do not move/delete playlist clips.
- Do not delete patterns or clips.
- Do not load plugins.
- Do not claim automatic Stretch Pro or Normalize handling.

## Out of Scope For Current Push
- Plugin loading or insertion
- Playlist clip editing, placement, movement, or deletion
- Pattern or clip deletion
- Project open/new/save-as/render automation
- Raw controller/API escape hatches
- Broad UI automation tools
- Full FLP snapshot or full-project restore claims
- Unsafe automation recording tools
- Automatic Stretch Pro / Normalize handling

## Safety & Documentation Links
- [Engineering Standards](docs/ENGINEERING_STANDARDS.md)
- [API Capability Audit](docs/API_CAPABILITY_AUDIT.md)
- [Verification History](docs/VERIFICATION_HISTORY.md)
- [Backlog Research](docs/BACKLOG_RESEARCH.md)
