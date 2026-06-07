# Changelog

This changelog is curated from the repository commit history, release tags, and project documentation. It focuses on user-visible behavior, compatibility, safety guarantees, verification evidence, and known FL Studio API boundaries. Routine formatting, metadata refreshes, wording-only documentation passes, and one-off housekeeping commits are intentionally omitted unless they change the public release contract.

## v2.0.0-stable - Architecture Foundation, Tool Efficiency, and Safety-First Production Workflows

**Release date:** 2026-06-07  
**Status:** Stable  
**Source basis:** `main` through `d5dea16`  
**Replaces:** `v2.0.0-rc1` (`4ccfc85`)

### Release positioning

v2.0.0 stabilizes `flstudio-mcp` as a production-oriented MCP bridge for FL Studio, not merely a collection of low-level controller helpers. The release consolidates the public tool surface, introduces a registry-backed operation model, moves the recommended runtime bridge to a localhost TCP daemon, and makes rollback-first behavior the default expectation for persistent FL Studio mutations.

The release also makes a deliberate distinction between what can be safely automated through FL Studio's exposed Python/controller APIs and what must remain advisory or manual. That boundary is part of the stable contract, not a footnote.

### Breaking changes and migration notes

- **Legacy low-level aliases were removed from the public MCP surface.** Use the consolidated domain tools and product workflow tools instead of older one-purpose getter/setter aliases.
- **Tool names and product workflows were cleaned up for the stable API.** RC-era compatibility names and removed workflow aliases should not be treated as stable.
- **The recommended transport is the daemon bridge.** The intended topology is:
  `MCP client -> MCP server -> localhost TCP daemon -> MIDI SysEx -> FL Studio controller script`.
  The daemon owns the virtual MIDI ports and keeps them stable across MCP client restarts. FL Studio itself is not advertised as a native TCP server.
- **`fl_batch` and persistent writes are stricter.** The operation registry rejects unknown operations, unsafe mixtures, invalid write classes, and raw escape-hatch behavior instead of silently passing them through.
- **Some previously implied capabilities are now explicitly out of scope.** Automatic plugin insertion/loading, preset recall inside FL Studio, destructive playlist/pattern edits, audio rendering, FLP save/open automation, and Stretch Pro/Normalize clip mutation are not claimed unless FL Studio exposes reliable and rollback-safe APIs for them.

### Added

- **Consolidated domain tools** for the main FL Studio work areas:
  - `fl_transport`
  - `fl_mixer`
  - `fl_channel`
  - `fl_pattern`
  - `fl_playlist`
  - `fl_effect`
  - `fl_plugin`
  - `fl_piano_roll`
  - `fl_batch`
- **Registry-backed operation validation** for operation names, parameter schemas, read/write classification, allowed batching behavior, and safety policy checks before requests reach the bridge.
- **`fl_batch` execution** for lower-latency read workflows and controlled persistent-write groups, including whitelist validation, operation limits, and stricter separation between read-only and write-safe actions.
- **Rollback-first write groups** with named rollback units, scoped snapshots, readback expectations where supported, clearer changelog entries, and safer failure handling for partial write groups.
- **`fl://agent-briefing` resource** so MCP-compatible LLM agents can start from the compact public surface, current bridge/status context, Knowledgebase-first rules, stop rules, and rollback expectations.
- **Knowledgebase-backed policy metadata** for higher-level product tools, including compact rule references in findings and clearer separation between verified automation and advisory checklists.
- **Low-End/Stereo Safety Assistant** via `fl_review_low_end_stereo`, covering mono/stereo risk reporting, pan/stereo-separation metadata, low-end layering, and Master headroom checks.
- **Mix Review refinements** for clearer headroom/clipping findings, better threshold handling, compact per-row KB metadata, and less noisy rule reporting.
- **Project organization and routing workflows** for channel type classification, naming, colors, routing review, bus layout planning, guided cleanup, dry-run plans, and rollback-safe cleanup actions.
- **Preflight and project-health workflows** that combine mix, routing, organization, and export-readiness checks into higher-level reports instead of forcing agents to coordinate many low-level calls manually.
- **Plugin and preset library awareness** that inspects installed FL Studio plugin database entries and preset folders from disk to suggest chains and likely presets. These workflows are advisory and do not claim to load plugins or presets automatically inside FL Studio.
- **Live project resources** for common read-only state such as status, project, transport, channels, mixer, and patterns.
- **Audio and composition helpers carried forward into the stable line**, including audio analysis, MIDI export, scale/mode/raga composition assistance, piano-roll helpers, and rollback-aware pattern/channel/effect operations.

### Changed

- **The public tool surface is smaller and more intentional.** Dozens of one-off aliases were folded into domain actions and product workflows to reduce tool-selection noise and preserve context for project reasoning.
- **The repo's own changelog now identifies the compact public FastMCP footprint as 87 registered public tools.** The important release note is not the raw number itself, but the stable shift from alias-heavy exposure to a curated public API.
- **Documentation now centers on workflow boundaries.** README, roadmap, user guide, verification history, and Knowledgebase material describe supported production phases, known API gaps, setup requirements, safety classes, and live-verification expectations.
- **Transport documentation was corrected.** Stable wording now describes a standalone `fl-studio-mcp-daemon` that connects the MCP server to virtual MIDI/SysEx, rather than implying that FL Studio's controller sandbox directly hosts the public TCP transport.
- **Version and package metadata were moved to the 2.0.0 stable line**, including stable/production classifiers, supported platform notes, optional audio extras, and console entry points for the MCP server and daemon.
- **The maintained fork provenance is explicit.** The project keeps compatibility-oriented package/command names while documenting the `thunderdew-dawn/flstudio-mcp` fork as the maintained line.

### Fixed since v2.0.0-rc1

- Fixed Mix Review threshold logic so clipping/headroom findings align with intended pre-fader and output-risk semantics.
- Fixed Project Organizer issues around color validation and routed cleanup paths.
- Fixed server routing/resource hints so bridge connectivity failures are surfaced through the correct tools and clearer diagnostics.
- Added safety tests for bridge connectivity failure paths.
- Added RC1 live probes and regression tests around the compact public surface, routing, project organization, and safety primitives.
- Clarified the Low-End/Stereo Safety Assistant verification state and final TCP daemon architecture language in the stable docs.

### Verification included in the stable cut

- Final Low-End/Stereo live verification was added before this stable cut: `fl_review_low_end_stereo` and `mixer_list_tracks` stereo-separation readback were verified against a loaded FL Studio project, with controller marker `channels-v39`.
- The focused Mix Review/Low-End test set passed with 51 tests and 0 failures.
- The strict safety audit passed with 0 write gaps.
- Product workflow naming and public registration were live-smoked over the TCP daemon on macOS against FL Studio Producer Edition v25.2.5 build 5055 with controller marker `channels-v38`.
- A rollback-safe write smoke changed a mixer-track trim value and then restored it through `fl_rollback_last_change`.

### Safety contract

- Read-only tools must stay read-only.
- Dry-run tools must describe intended actions without mutating the FL Studio project.
- Persistent writes must pass through the operation registry and the rollback-aware safety layer where applicable.
- Grouped writes should be auditable as named rollback units.
- Product tools should prefer diagnostics, plans, and bounded fixes over broad irreversible edits.
- Unsupported FL Studio operations should be reported as limitations or manual checklist items, not hidden behind optimistic automation language.

### Known limitations and non-goals

These are intentionally documented so the stable release does not overpromise:

- FL Studio's public Python/controller APIs do not expose everything needed for full DAW automation.
- Plugin insertion/loading and preset recall remain advisory/manual workflows.
- Audio rendering, FLP save/open, and full project snapshot/restore are not part of the supported MCP contract.
- Playlist clip editing/deletion and destructive pattern deletion are outside the safe automation boundary.
- Stretch Pro, Normalize, and detailed Audio Clip parameter mutation remain unavailable unless FL Studio exposes reliable APIs.
- Mix and project analysis can highlight risks and propose bounded fixes, but it should not be described as mastering, source separation, or guaranteed audio-quality correction.
- Build-specific FL Studio behavior can change. New FL Studio versions, new controller markers, or newly exposed API paths should be re-smoked before claiming broader live support.

### Intentionally de-emphasized in release notes

The following work exists in the history but should not be headline material for v2.0.0-stable because it is mostly internal or supporting work:

- Formatting-only commits.
- Wording-only documentation reshuffles.
- Metadata/index refreshes that do not change behavior.
- One-off verification logs that only confirm already documented behavior.
- Packaging housekeeping that does not affect installation, runtime behavior, or supported APIs.
- Temporary compatibility shims removed before the stable release.

## v2.0.0-rc1 - Compact Public Tool Surface and Registry-Based Safety

**Release date:** 2026-06-05  
**Status:** Release candidate  
**Tag:** `v2.0.0-rc1`

### Added

- Initial compact domain-tool architecture for transport, mixer, channel, pattern, playlist, effects, plugins, piano roll, and batching.
- Central operation registry for validating tool operations and safety classes.
- Early `fl_batch` support for reducing round trips and tool-selection noise.
- Knowledgebase-backed product workflow policy references.
- Documentation and tests for the 2.0.0 tool migration and safety expectations.

### Changed

- Began retiring the legacy alias-heavy public surface in favor of domain action tools.
- Reworked README, roadmap, verification history, and package metadata for the 2.0.0 architecture line.
- Moved product workflows toward stable naming and clearer safety classes.

### Notes

The RC line validated the architecture but still required threshold fixes, routing/project-organizer fixes, final Low-End/Stereo verification, bridge failure tests, and final public API cleanup before stable publication.

## v1.1.0 - Project Organization and Routing Intelligence

**Release date:** 2026-06-04  
**Status:** Milestone release line; not present as a Git tag in the current repository tag list

### Added

- Channel Type Classifier for identifying likely buses, inserts, instruments, audio tracks, sends, and utility channels from live project state.
- Project Organizer planning and rollback-safe cleanup for naming, colors, and track organization.
- Routing Review and Routing Cleanup workflows for finding suspicious mixer routing, missing routes, and project-structure issues.
- Audio Clip Inspector and safer clip-state reporting within the limits of FL Studio's exposed APIs.
- Project Health, Preflight, and Guided Cleanup workflows for higher-level review before export or collaboration.
- Live capability sweeps and tests around project organization, routing, guided mode, and rollback behavior.

### Changed

- Shifted from individual helper tools toward more workflow-oriented project review tools.
- Documented FL Studio API gaps more clearly, especially around clip mutation, plugin loading, and destructive edits.

## v1.0.0 - Maintained Fork Baseline, Cross-Platform Support, and Safety Layer

**Release date:** 2026-06-02  
**Status:** Tagged stable baseline  
**Tag:** `v1.0.0`

### Added

- Maintained fork baseline with package metadata, installation flow, documentation, and verification history.
- Cross-platform support for Windows and macOS setup, including macOS installation guidance and transport compatibility work.
- Standalone daemon/MIDI bridge support for environments where MCP clients cannot directly open MIDI ports.
- Rollback-aware safety layer for persistent writes, including named rollback units and safer write history.
- Live MCP resources for status/project/transport/channel/mixer/pattern state.
- Mix Doctor and Mix Review foundations, including full-song peak-watch behavior instead of relying only on short snapshots.
- Gain staging, reference-match, genre chain, plugin-chain, preset-suggestion, and library-aware advisory tools.
- Audio analysis helpers for tempo/key/pitch-style analysis where optional dependencies are installed.
- MIDI export and composition helpers, including scale/raga-oriented generation support.
- Piano-roll, note-bridge, arrangement, plugin-parameter, and mixing-intent workflows inherited from the upstream project and hardened in the maintained fork.

### Changed

- Reframed the project from a minimal FL Studio MCP experiment into a documented, safety-aware maintained fork.
- Expanded tests, audits, and safety classification docs around write behavior.
- Improved macOS compatibility and SSE/client compatibility documentation.

## v0.2.0 - MIDI SysEx Bridge and Early Workflow Expansion

**Status:** Historical pre-stable line

### Added

- MIDI SysEx bridge approach after FL Studio controller-script file writes proved unreliable in the controller sandbox.
- Virtual MIDI port setup and controller-script communication model.
- Early project, mixer, channel, pattern, playlist, note, plugin-parameter, and transport tools.
- Early arrangement, note writing, plugin parameter, and mix-intent helpers.

### Notes

This line established the practical transport foundation, but the public surface was still low-level and noisy compared with the stable v2.0.0 domain-tool API.

## v0.1.0 - Initial Prototype

**Status:** Withdrawn / replaced by the MIDI SysEx approach

### Notes

The original file-queue-oriented prototype was superseded because FL Studio controller-script file writes were not reliable enough for a stable MCP workflow.
