# Engineering Standards

This document consolidates the working rules for this fork. It is intended to
guide implementation, review, and backport-friendly commits while the API-backed
production suite is expanded.

## Core Engineering Bar

- Act as a senior, pragmatic software engineer: inspect the existing system
  first, make conservative design choices, and prefer small, coherent changes.
- Do not code blindly. Confirm the dependency order and safety story before
  implementing a new feature slice.
- Keep work reviewable: clear names, narrow diffs, focused tests, and no broad
  speculative wrappers.
- Preserve existing user or uncommitted changes. Never revert unrelated work.
- Use the repository's existing patterns before introducing new abstractions.
- Add a new abstraction only when it removes real complexity, reduces meaningful
  duplication, or matches an established local pattern.
- Keep the FL controller thin. It should return cheap raw data and perform the
  minimal requested action; product judgement belongs server-side.

## Language Rules

- Commit messages must be in English.
- Code comments must be in English.
- Docstrings and user-facing repository documentation must be in English.
- Comments should be sparse and useful. Avoid comments that restate obvious
  code.

## FL Studio Safety Contract

No FL Studio project-state mutation may ship unless it has rollback. Read-only
actions are the only exception.

Every persistent write must follow this sequence:

1. Take a scoped snapshot before the write.
2. Execute the smallest practical FL command or generated-script operation.
3. Read back the affected state.
4. Persist a changelog entry with enough restore data to undo the change.
5. Return a human-readable before/after result.
6. Support rollback through the MCP rollback path.

Multi-step changes must be one named rollback unit unless there is a clear,
documented reason to split them. If API support, readback, or rollback is
unclear, implement read-only reporting, dry-run planning, or a probe instead of
a user-facing write tool.

Transient runtime controls such as play, stop, and preview note triggering do
not require project rollback, but they still need safe failure behavior and must
not leave stuck state behind.

## Write Tool Requirements

For every new FL-mutating tool, add or update all relevant pieces:

- Protocol command constants, if a new controller command is needed.
- FL controller handler.
- Snapshot scope.
- Restore operation.
- Readback verification.
- Safety-layer integration via `safety.safe_write`,
  `safety.safe_write_group`, or the established Piano Roll safety path.
- Tool annotations and docstring explaining the safety class.
- Static audit compatibility.
- Focused unit/script test or rollback-safe live smoke script.
- Documentation note when behavior is limited by API support.

Piano Roll transforms must remain undo-backed and explicit about readback
limitations. Generated-script writes should use FL undo sections where
available and route rollback through the established undo path.

## Prohibited User-Facing Tools For This Branch

Do not ship these as user-facing tools unless the project safety architecture is
explicitly changed and reviewed:

- Plugin loading or insertion.
- Playlist clip editing, placement, movement, or deletion.
- Pattern or clip deletion.
- Project open, new, save-as, or render automation.
- Raw API escape hatches such as arbitrary controller calls.
- Full FLP snapshot or full-project restore claims.
- Broad UI automation tools.
- Unsafe automation recording tools.

Plugin-related work should configure already-loaded plugins only. Loading stays
manual.

## API Evidence Rules

Before implementing a capability, classify the evidence level:

- `documented`: official Image-Line documentation exposes the API.
- `documented-unconfirmed`: official documentation exposes the API, but a live
  smoke failed or behaved differently from the documentation.
- `live-probed`: the current FL build exposes and executes the API.
- `existing`: the current MCP already exposes it safely.
- `probe-needed`: documentation or names imply a path, but behavior is not
  verified.
- `api-limited`: no stable API path is known.

Only `documented`, `live-probed`, or `existing` capabilities should become
write tools, and only after the rollback contract is satisfied. `probe-needed`
capabilities should become probes first. If a documented API fails a broad live
test, classify it as `documented-unconfirmed` and run a targeted false-positive
probe before demoting it. The probe must check API presence, target
selection/focus, indexing, readback timing, and rollback on the current FL
build. `api-limited` capabilities should stay read-only, dry-run, or
manual-instruction-only.

Normalize and Stretch Pro defaults for audio channels remain probe-dependent.
Do not promise them until a stable API path is proven.

## Roadmap Scope


Current priority order:

1. Safety primitives and change history.
2. API-backed quick wins:
   - Step Sequencer Pack.
   - Channel Organizer Pack.
   - Pattern Management Pack.
   - Playlist Track Organizer.
   - Effect Slot and Native EQ Pack.
3. Product-level workflows:
   - Project Organizer MVP.
   - Routing Review 2.0.
   - Project Health / Preflight Report.
   - Export readiness report.
4. Creative intelligence and experimental infrastructure.

## Commit And PR Discipline

- Use sensible, staged commits throughout implementation.
- Each commit should represent a backportable feature slice or a tightly scoped
  fix.
- Prefer small PR slices that downstream or sister projects can cherry-pick.
- Commit messages must describe what changed and why, in English.
- Avoid mixing unrelated formatting, cleanup, and feature work.
- Update README, roadmap, API audit, or docs when tool behavior or safety
  guarantees change.
- Keep `ROADMAP.md` current as an operational source of truth:
  every completed slice, live verification checkpoint, and priority/order change
  must be reflected in the same PR or commit series.

## Testing And Verification

Run the smallest meaningful verification set for the changed area, then broaden
when shared behavior or safety-critical paths changed.

Expected checks for production-suite work:

- Compile checks for touched Python code.
- `scripts/audit_tool_safety.py --fail-on-gaps`.
- Focused script tests for changed areas.
- Rollback-safe live smoke tests when FL Studio is available.
- Tool registration checks when the FastMCP surface changes.

If repo-wide `pytest` or `ruff` failures are pre-existing, report them
separately. Do not churn the whole repository unless that cleanup is the agreed
task.

## Local Environment Notes

- Python target for this machine is 3.12.
- On macOS, commands that import pip, XML, or audio dependencies may require:

```bash
export DYLD_LIBRARY_PATH="/usr/local/opt/expat/lib:${DYLD_LIBRARY_PATH:-}"
```

- Prefer `rg` or `rg --files` for repository search.
- Use `apply_patch` for manual file edits.
- Do not use destructive Git commands such as `git reset --hard` or
  `git checkout --` unless the user explicitly requested that exact operation.

## Live FL Studio Work

- Confirm the bridge and controller build before live write tests.
- Live tests must be rollback-safe and scoped to the smallest practical state.
- Prefer read-only checks first: heartbeat, ping, controller build, and current
  state reads.
- For write smoke tests, use a temporary value, verify readback, then rollback
  immediately and verify restoration.
- If MIDI routing, controller reload, or FL restart is unclear, diagnose the
  connection before changing code.

## Product Quality Expectations

- Build tools around user workflows, not just one-to-one API wrappers.
- Prefer high-signal reports and guided fixes over large, flat tool surfaces.
- Project Health, Routing Review, and organizer workflows must orchestrate safe
  primitives instead of creating a second write layer.
- Bulk cleanup should be previewable and grouped into named rollback units.
- User-facing results should be explicit about what changed, what was skipped,
  and what is limited by FL API support.

### Tool Surface And MCP Efficiency

Reducing LLM token cost, tool-selection noise, and avoidable MCP round trips is
a product quality requirement. It is subordinate to safety: do not consolidate
or batch behavior if rollback, readback, validation, or API evidence becomes
weaker.

- Prefer high-signal domain tools and workflow tools over many one-property
  getter/setter tools.
- Avoid new MCP round trips when a safe grouped read/write or server-side
  orchestration can return the same user value.
- For new MCP tools or expanded tool surfaces, include token/tool-surface impact
  in the implementation plan, review summary, or roadmap update.
- Add or update registration and tool-count checks when FastMCP registration
  changes.
- Keep product workflows when they reduce unsafe manual orchestration; reduce
  redundant low-level wrappers first.
