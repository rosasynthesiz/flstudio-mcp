# Roadmap

> **Transport note (v0.2):** the FL <-> server channel is MIDI SysEx, not a
> file queue. See [`docs/architecture.md`](docs/architecture.md) and
> [`docs/CHANGELOG.md`](docs/CHANGELOG.md). The tool surface is unchanged;
> phase work continues on top of the new transport.

Tracking the full scope — eight phases shipping the MCP server, the scale/mode
composition tools, the SKILL.md, evals, and the Claude Code plugin marketplace
bundle.

Each phase is shippable on its own. Each ends with `python scripts/test_bridge.py`
still passing.

## Phase 0 — Foundation (shipping)

Goal: prove the SysEx bridge works end-to-end and ship the absolute
minimum tool surface.

- [x] MIDI SysEx protocol (commands, responses, heartbeat) over two virtual MIDI ports.
- [x] FL controller script with `OnSysEx`/`OnMidiMsg` dispatch and an `OnIdle` heartbeat.
- [x] FastMCP server skeleton with stdio transport.
- [x] Transport tools: ping, tempo get/set, play, stop, toggle, record,
      play-state, song-position get/set. **10 tools total.**
- [x] `scripts/test_bridge.py` standalone harness.
- [x] Install scripts for Windows and macOS. (Linux: not shipped — contributions welcome.)

## Phase 1 — Channel rack (~12 tools)

The channel rack is where most users place samples and instruments.

- `fl_channel_list` — Names, types, colors, current pattern.
- `fl_channel_get` — Volume, pan, mute, solo, target mixer track.
- `fl_channel_set_volume`, `_pan`, `_mute`, `_solo`.
- `fl_channel_select` — Make a channel active.
- `fl_channel_get_grid` — Read the step-sequencer grid for the current pattern.
- `fl_channel_set_grid_bit` — Write a single step. (This is how we draw drum
  patterns without needing the Piano Roll pyscript.)
- `fl_channel_clear_grid` — Wipe steps for a channel in the current pattern.
- `fl_channel_get_color`, `_set_color` — Visual organization.

Risk: FL's channel API uses `channels.channelNumber()` and `channels.selectedChannel()`
for the active channel. Some functions need the explicit index; some use the
selection. The script normalizes to explicit indices.

## Phase 2 — Mixer (~10 tools)

- `fl_mixer_list_tracks` — Up to 125 tracks plus Master at index 0.
- `fl_mixer_get_track` — Name, volume, pan, mute, solo, dock side, color.
- `fl_mixer_set_volume`, `_set_pan`, `_set_mute`, `_set_solo`.
- `fl_mixer_select_track` — Drive UI focus.
- `fl_mixer_get_route` — Where this track's audio is sent.
- `fl_mixer_set_route` — Add/remove a route to another track.
- `fl_mixer_get_levels` — Peak meter sample (read via `OnUpdateMeters`).

Risk: `setTrackVolume` takes a normalized float 0.0–1.0 where 0.8 is unity
gain, not 1.0. The tools accept dB and convert.

## Phase 3 — Patterns + playlist (~6 tools)

- [x] `fl_pattern_list` — Names, paginated (600-byte pages, `fetch_all_pages`).
- [x] `fl_pattern_select`, `_rename` — via `safe_write` (scope `pattern:N`), one rollback step each.
- [x] `fl_pattern_get_length` — beats (FL's native unit) + derived bars/ticks via RecPPQ/RecPPB.
- `fl_playlist_get_tracks` — Playlist track names and visibility.
- `fl_playlist_get_markers` — Time-line markers (used to insert section markers).

API limits worth surfacing in tool docs:
- New patterns cannot be created from scratch; clone an existing pattern
  instead (`fl_arrange_clone_pattern`).
- Patterns cannot be deleted via the API (a test pattern has to be renamed
  to a TMP_ marker and removed by hand in FL).

## Phase 4 — Piano Roll pyscript (~6 tools)

This is the most invasive phase — adds the second script type.

- `fl_piano_write_notes` — Note batch into the active pattern's Piano Roll.
- `fl_piano_write_chord` — Helper that builds a chord by name (`Cmaj7`,
  `Bbm9`) and writes it.
- `fl_piano_clear` — Wipe the active pattern.
- `fl_piano_quantize` — Snap selected notes.
- `fl_piano_transpose` — Shift in semitones.
- `fl_piano_get_notes` — Read back what is in the active pattern.

Mechanics:
1. FL's pyscript sandbox can't receive data the server hands it, so the daemon
   generates the `MCP_Apply` `.pyscript` with the notes baked in and writes it
   into FL's Piano roll scripts folder.
2. FL exposes no API to run a pyscript, so the note bridge is armed once per
   session: run `MCP_Apply` from the Piano roll's Scripting menu.
3. To apply a batch, the daemon force-focuses FL and re-triggers the armed
   script (FL's "Run last script again"); FL re-reads the `.pyscript` and writes
   the notes. No file queue, no JSON polling.

The Piano roll must be FL's active panel for the re-trigger to land, so the
bridge force-focuses FL first.

## Phase 5 — Plugin params (~5 tools)

- [x] `fl_plugin_get_params` — paginated dump: index, name, normalised value (covers the old `fl_plugin_list_params` name; the dead declaration was removed in E-2, see `docs/E2_REPORT.md`).
- [x] `fl_plugin_set_param` — single write, verified (E-1); `fl_plugin_set_params` — batch, one undo step (E-1).
- `fl_plugin_get_preset_name`, `_select_preset_index` — not yet exposed as tools (`fl_list_presets`/`fl_suggest_preset` read the on-disk library instead).

This is intentionally scoped tight. Per-VST parameter naming is a mess across
plugins; we expose the raw FL view and let the LLM map names.

## Phase 6 — Scale & mode composition (~8 tools)

Genre- and producer-agnostic composition in any scale or mode: Western modes,
pentatonic, the Carnatic melakarta and janya ragas, Arabic maqam, and beyond.
Claude supplies the correct notes/intervals for the requested scale and writes
them through the note bridge. Indian ragas are one supported family among many,
not the headline.

- Scale catalogue — scales and modes by family, each with its
  ascending/descending intervals (e.g. the 72 melakarta ragas plus common
  janyas — Bhairavi, Mohanam, Kalyani — alongside Western modes, pentatonic,
  and maqam).
- Scale → note mapping at a chosen base note.
- Melody and chords in a chosen scale, shaped by a mood/character (e.g.
  `devotional`, `cinematic`, `melancholic`, `energetic`), written via the note
  bridge (`fl_write_raga_melody`, `fl_write_raga_chords`).
- Section markers for arrangement (intro, build, drop, …).

Micro-tonal and gamaka-heavy traditions (e.g. Carnatic) get the *scale
framework* — correct swaras/intervals — not gamaka or micro-tonal rendering;
that's a 12-tone MIDI limit, not a tool limit.

Scale/mode data lives in `src/fl_studio_mcp/presets/` as plain Python modules
so it ships inside the wheel.

## Phase 7 — Polish & ship

- [ ] `skills/flstudio-production/SKILL.md` orchestration layer with deep
      content in `references/`. Under 500 lines.
- [ ] `evals/evals.json` — 10 questions exercising the full tool surface.
- [ ] `.claude-plugin/marketplace.json` so this can live in
      `rosasynthesiz-skills` as an installable plugin.
- [ ] `AGENTS.md` describing the agentic workflow for future Claude sessions
      working on this codebase.
- [ ] Demo video and screenshots in `docs/`.
- [ ] GitHub Actions for linting and the standalone bridge tests (mock FL).
- [ ] Pin a known-working FL Studio version range in README.

## Out of scope (intentionally)

- Loading new VST instances — FL API does not allow this.
- Creating new patterns ex nihilo — same limitation.
- Audio recording control beyond the record-arm toggle.
- Multiple FL Studio instances on one machine — not currently wired.
