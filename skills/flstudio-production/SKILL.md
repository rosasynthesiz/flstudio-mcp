---
name: flstudio-production
description: Use this skill whenever the user wants to control FL Studio from Claude — write or trigger drum patterns, set tempo, change mixer levels, write notes to the Piano Roll, build a house/raga/kuthu arrangement, reuse a recorded MIDI as the motif, or troubleshoot the FLStudioMCP bridge (notes not appearing, notes on the wrong bar or channel, hotkey not firing). Trigger on FL Studio, FL, Fruity Loops, FLStudioMCP, "FL-il pannu", music production via Claude. ALWAYS use the fl-studio MCP server tools — never instruct the user to perform the change manually if a tool exists.
---

# FL Studio production skill

This is the orchestration layer for the fl-studio MCP server. Deep detail lives
in `references/`.

## Before you act

1. Call `fl_ping` once at the start of every session. If `status` is not
   `READY`, stop and tell the user the `next` step it returns (for example:
   open FL Studio and load a project, or run `fl-studio-mcp setup`). Do not
   retry blindly.
2. Read `references/limits.md` (and the README's Limitations section) so you
   don't promise things the FL API can't deliver (no plugin loading, no audio
   loading, no rendering, no note readback).
3. If the user is going to write Piano Roll notes, FL Studio must be the
   focused window, and the user must run `MCP Apply` once from the Piano roll's
   Scripting menu this session. Warn them once at the start.

## Tool selection

| User intent | Tools |
|---|---|
| Tempo, play, stop | `fl_set_tempo`, `fl_play`, `fl_stop`, `fl_toggle_play` |
| Where are we in the song | `fl_get_song_position`, `fl_get_project_state` |
| Drum patterns | `fl_set_step_grid`, `fl_get_step_grid` — NOT the Piano Roll |
| Mixer levels | `fl_set_mixer_volume`, `fl_set_mixer_pan` |
| Melody in a raga | `fl_write_raga_melody`, which writes through the Piano Roll bridge |
| Chords / progression | `fl_write_raga_chords`, `fl_write_piano_roll_notes` |
| Quantise notes already recorded | `fl_quantize_pattern` (needs the armed bridge) |
| Read a plugin's knobs | `fl_plugin_list`, `fl_plugin_get_params` (names + normalised 0..1 values) |
| Change one knob | `fl_plugin_set_param` — answers `verified` / `attempts`; a `hint` means FL refused the value |
| Change several knobs of one plugin | `fl_plugin_set_params` — one paced burst, ONE undo step; prefer it over repeating the single tool |
| List / pick / rename patterns | `fl_pattern_list` (paginated), `fl_pattern_select`, `fl_pattern_rename` — select/rename are one rollback step each |
| How long is a pattern | `fl_pattern_get_length` — beats (FL's native unit) + derived bars/ticks via the project PPQ |
| Sections | `fl_arrange_add_marker`, `fl_arrangement_markers`, `fl_playlist_*` |
| Verify by eye | `fl_screenshot` (`region` is in logical points, PNG is 2× on retina) |

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

## Piano roll note bridge — the five rules

Note writes are blind (the API cannot read notes back). The server generates
`MCP_Apply.pyscript`, overwrites it, and presses FL's "Run last script again".
`references/note-bridge.md` has the mechanics and a 60-second verification.

1. **`time_bars` = FL bars, and the template's `score.PPQ * 4` is correct.**
   Never hand-edit that scaling. `score.PPQ` is pulses per *quarter* (96 on FL
   26.1.7); dividing by 4 squeezes a whole phrase into bar 1.
2. **A write lands on the channel whose Piano roll is OPEN**, not the `channel=`
   you pass. Ask the user to click the channel row in the Channel Rack, confirm
   the `Piano roll - <name>` title in a screenshot, then write all patterns for
   that channel before switching.
3. **Never `mode="replace"` on an unconfirmed channel** — it clears that
   channel's notes in the pattern. Export the live take as `.mid` before
   rewriting it.
4. **Verify with the script and the ruler.** `grep '^NOTES' MCP_Apply.pyscript`
   is the ground truth of what will be written (tool echoes truncate); a
   screenshot showing the Piano roll title plus the bar ruler answers both
   "which channel" and "where on the timeline". Pattern length is not a
   reliable check.
5. **Phrase length = drum grid length = playlist clip length.** Read the grid
   with `fl_get_step_grid(channel, length=64)` (it can be 64 steps = 4 bars).
   The API cannot create or resize clips, so tell the user the exact bar and
   length to drag.

If notes never land on macOS with a non-Latin keyboard layout, the trigger's
`keystroke "y"` is resolved through the layout; send `key code 16` instead:

```bash
osascript -e 'tell application id "com.image-line.flstudio" to activate' \
  -e 'delay 0.4' \
  -e 'tell application "System Events" to key code 16 using {command down, option down}'
```

Synthetic `click at` does not reach FL at all — see
`references/troubleshooting.md`.

## Working rhythm

1. Agree the target: genre, tempo, sections, and how many bars each.
2. Read the project first (`fl_get_project_state`, `fl_get_channel_state`,
   `fl_get_mixer_state`, `fl_get_channel_routing`).
3. Fix the section map and phrase length, add markers, read the drum grid.
4. Write drums (step sequencer) → bass → chords → motif, one channel at a time,
   verifying after the first write to each new channel.
5. Play it and check levels; propose one change at a time. Use
   `fl_rollback_last_change` for API edits, and say plainly that clips, clip
   length and bouncing are the user's to drag.

Arrangement shape, MIDI motifs and sectioning: `references/arrangement.md`.

## When something fails

- `FLNotRunning` → bridge is healthy, FL is not. Ask user to open FL.
- `FLTimeout` → controller is loaded but stalled. Ask user to re-select
  FLStudioMCP in MIDI Settings.
- `FLCommandFailed` with `code=client` → bad input. Show the user what was
  wrong and ask for a correction.
- `FL_BUSY` → a dialog is open (the welcome screen counts). Ask the user to
  close it; do not retry in a loop.
- Anything that looks like "notes in the wrong place / wrong channel / missing"
  → `references/troubleshooting.md`.

## References

- `references/note-bridge.md` — pyscript mechanics, time scaling, triggers,
  channel targeting, batch generation.
- `references/arrangement.md` — phrase/grid/clip alignment, MIDI motifs,
  sectioning, channel routing.
- `references/limits.md` — what the API cannot do, and how to say it.
- `references/troubleshooting.md` — symptom → cause → fix table.
