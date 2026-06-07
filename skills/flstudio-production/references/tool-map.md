# FLStudioMCP Tool Map

## Orientation Resources

- Start with `fl://agent-briefing`, then `fl://status`.
- Use capped resources such as `fl://mixer`, `fl://channels`, and
  `fl://patterns` before broad state reads.

## Domain Tools

- Transport: `fl_transport`.
  Actions: `ping`, `get_tempo`, `set_tempo`, `get_play_state`, `play`,
  `stop`, `toggle_play`, `record`, `get_song_position`, `set_song_position`,
  `get_time_signature`, `set_time_signature`.
- Mixer: `fl_mixer`.
  Actions: `list`, `get`, `select`, `get_route`, `set_route`, `set_volume`,
  `set_pan`, `set_mute`, `set_solo`, `set_stereo_separation`.
- Channel: `fl_channel`.
  Actions: `list`, `get`, `get_selected`, `get_steps`, `classify`, `select`,
  `set_color`, `set_mute`, `set_mixer_target`, `set_name`, `set_pan`,
  `set_solo`, `set_steps`, `set_volume`.
- Pattern: `fl_pattern`.
  Actions: `list`, `get`, `get_length`, `get_selected`, `find_empty`,
  `select`, `rename`, `set_color`, `set_length`.
- Playlist track metadata/control: `fl_playlist`.
  Actions: `list`, `get`, `select`, `set_color`, `set_mute`, `set_name`,
  `set_solo`. Playlist clip placement, movement, editing, and deletion are not
  exposed.
- Effect slots and native mixer EQ: `fl_effect`.
  Actions: `get_slot`, `list_slots`, `get_track_slots_enabled`,
  `set_slot_enabled`, `set_slot_mix`, `set_track_slots_enabled`, `get_eq`,
  `set_eq_band`.
- Already-loaded plugin parameters: `fl_plugin`.
  Actions: `list`, `list_params`, `get_param`, `set_param`. Plugin loading,
  insertion, removal, and preset writes stay manual.
- Piano Roll: `fl_piano_roll`.
  Actions include `write_notes`, `write_chord`, `clear`, `quantize`,
  `transpose`, `duplicate`, `velocity_ramp`, marker helpers, return-channel
  probes, and readback-limit reports. Piano Roll writes are FL undo-backed and
  are not eligible for generic persistent `fl_batch` writes.
- Batch: `fl_batch`.
  Use only strict operation-registry reads or homogeneous persistent writes.
  Writes become one named rollback unit.

## Project, Safety, And Reports

- Project reads: `fl_get_project_state`.
- Safety state: `fl_get_change_history`, `fl_get_change_log_summary`,
  `fl_take_snapshot`, `fl_rollback_last_change`, `fl_rollback_change`,
  `fl_export_change_log`, `fl_set_dry_run`.
- Reports: `fl_project_health_report`, `fl_project_health_overview`,
  `fl_check_project_preflight`, `fl_export_readiness_report`,
  `fl_project_dry_run_fix_plan`.

## Workflow And Specialist Tools

- Project organization: `fl_analyze_project_organization`,
  `fl_plan_project_cleanup`, `fl_apply_project_cleanup_step`,
  `fl_apply_naming_standard`, `fl_apply_color_standard`,
  `fl_start_guided_cleanup`, `fl_get_guided_cleanup_context`.
- Routing and cleanup: `fl_get_routing_all`, `fl_get_channel_routing`,
  `fl_detect_cleanup_candidates`, `fl_review_routing`,
  `fl_plan_routing_cleanup`, `fl_apply_routing_cleanup`,
  `fl_apply_bus_layout`, `fl_group_tracks`.
- Bulk and color helpers: `fl_solo_tracks`, `fl_mute_tracks`,
  `fl_clear_mute_solo`, `fl_set_track_color`, `fl_set_channel_color`.
- Channel/audio-clip helpers: `fl_detect_unassigned_channels`,
  `fl_assign_channel_to_free_mixer_track`, `fl_inspect_audio_clips`,
  `fl_plan_audio_clip_safe_defaults`,
  `fl_apply_audio_clip_safe_defaults`.
- Arrangement primitives: `fl_arrange_new_pattern`,
  `fl_arrange_select_channel`, `fl_arrange_clone_pattern`,
  `fl_arrange_add_marker`.
- Composition: `fl_scale_list`, `fl_scale_get`, `fl_write_raga_melody`,
  `fl_write_raga_chords`.
- Audio analysis and MIDI export: `fl_analyze_audio`, `fl_extract_melody`,
  `fl_export_midi`.
- Mixing intents and review: `fl_apply_eq_intent`,
  `fl_apply_reverb_intent`, `fl_apply_delay_intent`,
  `fl_apply_compression_intent`, `fl_get_track_level`, `fl_review_mix`,
  `fl_review_low_end_stereo`, `fl_apply_mix_adjustment`,
  `fl_mix_watch_start`, `fl_mix_watch_status`, `fl_mix_watch_stop`,
  `fl_gain_stage`, `fl_reference_match`.
- Chain and preset planning: `fl_list_chains`, `fl_list_installed_plugins`,
  `fl_setup_chain`, `fl_list_presets`, `fl_suggest_preset`,
  `fl_plugin_get_preset_name`, `fl_plugin_next_preset`,
  `fl_plugin_prev_preset`.
- Knowledgebase: `kb_search`, `kb_get`, `kb_get_parameter_spec`,
  `kb_get_conversion`, `kb_list_open_questions`, `kb_record_finding`,
  `kb_record_verified_finding`.
