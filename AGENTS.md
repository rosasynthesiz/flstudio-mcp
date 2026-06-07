# AGENTS.md

This file is the repository guide for AI-assisted coding in this workspace.
Follow it together with the higher-priority system/developer instructions.

## START HERE FOR FL AGENTS

- Read `fl://agent-briefing`, then `fl://status`, before selecting tools.
- Prefer current domain/workflow tools: `fl_transport`, `fl_mixer`,
  `fl_channel`, `fl_pattern`, `fl_playlist`, `fl_effect`, `fl_plugin`,
  `fl_piano_roll`, `fl_batch`, Project Health/Preflight, Mix Review, Routing
  Review, Project Organizer, audio analysis, MIDI export, and Knowledgebase
  tools.
- Check the Knowledgebase before FL state, mixer/plugin parameters, automation,
  REC events, or MIDI work. Do not guess ranges, mappings, indices, or IDs.
- No persistent FL write without rollback and readback:
  snapshot -> smallest write -> readback -> changelog -> rollback path.
- Stop when API support, readback, rollback, target selection, bridge status, or
  value evidence is unclear. Use read-only, dry-run, probe-only, or manual
  guidance instead.

## Mandatory First Reads

Before changing code, tests, docs, scripts, controller files, skill files, evals,
or roadmap state, read these files and follow them as binding project
instructions:

- `docs/ENGINEERING_STANDARDS.md`
- `ROADMAP.md`

If either file conflicts with an ad-hoc prompt, stop and surface the conflict
before implementing. The safety contract and roadmap scope are not optional.

## Working Mode

- Act as a senior, pragmatic software engineer.
- Inspect the repo before changing it. Read surrounding code, existing tool
  patterns, tests, safety layer, protocol constants, controller handlers, and
  registration style.
- For implementation work, explicitly inspect the relevant parts of
  `ROADMAP.md`, `docs/API_CAPABILITY_AUDIT.md`,
  `src/fl_studio_mcp/safety.py`, `src/fl_studio_mcp/protocol.py`, the FL
  controller script, existing tool modules, and focused tests/scripts before
  editing.
- For non-trivial implementation slices, produce a short implementation plan
  before editing and confirm the slice is dependency-correct and rollback-safe.
- Before building anything new, check whether the functionality already exists
  under a different name or can be composed from existing safe primitives.
- Prefer existing project patterns over new abstractions.
- Use established patterns: protocol constants, controller handlers,
  `safety.safe_write`, `safety.safe_write_group`, Piano Roll safety helpers,
  focused tests/scripts, and FastMCP registration style.
- Keep edits small, coherent, and backport-friendly.
- Preserve all user and uncommitted changes. Never revert unrelated work.
- Use English for commits, code comments, docstrings, and repo documentation.

## Required Safety Posture

- No FL Studio project-state mutation may ship without rollback.
- Read-only actions are the only exception.
- Every persistent write must follow:
  scoped snapshot -> smallest practical write -> readback -> changelog entry ->
  rollback path.
- Multi-step changes must be one named rollback unit unless there is a clear,
  documented reason to split them.
- If API support, readback, or rollback is unclear, implement read-only,
  dry-run, manual-guidance, or probe-only behavior.
- Keep Piano Roll transforms undo-backed and explicit about readback limits.
- Normalize and Stretch Pro behavior remains probe-dependent; do not promise it.

## FL Studio Knowledgebase Protocol

- Agents MUST check the Knowledgebase (`knowledgebase/`) before making changes to FL Studio state, mixer parameters, plugin parameters, automation, REC events, or MIDI data.
- Agents MUST NOT guess valid value ranges, normalized values, dB/Hz mappings, REC event IDs, track indexing, or plugin parameter indices.
- Agents MUST prefer high-level MCP tools over raw FL API calls. Raw calls are only permitted if no safe wrapper exists.
- When new verified knowledge is acquired, it MUST be documented in a Markdown file. If machine-relevant, it MUST additionally be documented in JSON/YAML.
- Every Knowledgebase entry needs at least: Topic, Source/Verification Method, Date, Confidence Level, Affected API/Function/Tool, Valid Ranges, Example, and Known Pitfalls.
- Hard Rule: Agents MUST NOT leave reusable findings only in chat, commit messages, or temporary scratch notes.

## Knowledge Capture Protocol

An Agent MUST update the Knowledgebase if any of the following occur:
- An FL Studio API behavior is practically tested.
- A parameter range is confirmed (via trial, readback, docs, or error messages).
- A mapping between a UI value and an API value is discovered.
- A recurring error or pitfall is detected.
- A workaround is successfully applied.
- An MCP wrapper is added, modified, or identified as necessary.
- An assumption is proven wrong.
- A tool call or server error shows that existing KB knowledge is missing or unclear.
- A musical recipe rule is reusable.
- A behavior depends on the FL Studio version, platform, plugin version, or API version.

Every new entry MUST contain: Date, Agent/Author, Topic, Affected File/API, Context, Observation, Tested Values, Result, Confidence Level, Source/Method, Reproduction Steps (if relevant), Open Questions, and Next Recommended Action.

Allowed Confidence Levels: `hypothesis`, `user_reported`, `docs_confirmed`, `measured_once`, `measured_repeated`, `implementation_verified`, `cross_platform_verified`, `deprecated_or_rejected`.

Rules:
- If a finding affects tool behavior, Markdown is not enough. JSON/YAML MUST be updated.
- If uncertain, agents MUST NOT document false certainty. Use a low confidence level and add an open question.
- Every new or modified MCP function must check for a KB entry. If none exists, create a brief entry.
- Every resolved false assumption MUST also be documented in `knowledgebase/known_pitfalls/`.

## Do Not Ship As User-Facing Tools

- Plugin loading or insertion.
- Playlist clip editing, placement, movement, or deletion.
- Pattern or clip deletion.
- Project open, new, save-as, or render automation.
- Raw controller/API escape hatches.
- Full FLP snapshot or full-project restore claims.
- Broad UI automation tools.
- Unsafe automation recording tools.

Plugin work should configure already-loaded plugins only. Loading stays manual.

## Documented API Failures

If an officially documented API fails or behaves differently in a live test, do
not immediately discard the capability. Classify it as
`documented-unconfirmed` and run a targeted false-positive probe before
demoting it. The probe must check API presence, target selection/focus,
indexing, readback timing, target/plugin state, and rollback on the current FL
build.

## Implementation Checklist

For every new FL-mutating tool, add or update:

- Protocol command constants, if needed.
- FL controller handler.
- Snapshot scope.
- Restore operation.
- Readback verification.
- Safety-layer integration via the established safety helpers.
- Tool annotations and docstring explaining safety behavior.
- Static audit compatibility.
- Focused script/unit test or rollback-safe live smoke script.
- Roadmap/API audit/docs note when behavior or scope changes.

## Roadmap Discipline

- Treat `ROADMAP.md` as the active execution tracker.
- Keep it current in the same PR or commit series whenever a slice is
  completed, re-scoped, verified, blocked, or reprioritized.
- Record live FL verification checkpoints with date, FL build, controller build
  marker, tested path, and rollback result.

## Commit Discipline

- Use sensible staged commits while working.
- Each commit should be a coherent feature slice or tightly scoped fix.
- Keep commits useful for cherry-picking by sister projects.
- Do not mix unrelated cleanup, formatting, and feature work.
- Commit messages must be English and explain the change clearly.

## Verification Expectations

Run the smallest meaningful checks for the changed area, then broaden when the
blast radius justifies it:

- Compile checks for touched Python code.
- `scripts/audit_tool_safety.py --fail-on-gaps`.
- `scripts/audit_tool_safety.py --fail-on-missing-safety-docs --format json`
  when tool annotations or docstrings change.
- Focused script tests for changed areas.
- FastMCP registration/tool-count checks when tool registration changes.
- Rollback-safe live smoke tests when FL Studio is available and the change
  touches live behavior.

If repo-wide `pytest` or `ruff` failures are pre-existing, report them
separately and do not churn unrelated code.

At handoff, summarize changed files, verification run, remaining risks or API
limits, and the next recommended roadmap slice.

## Local Environment

- Python target: 3.12 for current development on this machine. Package metadata
  still supports Python 3.10+ unless changed deliberately.
- On macOS, commands importing pip, XML, or audio dependencies may need:

```bash
export DYLD_LIBRARY_PATH="/usr/local/opt/expat/lib:${DYLD_LIBRARY_PATH:-}"
```

- Prefer `rg` and `rg --files` for search.
- Use `apply_patch` for manual file edits.
- Do not use destructive Git commands unless explicitly requested.

## Live FL Studio Procedure

- Start the TCP daemon yourself when live tests require it.
- Confirm heartbeat and `fl_transport(action="ping")` before live work.
- Confirm the controller build marker expected by the current code.
- Read current state before writing.
- For live write tests, write a temporary value, verify readback, rollback
  immediately, and verify restoration.
- If MIDI routing, script reload, or restart state is uncertain, diagnose the
  connection before changing code.
- Stop daemons you started and leave playback stopped/recording disarmed after
  tests.

## Workspace & File Artifact Protocol

To keep the workspace clean and maintain context for generated artifacts, agents MUST strictly adhere to the following output directory structures. NEVER write files directly to the root of `scratch/` or the project root.

- **Temporary Scripts (`scratch/scripts/`)**: All ad-hoc, probing, or testing Python scripts generated by agents (e.g., `live_test.py`, `fix_routing.py`) MUST be saved here.
- **Generated MIDI (`scratch/midi/`)**: All exported or generated MIDI files MUST be placed in session- or task-specific subdirectories (e.g., `scratch/midi/YYYY-MM-DD_task_name/`).
- **Analysis Data & State Dumps (`scratch/analysis/`)**: JSON dumps of FL Studio state, diagnostic metrics, and snapshots MUST be saved in session-based subdirectories (e.g., `scratch/analysis/YYYY-MM-DD_session_name/`).
- **Audio Files (`scratch/audio/`)**: Rendered bounces and reference audio tracks (WAV, MP3) MUST be saved here.
- **Logs (`scratch/logs/`)**: Text-based logs (e.g., `daemon.log`, `mix_review.log`) MUST be collected here.

When writing files, agents MUST ensure the target subdirectory exists, creating it if necessary (e.g., using `os.makedirs(..., exist_ok=True)` in Python).
