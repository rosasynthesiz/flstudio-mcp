# Verification History

This file stores historical verification evidence, including dated live/offline verification checkpoints. It preserves dates, FL Studio build numbers, controller build markers, tested paths, results, blocked states, and rollback results.

## Current verification checkpoints

- 2026-06-07: Data-driven standard template classifier offline validation.
  - Verified path: Validated all compact profiles under
    `knowledgebase/templates/profiles/`, then ran parametric classifier,
    template-policy, and cleanup-preservation tests across the profile set.
    Also reran Mix Doctor and Project Doctor regression tests.
  - Result: The classifier recognizes all 13 unique standard template names
    represented by the profile set and exposes ambiguity for structurally
    identical pairs (`Chillout`/`Chillout-Ambient`, `HipHop-Trap`/`Trap`,
    `Funk`/`Rock`). Product workflows receive shared template context without
    performing any FL Studio writes.

- 2026-06-07: Template profile ingest offline validation.
  - Verified path: Added `knowledgebase/templates/template_profile.schema.json`,
    generated `knowledgebase/templates/profiles/electro.json` from the
    read-only Electro dump, and ran
    `scripts/validate_template_profiles.py --profile knowledgebase/templates/profiles/electro.json`.
    Added focused regression coverage in `tests/test_template_profile_tools.py`.
  - Result: The compact Electro profile validates against the schema and
    preserves placeholder ranges, sidechain-control routes, plugin signatures,
    channel routes, and tool-policy flags without reading or writing live FL
    Studio state.

- 2026-06-07: Electro template topology live read and workflow regression.
  - Verified path: Ran read-only live dump
    `scratch/scripts/read_electro_template_live.py` against the open `Electro`
    template over TCP on FL Studio Producer Edition v25.2.5 [build 5055],
    controller marker `channels-v38`. Added KB entries under
    `knowledgebase/templates/` and `knowledgebase/known_pitfalls/`. Ran focused
    offline tests and read-only live regressions for Mix Doctor and cleanup
    detection.
  - Result: The classifier recognized the `Electro` M/S premaster, stem buses,
    sidechain control bus, source tracks, and reserved placeholder bank.
    Stopped-template Mix Doctor output changed from 111 low findings to 0.
    Cleanup detection changed from 95 placeholder false positives to only
    `Insert 126`. No FL Studio project writes were performed.

- 2026-06-07: Low-End/Stereo Safety Assistant live verification.
  - Verified path: Added read-only `fl_review_low_end_stereo`, extended
    `mixer_list_tracks` readback with `stereo_sep`, and bumped the controller
    marker to `channels-v39`. Ran live readback parity check against FL Studio.
  - Result: 51 focused Mix Review/Low-End tests passed with 0 failures. Safety
    audit `scripts/audit_tool_safety.py --fail-on-gaps` passed with 0 write
    gaps. Live FL readback parity for controller marker `channels-v39` successfully confirmed across a loaded project on macOS.

- 2026-06-07: Product workflow naming live smoke on macOS.
  - Verified path: Ran `scripts/probes/test_product_workflow_naming_live.py`
    over the TCP daemon (port 9787) against FL Studio Producer Edition v25.2.5
    [build 5055] with controller build marker `channels-v38`. Confirmed public
    registration contains the new product workflow names and not the removed
    names. Executed read-only calls `fl_review_mix`, `fl_gain_stage`,
    `fl_review_routing`, `fl_project_health_overview`,
    `fl_check_project_preflight`, `fl_start_guided_cleanup`,
    `fl_get_guided_cleanup_context`, `fl_analyze_project_organization`, and
    `fl_setup_chain`.
  - Result: All read-only calls passed. Rollback-safe write smoke
    `fl_apply_mix_adjustment("trim_volume", track=20, target_db=-7.09)` changed
    Track 20 from `-6.84 dB` / `0.5718` normalized to `-7.09 dB` / `0.5639`
    normalized, then `fl_rollback_last_change` restored Track 20 to `-6.84 dB`
    / `0.5718` normalized. Result artifact:
    `scratch/product_workflow_naming_live_2026_06_07.json`.

- 2026-06-06: macOS SSE/TCP Live Smoke Sweep and Fader Color Rollback.
  - Verified path: Ran live verification on FL Studio Producer Edition v25.2.5 [build 5055] with controller build marker `channels-v38` over the SSE server (port 8080) and TCP bridge (port 9787). Executed read-only sweep tools (`fl_diagnose_mix`, `fl_gain_stage`, `fl_preflight_project`, `fl_analyze_routing`, `fl_analyze_project_organization`, and `fl_setup_chain`). Performed a write-and-rollback color modification test on Track 20 ("Toploop") from `#ABA362` to `#FF0080` and back.
  - Result: All read-only tools correctly reported findings, safety boundaries, and mapped Knowledgebase policy rule references. The fader track color test successfully verified write, readback, LIFO rollback, and clean restoration to the original state.

- 2026-06-05: v2.0.0 Architecture Foundation & Tool Efficiency.
  - Verified path: Executed static safety audit (`scripts/audit_tool_safety.py`). Consolidated dozens of single-purpose functions into unified `fl_transport`, `fl_mixer`, `fl_channel` endpoints. Replaced legacy single-tool registration with centralized operation registry. Validated `safe_write` and `safe_write_group` behavior under the new architecture. Updated package version and documentation.
  - Result: Massive reduction in tool-selection noise and MCP token consumption. Backward-incompatible tool API overhaul correctly signaled via major version bump. Rollback layer integrity maintained.

- 2026-06-04: v1.1.0 Project Organization & Routing Intelligence.
  - Verified path: Executed static safety audit (`scripts/audit_tool_safety.py --fail-on-missing-safety-docs`). Created and executed `scripts/probes/test_v1_1_0_tools.py` via Python, which deliberately mutated a channel via `safe_write`, triggered analyzers (`fl_analyze_project_organization`, `fl_inspect_audio_clips`, `fl_analyze_routing`, `fl_project_health_dashboard`, `fl_preflight_project`), then executed batch routing and naming fixes via `safe_write_group`, followed by sequential LIFO rollbacks to cleanly restore project state.
  - Result: All batch write tools (`fl_create_bus_layout`, `fl_apply_naming_standard`) successfully created scoped snapshot arrays and reverted cleanly. Discovered and fixed missing `scope` kwargs in internal `safe_write_group` invocations. `CMD_CHANNEL_ROUTING_SUMMARY` extension successfully eliminated N+1 API read delays for channel types and volumes. All tools correctly registered and verified as `read-only` or `write-safe`.

- 2026-06-03: Empirically calibrated mixer fader volume curve implemented.
  - Verified path: Deployed updated `fl_controller/FLStudioMCP/device_FLStudioMCP.py` to FL Studio's Hardware settings folder; executed live fader sweep to capture 101-point calibration table (`scratch/fader_calibration.json`); verified target dB to normalized value linear interpolation via `scratch/verify_mixer_fader.py` and applied gain staging to 13 tracks via `scratch/apply_mix_gains.py`.
  - Result: Mixer track volume reads now return the actual, true decibel levels directly from FL Studio (`mixer.getTrackVolume(t, 1)`), and volume writes convert requested dB levels to precise normalized fader values using linear interpolation on the empirical calibration table. All writable tracks in the user's project were set to their exact target dB levels. Identified 21 tracks locked by active automation clips in the project that ignore external writes.
- 2026-06-02: Dynamic mixer-track guards and transient plugin-read retries
  added.
  - Verified path: `compileall` for connection, safety, target helpers, mixer,
    channel, plugin, effect, and routing modules; focused offline tests
    `scripts/test_dynamic_mixer_targets.py`, `scripts/test_channel_organizer.py`,
    `scripts/test_plugin.py`, and `scripts/test_effects_pattern_extensions.py`.
  - Result: mixer/plugin/effect/channel/routing tools now validate requested
    mixer-track indices against the current dynamic `mixer_track_count` before
    dispatching FL commands; missing tracks are reported as project/fixture
    state rather than API failure. Plugin parameter reads retry transient
    timeouts, and plugin parameter writes use idempotent value readback
    verification. Creating new dynamic mixer tracks remains probe-gated until
    a rollback-safe Image-Line API path is live-probed.
- 2026-06-02: User-facing value, workflow, and tool-reference documentation
  added.
  - Verified path: `docs/USER_GUIDE.md` reviewed against
    `scripts/audit_tool_safety.py --format json` output; README usage entry
    linked to the guide; stale pattern-creation limit language corrected in
    server instructions and this roadmap.
  - Result: public docs now explain the app's production value, natural-language
    assistant interaction model, module-level examples, MCP resources, safety
    classes, explicit product boundaries, and the current 138-tool catalog.
- 2026-06-02: Fork provenance and repository metadata aligned with the
  maintained `thunderdew-dawn/flstudio-mcp` branch.
  - Verified path: README, CONTRIBUTING, package metadata, MCP server metadata,
    Glama metadata, LICENSE, and NOTICE reviewed for current maintainer,
    upstream attribution, compatibility-preserving package names, and explicit
    rollback-first fork direction.
  - Result: public-facing source metadata now distinguishes this maintained
    fork from upstream without breaking the existing `fl-studio-mcp` package or
    command names.
- 2026-06-02: `AGENTS.md` repository workflow guide updated and approved for
  commit.
  - Verified path: `AGENTS.md` reviewed for repo-safe relative paths and no
    remaining local-only/no-commit instruction.
  - Result: future AI-assisted sessions now have a committed workflow guide
    covering first reads, rollback-first safety posture, documented-API
    false-positive handling, roadmap discipline, verification expectations,
    and live FL procedure.
- 2026-06-02: README now pins the known-working FL Studio build range.
  - Verified path: README requirements section reviewed with `rg` check for
    `v25.2.5`, `build 5055`, and controller marker `channels-v38`.
  - Result: requirements now state the observed known-working FL Studio
    Producer Edition v25.2.5 build 5055/controller `channels-v38` baseline and
    keep FL 20.7+ as MIDI-scripting foundation rather than a guarantee that all
    build-specific write APIs behave identically.
- 2026-06-02: GitHub Actions CI for hard lint, safety audits, and mock bridge
  smoke test added.
  - Verified path: local run of CI commands: `compileall src
    scripts/test_bridge_mock.py scripts/audit_tool_safety.py`; `ruff check
    --select E9,F src fl_controller/FLStudioMCP/device_FLStudioMCP.py
    scripts/audit_tool_safety.py scripts/test_bridge_mock.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`;
    `scripts/audit_tool_safety.py --fail-on-missing-safety-docs --format json`;
    `scripts/test_bridge_mock.py`.
  - Result: `.github/workflows/ci.yml` now runs a no-FL mock TCP bridge smoke
    plus hard Python-error linting and safety gates. Full `ruff check .` still
    has pre-existing style failures in older controller/live-test scripts, so
    CI intentionally scopes linting to hard `E9,F` errors for the core surface.
- 2026-06-02: Prompt-level eval suite added for the FLStudioMCP production
  tool surface.
  - Verified path: `python3 -m json.tool evals/evals.json`; manual coverage
    check confirms 10 scenarios spanning bridge/transport, project reports,
    channel steps, mixer/routing/bulk/color, patterns/playlist/arrangement,
    Piano Roll/scale composition, plugin/effect intents, Mix Doctor,
    audio/preset/chain planning, and documented-API false-positive handling.
  - Result: `evals/evals.json` now captures expected tool choices and safety
    expectations for regression review.
- 2026-06-02: FL Studio production skill orchestration layer updated.
  - Verified path: `wc -l` confirms `skills/flstudio-production/SKILL.md` is
    under 500 lines; frontmatter/reference existence check passed; all `fl_*`
    tools named in `references/tool-map.md` resolve to registered tool
    functions.
  - Result: the skill now points to real one-level references for limits, tool
    selection, workflows, and troubleshooting; stale non-existent preset/kuthu
    tool names were removed; the skill documents rollback-first behavior and
    documented-API false-positive probe discipline.
- 2026-06-02: Compose and MIDI Export tools now have safety-class docstrings
  and MCP annotations; the strict safety-doc audit passes for the full tool
  surface.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/compose.py` and
    `src/fl_studio_mcp/tools/export.py`; targeted `audit_file` check for
    Compose and MIDI Export tools' `safetyClass` and `Safety:` docstrings;
    `scripts/test_compose.py`; `scripts/test_midi_export.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`;
    `scripts/audit_tool_safety.py --fail-on-missing-safety-docs --format json`.
  - Result: undo-backed raga/scale Piano Roll writes, scale catalogue reads,
    and the external MIDI-file export now report explicit safety classes.
    Safety-class docstrings and MCP annotations are complete across the
    audited tool surface.
- 2026-06-02: Bulk mute/solo and Color tools now have safety-class docstrings
  and MCP annotations.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/bulk.py` and
    `src/fl_studio_mcp/tools/color.py`; targeted `audit_file` check for every
    Bulk and Color tool's `safetyClass` and `Safety:` docstring;
    `scripts/test_bulk.py`; `scripts/test_color.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: rollback-backed grouped mixer mute/solo reset, mixer-track color,
    and channel-color tools now report explicit write-safe safety classes. The
    manual `scripts/test_color_live.py` probe was not counted for this
    metadata-only slice.
- 2026-06-02: Read-only Audio Analysis, Chain Planning, Preset Suggestion, and
  Project Doctor tools now have safety-class docstrings and MCP annotations.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/audio.py`,
    `src/fl_studio_mcp/tools/chains.py`,
    `src/fl_studio_mcp/tools/presets.py`, and
    `src/fl_studio_mcp/tools/project_doctor.py`; targeted `audit_file` check
    for every touched tool's `safetyClass` and `Safety:` docstring;
    `scripts/test_audio_analysis.py`; `scripts/test_chains.py`;
    `scripts/test_preset_library.py`; `scripts/test_project_doctor.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: offline audio/key analysis, monophonic melody extraction, genre
    chain planning, installed-plugin/preset library reads, and project/export
    readiness reports now report explicit read-only safety classes.
- 2026-06-02: Arrangement tools now have safety-class docstrings and MCP
  annotations.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/arrange.py`;
    targeted `audit_file` check for every Arrangement tool's `safetyClass`
    and `Safety:` docstring; `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: rollback-backed pattern creation, pattern clone, channel selection,
    and marker-add tools now report explicit safety classes. The existing
    `scripts/test_arrange_mechanic.py` live script was not counted for this
    slice because it directly creates patterns/markers and is explicitly not a
    rollback-safe smoke test.
- 2026-06-02: Mix Doctor and Mixing Intent tools now have safety-class
  docstrings and MCP annotations.
  - Verified path: `compileall` for
    `src/fl_studio_mcp/tools/mix_doctor.py` and
    `src/fl_studio_mcp/tools/mixing.py`; targeted `audit_file` check for
    every Mix Doctor and Mixing Intent tool's `safetyClass` and `Safety:`
    docstring; `scripts/test_mix_doctor.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`; TCP live preflight with
    `fl_ping` on FL Studio Producer Edition v25.2.5 (build 5055), controller
    build marker `channels-v38`.
  - Result: Mix Doctor read-only/gated-write tools and rollback-backed
    grouped Mixing Intent writes now report explicit safety classes. Pure
    curve/logic checks in `scripts/test_mixing_intents.py`,
    `scripts/test_reverb_delay_intents.py`, and
    `scripts/test_compression_intents.py` passed, but rollback-safe live plugin
    writes were blocked by missing fixture plugins on the expected targets
    (track 2 slot 0, no reverb/delay on track 2, and track 9 slot 4). No
    plugin loading was attempted because loading plugins is prohibited.
- 2026-06-02: Channel Organizer and Step Sequencer tools now have
  safety-class docstrings and MCP annotations.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/channels.py`;
    targeted `audit_file` check for every channel tool's `safetyClass` and
    `Safety:` docstring; `scripts/test_channel_organizer.py`;
    `scripts/test_step_sequencer.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: channel detail/assignment reads and rollback-backed channel
    naming, mixer-target, and step-sequencer writes now report explicit safety
    classes.
- 2026-06-02: Piano Roll tools now have safety-class docstrings and MCP
  annotations.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/pianoroll.py`;
    targeted `audit_file` check for every Piano Roll tool's `safetyClass` and
    `Safety:` docstring; `scripts/test_pianoroll.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: undo-backed Piano Roll note, marker, quantize, transpose,
    duplicate, velocity-ramp, and API-limited readback tools now report explicit
    safety classes and keep their readback limitations visible.
- 2026-06-02: Phase 1 project/mixer/channel/safety tools now have
  safety-class docstrings and MCP annotations.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/phase1.py`;
    targeted `audit_file` check for every Phase 1 tool's `safetyClass` and
    `Safety:` docstring; `scripts/test_mixer.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: project, mixer, channel, changelog, rollback, dry-run, and
    external changelog-export tools now report explicit safety classes without
    changing their rollback behavior.
- 2026-06-01: Routing tool safety-class docstrings and MCP annotations added.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/routing.py`;
    targeted `audit_file` check for every routing tool's `safetyClass` and
    `Safety:` docstring; `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: routing reads, cleanup candidate diagnosis, single route writes,
    and grouped bus routing now report explicit safety classes. No live routing
    write was run for this metadata-only slice.
- 2026-06-01: Plugin parameter tool safety-class docstrings and MCP
  annotations added.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/plugin.py`;
    targeted `audit_file` check for every plugin tool's `safetyClass` and
    `Safety:` docstring; `scripts/test_plugin.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: plugin listing, parameter reads, preset-name reads, manual preset
    navigation plans, and rollback-backed already-loaded plugin parameter
    writes now report explicit safety classes.
- 2026-06-01: Pattern and Playlist tool safety-class docstrings and MCP
  annotations added.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/phase3.py`;
    targeted `audit_file` check for every Pattern/Playlist tool's
    `safetyClass` and `Safety:` docstring; `scripts/test_pattern_playlist.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: Pattern and Playlist read/write tools now report explicit
    read-only or write-safe safety classes while preserving rollback-backed
    write behavior.
- 2026-06-01: Transport tool safety-class docstrings and MCP annotations added.
  - Verified path: `compileall` for `src/fl_studio_mcp/tools/transport.py`;
    targeted `audit_file` check for every transport tool's `safetyClass` and
    `Safety:` docstring; `scripts/audit_tool_safety.py --fail-on-gaps`;
    `scripts/test_bridge.py` against FL Studio Producer Edition v25.2.5 (build
    5055), controller build marker `channels-v38`.
  - Result: read-only, transient runtime, and rollback-backed transport tools
    now report explicit safety classes. The live bridge test restored tempo
    from 147 BPM back to 142 BPM and ended with playback stopped and recording
    disarmed.
- 2026-06-01: Safety-class documentation audit support added offline, with
  the Effect Slot and Native EQ tool module updated as the first annotated
  module.
  - Verified path: `compileall` for `scripts/audit_tool_safety.py` and
    `src/fl_studio_mcp/tools/effects.py`;
    `scripts/test_effects_pattern_extensions.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`;
    `scripts/audit_tool_safety.py --fail-on-missing-safety-docs --format json`.
  - Result: the audit output now reports each tool's `safetyClass` annotation
    and whether the function docstring contains a `Safety:` section. The new
    strict doc gate intentionally remains non-standard for now because the
    remaining modules still need migration; the existing write-gap gate stays
    green.
- 2026-06-01: Native EQ type mapping probe ran on FL Studio Producer Edition
  v25.2.5 (build 5055), controller build marker `channels-v38`; no working
  high-pass type mapping found.
  - Verified path: installed updated controller script into
    `~/Documents/Image-Line/FL Studio/Settings/Hardware/FLStudioMCP/`,
    reloaded FL MIDI scripts, confirmed `fl_ping` build `channels-v38`, then
    ran `scripts/probe_native_eq_type_live.py`.
  - Result: raw integer, update-only, MIDI-scaled, and candidate type values
    all read back as Native EQ `type=0` on mixer track 8 `Drums`, band 0.
    Float variants were rejected by FL's `processRECEvent` binding because the
    value must be an integer. Each attempted write used immediate rollback.
  - Decision: do not expose Native EQ high-pass/type configuration as a
    user-facing tool on this build. Keep Native EQ type writes
    `documented-unconfirmed`/manual until a different FL build or API path
    proves a visible, rollback-safe type mutation.
- 2026-06-01: Named rollback-unit metadata added offline for write history.
  - Verified path: `scripts/test_change_history.py`;
    `scripts/test_step_sequencer.py`; `scripts/test_bulk.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: `safe_write` and `safe_write_group` now persist a
    `rollback_unit` name in changelog entries and recent summaries. Bulk
    mute/solo/reset, routing group, and step sequencer batch writes now pass
    explicit rollback-unit names so grouped/batch operations are easier to
    audit before rollback.
  - Note: `scripts/test_group_tracks.py` is live-only and was not counted in
    the offline verification set.
- 2026-06-01: Native EQ type mapping probe infrastructure added offline.
  - Verified path: `compileall` for `src/fl_studio_mcp/protocol.py`,
    `fl_controller/FLStudioMCP/device_FLStudioMCP.py`,
    `scripts/probe_native_eq_type_live.py`, and
    `scripts/run_live_capability_sweep.py`;
    `scripts/test_effects_pattern_extensions.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: controller build marker bumped to `channels-v38`; added the
    constrained internal `mixer_probe_eq_type` command and
    `scripts/probe_native_eq_type_live.py` to test Native EQ type REC event
    value/flag variants with immediate rollback. This is probe-only and does
    not expose a user-facing raw API surface.
  - Next action: reload FL MIDI scripts, confirm `fl_ping` reports
    `channels-v38`, then run `scripts/probe_native_eq_type_live.py`.
  - Live preflight: attempted immediately after implementation; blocked as
    expected because FL still reported controller build `channels-v37`.
- 2026-06-01: Phase A API-backed snapshot scopes marked complete offline.
  - Verified path: `scripts/test_safety_scopes.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: snapshot coverage now includes channel state, channel steps,
    pattern state/current selection, playlist tracks, effect slots, track slot
    bypass state, project time signature, and native mixer EQ. Added focused
    test assertions for the previously implicit channel and track-slot scopes.
- 2026-06-01: Targeted Native EQ high-pass write on mixer track 8 `Drums`
  did not pass; visual check confirmed no visible mixer EQ change, and rollback
  restored the original EQ state.
  - Verified path: daemon started locally via `.venv/bin/fl-studio-mcp-daemon`,
    `fl_ping` on FL Studio Producer Edition v25.2.5 (build 5055), controller
    build marker `channels-v37`; read mixer track 8; attempted
    rollback-backed `mixer_set_eq` on band 0 with frequency normalized for 120
    Hz and high-pass type value `3`.
  - Result: frequency readback changed from `0.0882` to `0.2594`, but EQ type
    stayed `0` instead of `3`, so the write was not a verified high-pass.
    User visual inspection found no visible change on mixer track 8. Rollback
    by change ID `chg_1780338910870602000_e18e5076` restored band 0 to
    frequency `0.0882`, bandwidth `0.267`, gain `0.5`, type `0`.
  - Next action: Native EQ type writes need a narrower REC event/value mapping
    probe before user-facing high-pass configuration can be promised. Track 8
    had no loaded plugin slots, so no already-loaded EQ2 fallback was available
    without violating the no-plugin-loading rule.
- 2026-06-01: Documented-API false-positive live probe ran on FL Studio
  Producer Edition v25.2.5 (build 5055), controller build marker
  `channels-v37`; did not fully pass, but produced narrower evidence.
  - Verified path: daemon started locally via `.venv/bin/fl-studio-mcp-daemon`,
    `fl_ping`, `scripts/probe_documented_api_live.py`, and
    `scripts/test_effect_targets_live.py`.
  - Result: `patterns.setPatternLength` is documented but not exposed by
    `dir(patterns)` on this runtime, and the rollback-safe write command
    returned API unavailable without mutating state. Keep it
    `documented-unconfirmed` for this build rather than deleting support.
  - Result: `mixer.setPluginMixLevel` is documented and works on at least one
    occupied target (Master track 0, slot 8, `Fruity parametric EQ 2`) in both
    direct and selected-track variants with rollback verified. It still did not
    stick on track 49 slot 0 `Fruity Limiter` or track 50 slot 0 `Fruity
    parametric EQ 2`; treat failures as target/plugin/state dependent, not
    globally `api-limited`.
  - Result: native mixer EQ setters are present, but gain writes did not stick
    on tracks 0, 1, 49, or 50 while rollback/restore remained safe. Keep Native
    EQ writes `documented-unconfirmed` until a narrower target/state probe
    proves a working path.
  - Result: Fruity Limiter generic parameter writes still did not stick across
    exposed parameters; Fruity Parametric EQ 2 plugin parameter write/readback
    still passed on Band 4 level.
- 2026-06-01: Documented-API false-positive probe infrastructure added
  offline.
  - Verified path: `compileall` for `src/fl_studio_mcp`, controller script,
    `scripts/probe_documented_api_live.py`, and
    `scripts/run_live_capability_sweep.py`;
    `scripts/test_effects_pattern_extensions.py`;
    `scripts/test_safety_scopes.py`;
    `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: broad live-sweep failures for officially documented APIs must now
    stay `documented-unconfirmed` until `scripts/probe_documented_api_live.py`
    checks API presence, target selection/focus, indexing, readback timing, and
    rollback. The live capability sweep now includes this probe plus the
    targeted effect-plugin probe before any documented API is demoted.
- 2026-06-01: Piano Roll retargeting infrastructure slice passed offline.
  - Verified path: `compileall` for `src/fl_studio_mcp`, controller script, and focused scripts; `scripts/test_pianoroll.py`; `scripts/test_compose.py`; `scripts/audit_tool_safety.py --fail-on-gaps`.
  - Result: existing undo-backed Piano Roll write tools can optionally pass a channel/pattern target through the bridge to the controller, which uses `ui.openEventEditor` when available and falls back to `ui.showWindow`.
  - Live verification passed on FL Studio Producer Edition v25.2.5 (build 5055), controller build marker `channels-v37`: targeted append write to channel 1 / pattern 4 returned `retargeted=True` via `ui.openEventEditor`, then `fl_rollback_last_change` restored through FL undo.
- 2026-06-01: Live capability sweep rerun on FL Studio Producer Edition v25.2.5 (build 5055), controller build marker `channels-v37`, did not fully pass.
  - Verified path: `scripts/run_live_capability_sweep.py` over TCP after FL MIDI script reload and ping confirmation.
  - Result: patterns/playlist, mixer, step sequencer, Piano Roll duplicate, and Piano Roll velocity ramp paths passed with rollback checks; `pattern_set_length` skipped because this FL build does not expose a working length write API; plugin-parameter probe skipped because no plugin was loaded on the probe tracks.
  - Live API limits observed: effect slot mix and native EQ band writes did not stick on the auto-selected mixer target (track 1, slot 0), so readback verification failed while rollback/restore checks remained safe. Because these APIs are officially documented, treat them as `documented-unconfirmed` until a narrower false-positive probe proves whether the issue is target selection, indexing, readback timing, stale state, or a real build limit.
- 2026-06-01: Targeted effect-plugin live probe against track 49/50 did not fully pass.
  - Verified path: `scripts/test_effect_targets_live.py` over TCP against track 49 slot 0 `Fruity Limiter` with route 1->49 active, and track 50 slot 0 `Fruity parametric EQ 2`.
  - Result: Fruity Parametric EQ 2 plugin parameter write/readback/rollback passed on Band 4 level; Fruity Limiter generic plugin parameters did not stick across all 18 exposed parameters; per-slot mix did not stick for either plugin; per-slot enabled write is unavailable on this FL build. All attempted writes used immediate rollback/restore checks.
  - Next action: treat effect slot mix and Fruity Limiter parameter writes as `documented-unconfirmed`/probe-gated for this build/state; prefer plugin-specific EQ2 parameter writes where readback is proven, and keep Limiter sidechain configuration manual until a stable parameter path is proven.
- 2026-06-01: Priority 1/2 live smoke suite attempted, blocked by stale FL controller build.
  - Verified path: daemon up, bridge ping ok (`build=channels-v35`), then
    `scripts/test_priority12_live.py`.
  - Result: blocked at command preflight (`Unknown command: pattern_find_empty`)
    because FL still runs an older script build that does not include the new
    controller handlers. Required next step: reload FL MIDI scripts and rerun
    the live smoke suite.
- 2026-06-01: Fixture hard-standardize + live capability sweep passed on FL Studio Producer Edition v25.2.5 (build 5055), controller build marker `channels-v36`.
  - Verified path: `scripts/fixture_hard_standardize_live.py` (names/colors/markers) then `scripts/run_live_capability_sweep.py`.
  - Result: core rollback-safe writes verified (patterns color, playlist track props, mixer routing/selection, effects slot mix + enabled, native EQ band edit, step sequencer grid bit, plugin param write) with immediate rollback confirmation.
  - Known limits on this build: `pattern_set_length` is API-unavailable (skipped); `mixer_set_stereo_sep` call executes but does not stick (treated as API-limited in live sweep).
- 2026-06-01: Priority 1 + Priority 2 implementation slice (offline) passed.
  - Verified path: `compileall` for `src/` + controller script, safety audit
    gate (`scripts/audit_tool_safety.py --fail-on-gaps`), focused offline tests:
    `scripts/test_effects_pattern_extensions.py`,
    `scripts/test_step_sequencer.py`, `scripts/test_pattern_playlist.py`,
    `scripts/test_pianoroll.py`.
  - Result: new rollback-safe Pattern Completion, Effect Slot + Native EQ
    tools, Project Doctor/Export Readiness reports, and initial Piano Roll
    comfort transforms (`duplicate`, `velocity_ramp`) are integrated and
    passing offline checks.
- 2026-05-31: Scale & Mode Composition Pack Phase 6 live smoke passed on FL Studio
  Producer Edition v25.2.5 (build 5055), controller build marker
  `channels-v35`.
  - Verified path: heartbeat -> ping -> scale catalog read -> scale notes query -> melody creation -> channel focus -> note writing & hotkey triggering via piano-roll bridge.
  - Result: all checks passed, scale listing and mapping works, notes correctly generated and written to FL Studio.
- 2026-05-31: Plugin Params Pack Phase 5 live smoke passed on FL Studio
  Producer Edition v25.2.5 (build 5055), controller build marker
  `channels-v35`.
  - Verified path: heartbeat -> ping -> plugin list -> param list & single param read -> preset name read -> rollback-safe plugin param edit write/readback/rollback.
  - Result: parameter read/write rollback passed. Preset next/prev remains read-only/manual because FL exposes navigation but no verified MCP restore primitive.
- 2026-05-31: Piano Roll Pack Phase 4 offline tests passed.
  - Verified path: note name parsing -> chord interval generation -> Pyscript rendering -> rollback undo action generation.
  - Result: 31 tests passed.
- 2026-05-31: Patterns & Playlist Pack Phase 3 live smoke passed on FL Studio
  Producer Edition v25.2.5 (build 5055), controller build marker
  `channels-v34`.
  - Verified path: heartbeat -> ping -> pattern list & length read -> playlist tracks read ->
    rollback-safe pattern rename write/readback/rollback ->
    rollback-safe playlist track mute/rename/color/selection write/readback/rollback.
  - Result: all checks passed, rollback restoration confirmed for patterns and playlist tracks.
- 2026-05-31: Mixer Pack Phase 2 live smoke passed on FL Studio
  Producer Edition v25.2.5 (build 5055), controller build marker
  `channels-v28`.
  - Verified path: heartbeat -> ping -> mixer track details read (with `dock_side` and `stereo_sep`) ->
    rollback-safe select track write/readback/rollback -> rollback-safe send route
    write/readback/rollback -> rollback-safe stereo separation write/readback/rollback ->
    peak level measurement verification.
  - Result: all checks passed, rollback restoration confirmed for selection, routing, and stereo separation.
- 2026-05-31: Step Sequencer Pack Phase 1 live smoke passed on FL Studio
  Producer Edition v25.2.5 (build 5055), controller build marker
  `channels-v26`.
  - Verified path: heartbeat -> ping -> grid read -> write-safe step grid bit
    write/readback/rollback -> rollback verification.
  - Result: grid bit mutation and rollback restoration successfully verified.
- 2026-05-31: Channel Organizer Pack v1 live smoke passed on FL Studio
  Producer Edition v25.2.5 (build 5055), controller build marker
  `channels-v16`.
  - Verified path: heartbeat -> ping -> channel detail read (`type`, `pitch`) ->
    rollback-safe rename write/readback/rollback -> rollback-safe mixer-target
    write/readback/rollback.
  - Result: all checks passed, rollback restoration confirmed for both write
    operations.

For every write-capable tool, the required shape is:

1. Take a scoped snapshot before the write.
2. Execute the smallest practical change.
3. Read back the affected state.
4. Persist a change-log entry with enough restore data to undo it.
5. Return a human-readable before/after result.
6. Support rollback through the MCP rollback path.

This applies to mixer, channel, pattern, playlist, piano-roll, routing, plugin,
effect-slot, project-tempo, time-signature, UI-assisted, and bulk operations.
Multi-step tools must apply as one named rollback unit unless explicitly split
into smaller user-approved changes.

Tools that cannot provide rollback are limited to read-only diagnosis, dry-run
planning, or clearly labelled manual instructions. They must not silently make
irreversible changes in FL Studio.

Transport-only runtime controls such as play, stop, and preview note triggering
do not change the saved project structure, but any persisted project mutation
such as tempo, pattern edits, channel routing, note writes, or mixer/plugin
changes must follow this contract.
