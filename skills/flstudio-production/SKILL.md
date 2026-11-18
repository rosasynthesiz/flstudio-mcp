---
name: flstudio-production
description: Use this skill whenever the user wants to control FL Studio from Claude — write or trigger drum patterns, set tempo, change mixer levels, write notes to the Piano Roll, work with Carnatic ragas or kuthu rhythms in FL Studio, or troubleshoot the FLStudioMCP bridge. Trigger on FL Studio, FL, Fruity Loops, FLStudioMCP, "FL-il pannu", music production via Claude. ALWAYS use the fl-studio MCP server tools — never instruct the user to perform the change manually if a tool exists.
---

# FL Studio production skill

This is the orchestration layer for the fl-studio MCP server.

## Before you act

1. Call `fl_ping` once at the start of every session. If `status` is not
   `READY`, stop and tell the user the `next` step it returns (for example:
   open FL Studio and load a project, or run `fl-studio-mcp setup`). Do not
   retry blindly.
2. Read the README's Limitations section so you don't promise things the FL
   API can't deliver (no plugin loading, no audio loading, no rendering).
3. If the user is going to write Piano Roll notes, FL Studio must be the
   focused window. Warn them once at the start.

## Tool selection

| User intent | Tools |
|---|---|
| Tempo, play, stop | `fl_set_tempo`, `fl_play`, `fl_stop`, `fl_toggle_play` |
| Where are we in the song | `fl_get_song_position` |
| Drum patterns | `fl_set_step_grid`, `fl_get_step_grid` — NOT the Piano Roll |
| Mixer levels | `fl_set_mixer_volume`, `fl_set_mixer_pan` |
| Melody in a raga | `fl_write_raga_melody`, which writes through the Piano Roll bridge |
| Read a plugin's knobs | `fl_plugin_list`, `fl_plugin_get_params` (names + normalised 0..1 values) |
| Change one knob | `fl_plugin_set_param` — answers `verified` / `attempts`; a `hint` means FL refused the value |
| Change several knobs of one plugin | `fl_plugin_set_params` — one paced burst, ONE undo step; prefer it over repeating the single tool |
| List / pick / rename patterns | `fl_pattern_list` (paginated), `fl_pattern_select`, `fl_pattern_rename` — select/rename are one rollback step each |
| How long is a pattern | `fl_pattern_get_length` — beats (FL's native unit) + derived bars/ticks via the project PPQ |

Pattern writes return `verified` from an independent readback. If `ok` is false,
inspect the error and state before continuing. Failed undo returns
`recovery_retained: true`; the original recovery record stays available for a
retry. Full pattern names that exceed the MIDI budget are rejected rather than
truncated, so a list entry with `trunc: true` may not support a full-name read or
write. Undo never restores a shortened name.

### Plugin parameter recipe

Trust `verified`, not the request. Measured on FL 26 with Fruity Parametric
EQ 2: levels and gains take an arbitrary 0..1 value; stepped parameters
(filter types, orders, selectors) snap to their own grid, so an off-grid
request comes back `verified: false` with the snapped value in `after`; some
parameters (band widths) ignore writes entirely. An open plugin window
(pickup mode) did not block script writes in our test. Values are the
normalised 0..1 domain shown by `fl_plugin_get_params` — read the display
string (`3.6dB`, `500Hz`) to know what a value means, and prefer
`fl_plugin_set_params` for 2+ knobs (one undo step).

## When something fails

- `FLNotRunning` → bridge is healthy, FL is not. Ask user to open FL.
- `FLTimeout` → controller is loaded but stalled. Ask user to re-select
  FLStudioMCP in MIDI Settings.
- `FLCommandFailed` with `code=client` → bad input. Show the user what was
  wrong and ask for a correction.
