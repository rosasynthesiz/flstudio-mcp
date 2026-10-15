# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
