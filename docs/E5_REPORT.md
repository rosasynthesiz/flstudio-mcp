# E-5 Report — Wrapper holes: presets, color reads, undo, api_probe

**Scope:** close the last capabilities that had controller/protocol support but
no MCP wrapper, on top of the v2 bridge (project-bound undo, one-command
setup). Issue #55.

**Live FL:** Producer Edition **26.1.7 [build 5419]**, v2 zero-click MIDI
pairing, controller `2.0.0.dev0` (re-deployed from this branch; FL restarted so
the new handler table loaded).

## Live facts (measured this run)

- **`plugins` module is reachable:** `fl_api_probe("plugins")` -> 13 public
  names, including `getPresetCount`, `nextPreset`, `prevPreset`. There is
  still **no `setPreset` and no preset index** — a restore by name is
  impossible.
- **`name_f6` now reads the CURRENT preset** (`midi.GPN_GetCurrentPreset`
  instead of `paramIndex=0`). Live on FLEX (channel 4, 30 presets):
  `808 Astronomic` -> `prev` -> `808 Volcanic` -> `808 Vast Wave`, then back
  with `next`. Before the fix every read returned preset #0's name.
- **Preset navigation is best-effort and lags:** the immediate `current`
  re-read can trail the actual preset by one step (same-RPC name readback
  lags, the E-1 fader pattern). The tool therefore states `rollback: "none"`
  and tells the agent to re-read; a second read settles it.
- **`fl_undo` restores a fader exactly:** mixer track 15 `0.8 -> 0.7` ->
  `fl_undo` -> `0.8`. A readback taken in the same instant can be one script
  tick stale — re-read (already in the warning text).
- **Color reads work and FL quantizes:** set `#00FF00` on channel 0 ->
  reads back `#14FF14`; `fl_rollback_last_change` restored `#5C656A`
  exactly. Track read (track 15) returned `#636C71`.
- **Preset-less plugins stay honest:** Emphasizer reports
  `preset_count: 1`, `name_f6: ""` — no fake navigation.

## Decisions

### Preset navigation sits OUTSIDE the safety layer

FL 26 cannot set a preset (no `setPreset`, no index), and live testing shows
`nextPreset`/`prevPreset` are best-effort (steps and name readbacks can lag).
A mirrored "rollback" would silently claim something it cannot do. So
`op=info` is a plain read, and `op=next/prev` return `rollback: "none"`, a
`warning`, and a fresh-tick `info` re-read (`current`). No changelog entry,
matching the `fl_undo` precedent.

### `fl_undo` is a direct command, not a safe write

Nothing readable describes what an undo jump will undo, so a snapshot is
impossible; a changelog entry without a restore would either lie or block
rolling back the previous REAL write. Undo joins `fl_play`/`fl_stop` with an
explicit warning and `last_rollback` (newest changelog entry, which the undo
may have just cancelled). Coverage still varies by action type (volume /
parameters undo; pattern rename is not in FL's undo stack).

### `fl_api_probe` filter budgets the full envelope

With `pattern`, all pages are walked (`_MAX_PAGES = 50`), matches filtered, and
the reply is trimmed against the **complete** envelope
`{module, pattern, total, start, match_count, names, truncated}`. A 600-byte
names array still shipped 675 B in the first E-5 review, so the budget is
measured on the serialized wrapper, not the list.

## What changed

- New tools: `fl_plugin_preset`, `fl_get_channel_color`,
  `fl_get_track_color`, `fl_undo`, `fl_api_probe` (91 -> **96 tools**).
- Controller: `GPN_GetCurrentPreset` for `name_f6`; `plugins` added to the
  `api_probe` module map; honest `undo` handler (`general.undoUp`) registered
  as `CMD_UNDO`.
- Docs: README tool list + counts, SKILL routing rows, this report.
- Tests: `tests/test_e5_wrappers.py` (wrapper contracts, probe paging/budget)
  and `tests/test_controller_e5.py` (GPN fix, undo handler, plugins module).

## Live scenario

| Step | Result |
|---|---|
| `fl_api_probe("plugins")` | 13 names; `getPresetCount/nextPreset/prevPreset` present |
| `fl_plugin_preset(4, -1)` (FLEX) | `preset_count: 30`, `name_f6: "808 Astronomic"` |
| `op=prev` then re-read | `808 Volcanic` / `808 Vast Wave` (name lags one step) |
| `op=next` x2 | back to `808 Astronomic` |
| `fl_set_mixer_volume(15, 0.7)` then `fl_undo` | `0.8 -> 0.7 -> 0.8`; `last_rollback.tool = mixer_set_volume` |
| `fl_set_channel_color([0], "#00FF00")` then read | `#14FF14` (FL quantization) |
| `fl_rollback_last_change` then read | `#5C656A` (exact restore) |
| `fl_get_track_color(15)` | `#636C71` |

## Note for reviewers

The controller file changed, so an existing install must re-run
`fl-studio-mcp setup` (hash-compared, with a timestamped backup) and restart
FL Studio to load the new handler table. `CONTROLLER_VERSION` was left at
`2.0.0.dev0` on purpose: `tests/test_setup_v2.py` pins it to the package
version, so a version bump would imply a release.
