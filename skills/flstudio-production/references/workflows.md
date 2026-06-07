# FLStudioMCP Workflows

## Live Write Smoke

1. `fl_transport(action="ping")`.
2. Read the target state.
3. Apply one temporary, low-risk change.
4. Verify readback.
5. Roll back immediately.
6. Verify restoration.

Use this for live verification, not for normal creative edits unless the user
asked for a test.

## Project Cleanup

1. Run `fl_project_health_report`.
2. Run `fl_project_dry_run_fix_plan`.
3. Execute one proposed action at a time.
4. Verify readback after every action.
5. Roll back immediately if the result differs from the plan.

## Mixer Organization

1. Inspect tracks with `fl_mixer(action="list")` or `fl_get_routing_all`.
2. Use `fl_set_track_color`, `fl_set_channel_color`, `fl_group_tracks`, or
   channel assignment tools as grouped rollback-safe changes.
3. For bulk solo/mute, prefer `fl_solo_tracks` and `fl_mute_tracks`; restore
   with `fl_clear_mute_solo` or the latest rollback entry.

## Plugin And Chain Configuration

1. Use `fl_plugin(action="list")` to inspect already-loaded plugins.
2. Use `fl_setup_chain` to plan genre-style chains against loaded plugins.
3. Use intent tools only on matching loaded plugins.
4. Never load missing plugins through the API; suggest manual loading and
   re-run the plan after the user confirms.

## Piano Roll Composition

1. Confirm the bridge is alive with `fl_transport(action="ping")`.
2. If needed, tell the user to run `MCP Apply` once from the Piano Roll
   Scripting menu.
3. Use `fl_scale_list` or `fl_scale_get` for pitch material.
4. Use `fl_piano_roll(action="write_notes")`,
   `fl_piano_roll(action="write_chord")`, `fl_write_raga_melody`, or
   `fl_write_raga_chords`.
5. If targeting a specific instrument, pass or select the channel explicitly.

## Audio-To-MIDI And MIDI Export

- Use `fl_analyze_audio` for tempo/key estimates and label key detection as
  estimated.
- Use `fl_extract_melody` only for monophonic sources and review confidence
  before writing notes.
- Use `fl_export_midi` for full arrangement files. This writes a `.mid` outside
  FL; the user imports it manually and assigns instruments.
