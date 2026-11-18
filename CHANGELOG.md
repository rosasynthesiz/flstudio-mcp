# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Version 2 (will be released as 2.0.0)
- **One-command setup:** `fl-studio-mcp setup` installs the controller script (now shipped inside the package), waits for FL Studio and reports READY only after a real ping. `fl-studio-mcp doctor` prints one status code and the next step; `fl-studio-mcp connect` prints the client entry.
- **macOS / Linux need no MIDI setup:** the server creates virtual ports with one shared name and FL Studio links, pairs and enables them by itself. On by default; an existing IAC or loopMIDI pair is used first; `FLSTUDIO_MCP_VIRTUAL_PORTS=0` turns it off. Builds on #11 by David Bertram.
- **No daemon to start:** the first server owns the MIDI ports and shares them; later servers join; a joiner takes over if the owner exits. `FLSTUDIO_MCP_TRANSPORT` and the daemon still work.
- **Project-bound undo:** an undo entry from another project or controller session is refused and kept. The log is shared safely between servers. `fl_set_tempo` is undoable.
- **Pattern tools:** `fl_pattern_list`, `fl_pattern_select`, `fl_pattern_rename`, `fl_pattern_get_length` (#37, #38 by Evgeniy Ovchintsev), with verified writes.
- **Playlist and plugin tools** from #12 by David Bertram: playlist tracks (list, mute, solo, rename, colour), arrangement selection and markers, `fl_capabilities`, and deeper plugin control (`fl_plugin_overview`, `fl_plugin_find_params`, `fl_plugin_calibrate_param`, `fl_plugin_set_param_value`, `fl_plugin_intent`), also for channel-rack instruments (`slot=-1`). 90 tools in total.
- **Plugin writes land on the first send.** The controller now passes an explicit pickup mode to FL; without one FL Studio 26.1 often ignored a write however many times it was sent.
- Undo picks the newest change of the open project; entries left by another project or FL session no longer block undo or calibration.
- The first command after connecting waits until FL answers steadily (FL can go silent for about a second while it attaches the device).
- `FLSTUDIO_MCP_LOG=DEBUG` logs every command sent to FL and its answer.
- `fl_ping` returns `status` and `next`. A write FL refuses because a dialog is open reports `FL_BUSY`. The first command after connecting is no longer lost.
- One version for server and controller, checked on connect.
- FastMCP capped below 5; `pyautogui` no longer installed on macOS (the note-bridge key goes through System Events).
- The macOS installer uses a private `.venv` and no longer touches the system Python.
- `mcp.json` no longer forces the daemon transport, and an old `FLSTUDIO_MCP_TRANSPORT=tcp` setting now works without a daemon.

**Upgrading from 1.x:** run `fl-studio-mcp setup` again and restart FL Studio. Existing `FLStudioMCP RX` / `FLStudioMCP TX` ports and MIDI Settings keep working.

### Integrated community work
- Verified plugin writes and batches, dry-run/JSON correctness, Piano Roll targeting and safer Windows setup (#17, #22, #27, #30, #32).
- Chords/drums to MIDI, step-grid control and cross-platform CI (#23, #24, #26, #32).
- Keyboard-layout-independent Windows note triggering and optional native FL per-note portamento (#16, #18).

### Added
- macOS setup support: `scripts/install_macos.sh`, IAC Driver instructions, `Cmd+Opt+Y` note-bridge trigger (#4).
- `server.json` for MCP Registry publishing; `glama.json` for Glama indexing.
- PyPI metadata (ownership marker, classifiers).
- Community health files: Code of Conduct, security policy, issue/PR templates, this changelog.

### Changed
- Documented the 8 mixer/channel set tools.

## [1.0.0] - 2026-05-26

First public release.

### Added
- MCP server and TCP daemon bridging Claude (and other MCP clients) to FL Studio over a SysEx controller script.
- Transport, mixer, channel and plugin-parameter tools with safety-checked writes, readback and rollback (`safe_write`, dry-run, changelog).
- Mixing intents: EQ, reverb, delay and compression (Fruity Limiter COMP); routing read/write/group.
- Mix Doctor: whole-mix snapshot, sustained/full-song peak watch, threshold diagnosis, and gated apply-fixes (`fl_diagnose_mix`, `fl_apply_mix_fix`).
- Gain staging assistant (`fl_gain_stage`) and reference match (`fl_reference_match`).
- Audio analysis with CREPE pitch engine (pyin fallback) and confidence gating.
- Raga/scale composer (`fl_write_raga_melody`, `fl_write_raga_chords`).
- Genre chain setup (`fl_setup_chain`, `fl_list_chains`), library-aware chains from FL's installed-plugin database, and preset suggester (`fl_list_presets`, `fl_suggest_preset`).
- MIDI export (`fl_export_midi`), quantize via the pyscript bridge, bulk mute/solo, track/channel coloring.
- Windows installer (`scripts/install_windows.bat`), README v1.0, demo GIF, contributing guidelines.

### Removed
- One-off probes and dead `detect_cleanup` controller code.

[Unreleased]: https://github.com/rosasynthesiz/flstudio-mcp/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rosasynthesiz/flstudio-mcp/releases/tag/v1.0.0
