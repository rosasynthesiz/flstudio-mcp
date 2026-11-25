---
name: fl-studio-mcp
description: Use when the user wants to control or inspect FL Studio through the flstudio MCP tools - diagnose a mix, change mixer levels or pan, read and set plugin parameters, write drum patterns or piano roll notes, set tempo, or arrange patterns. Trigger on FL Studio, FL, mixing, piano roll, step sequencer, drum pattern.
---

# FL Studio MCP

Use the `flstudio` MCP server's tools to work in the project open in FL Studio. Prefer a tool over telling the user to click through FL Studio themselves.

## Start every session

1. Call `fl_ping`. If `status` is not `READY`, stop and give the user the `next` step it returns (open FL Studio with a project, or finish the one-time setup in the project README). Do not retry in a loop.
2. For piano roll writes, FL Studio must be the focused window. Say so once.

## Pick the right tool

| Goal | Tools |
|---|---|
| Tempo, play, stop | `fl_set_tempo`, `fl_play`, `fl_stop` |
| Mix problems | `fl_get_mixer_state`, `fl_diagnose_mix`, then `fl_apply_mix_fix` |
| Levels, pan, mute, solo | `fl_set_mixer_volume`, `fl_set_mixer_pan`, `fl_set_mixer_mute`, `fl_set_mixer_solo` |
| Plugin knobs | `fl_plugin_list`, `fl_plugin_get_params`, `fl_plugin_set_param`, `fl_plugin_set_params` (use for 2 or more knobs: one undo step) |
| Drum patterns | `fl_set_step_grid`, `fl_get_step_grid` (not the piano roll) |
| Notes and melodies | `fl_write_piano_roll_notes`, `fl_write_raga_melody` |
| Patterns and arrangement | `fl_pattern_list`, `fl_pattern_select`, `fl_arrange_new_pattern`, `fl_arrange_clone_pattern` |

## Work safely

- Read before you write: look at the current state, then change it.
- Write results include `verified`. If it is false, report what FL Studio actually did (see `after` or `hint`) and do not claim success.
- Use `fl_set_dry_run` to preview a change without touching the project when the user is unsure.
- Every change is logged. `fl_rollback_last_change` undoes the last one; offer it if the user is unhappy with a result.
- FL Studio's scripting API cannot load plugins, load audio or render. Say so instead of promising it.

## When something fails

- Not running: ask the user to open FL Studio and load a project.
- Timeout: the controller is loaded but stalled; ask the user to re-select FLStudioMCP in FL Studio's MIDI settings.
- Bad input error: show what was wrong and ask for a correction.
