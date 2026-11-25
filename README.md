# FL Studio MCP — control FL Studio with Claude, Cursor and other AI assistants

**The MCP server for FL Studio (Fruity Loops): AI mixing, mix diagnosis, plugin control, piano roll and drum patterns, in plain language.**

**Website:** [rosasynthesiz.com/products/fl-studio-mcp](https://rosasynthesiz.com/products/fl-studio-mcp): what it does, all 90 tools and setup.

[![PyPI](https://img.shields.io/pypi/v/fl-studio-mcp)](https://pypi.org/project/fl-studio-mcp/)
![status](https://img.shields.io/badge/status-beta-yellow)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.10+-blue)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-blue)
![FL Studio](https://img.shields.io/badge/FL%20Studio-2025%2B-orange)

![Claude diagnosing and fixing a mix in FL Studio](docs/demo.gif)

*Claude diagnosing and fixing a mix in FL Studio through natural language.*

## Overview

`flstudio-mcp` is a Model Context Protocol (MCP) server that connects FL Studio to AI assistants: Claude Code, Claude Desktop, Cursor, Codex, or any other MCP client. Ask for a mix diagnosis, a vocal chain, a chord progression in a particular scale, or a full arrangement, and the assistant carries it out inside your open FL Studio project through FL's scripting API and a set of calibrated, safety-checked tools.

- **90 tools** for the mixer, plugins, piano roll, step sequencer, patterns, playlist, routing and transport
- **One-command setup on macOS**, with no MIDI configuration
- **Every change can be undone**, and an undo never touches a different project
- **Windows and macOS**, FL Studio 2025 and 2026

It is genre- and producer-agnostic: nothing about it assumes a particular style of music.

## Quickstart

**macOS** — one command, no MIDI setup:

```bash
uvx --from git+https://github.com/rosasynthesiz/flstudio-mcp fl-studio-mcp setup
```

It installs the FL controller script, then waits. Open FL Studio and load any
project; the command prints `Status: READY` once FL answers. You do not create
IAC ports and you do not touch FL's MIDI Settings: the server makes its own
MIDI ports and FL links them by itself.

Then add the server to your AI client:

```bash
uvx --from git+https://github.com/rosasynthesiz/flstudio-mcp fl-studio-mcp connect
```

**Windows** — two loopMIDI ports and one step in FL (details in [Setup](#setup)):

```bat
:: first: in loopMIDI, create two ports named exactly "FLStudioMCP RX" and "FLStudioMCP TX"
git clone https://github.com/rosasynthesiz/flstudio-mcp.git
cd flstudio-mcp
scripts\install_windows.bat
```

Then ask Claude in plain language:

> "Scan my mix and tell me what's wrong." — "Set up a vocal chain from my plugins." — "Export this arrangement to MIDI."

If something does not connect, run `fl-studio-mcp doctor`. It checks each
stage and prints one status and the one next step.

The PyPI package (`fl-studio-mcp` 1.0.0) is the older v1 and does not have
these commands yet; use the commands above until 2.0.0 is released.

## Capabilities

### Mixing & diagnosis
- **Mix Doctor** — scans the whole mix and reports concrete problems (clipping, low headroom, level imbalance, missing high-pass, ungrouped related tracks, overlapping EQ boosts), each with the exact evidence and a proposed fix. Fixes are applied one at a time, only on approval, through a snapshot → write → readback → rollback safety layer. Master clipping is resolved by trimming the contributing source tracks rather than pulling the master.
- **Full-song peak watch** — holds a running peak per track across playback, so level decisions are based on the loudest moment of the actual song, not a single instant.
- **Calibrated processing intents** — musical EQ, compression, reverb, and delay moves mapped to real plugin parameters (native and third-party), each applied as one reversible change.
- **Level-aware compression** — sets thresholds relative to a track's measured level during playback.
- **Gain staging** — proposes per-track trims toward a healthy level with proper master headroom.
- **Reference match** — compares your mix's level and tonal balance against a reference track.
- **Bulk track control** — solo or mute a whole group (drums, vocals, …) in one step, with a one-call reset.
- **Track & channel coloring** — color a track, a channel, or a whole group (drums, vocals, …) by color name or hex, reversible like every other change.

### Plugin & preset control
- Read and set plugin parameters by name, on native and third-party plugins (the parameter list is resolved live).
- **Verified writes** — every parameter write is re-read on a fresh tick and retried (0.4 s apart) if FL did not take it; the answer carries `verified` / `attempts` and a `hint`, so a swallowed write is reported instead of echoed back as if it worked.
- **Batch parameter changes** — `fl_plugin_set_params` sets several knobs of one plugin in a single paced burst and one undo step; `fl_rollback_last_change` puts them all back together.
- **Chain suggestions** and **preset recommendations** drawn from your actual installed library — read directly from FL's plugin database and preset folders on disk, so recommendations are limited to what you own.

### Composition
- **Multi-track MIDI export** — generate a complete arrangement as a standard MIDI file to import.
- **Multi-pattern arrangement** — create, name, clone, and mark sections.
- **Pattern control** — list (paginated), select, rename, and read the length (beats/bars via the project PPQ) of any pattern; select and rename are single reversible steps with their own rollback.
- **Drum patterns in the step sequencer**: read or set a channel's steps in the current pattern, e.g. `x...x...x...x...`, reversible like every other change.
- **Note and chord writing** into the piano roll, with quantize to a grid (for new notes and existing ones).
- **Composition in any scale or mode** — Western modes, pentatonic, ragas, maqam, and beyond — through the scale composer, where Claude supplies the notes for the requested scale.

### Audio analysis
- Tempo and key estimation from an audio file.
- Melody-to-MIDI transcription (CREPE pitch tracking, with a lighter fallback).
- **Chords-to-MIDI** transcription of polyphonic audio (keys, piano, guitar) with Spotify's Basic Pitch, as notes for the piano roll or a `.mid` file.
- **Drums to MIDI**: a drum loop or stem to kick, snare, clap, closed and open hi-hat, aligned to the beat, as a `.mid` or straight into the step sequencer of the channels you choose (one undo step).

The server exposes 90 tools, plus 6 live resources (project, mixer, transport, channels, patterns, status) that Claude can read directly.

## What sets it apart

flstudio-mcp is built as a mixing and production assistant, not only a note sender. It diagnoses and repairs a whole mix, makes decisions from real measured levels rather than guesswork, and is aware of your actual plugin and preset library when it makes suggestions. Every change that touches the project is shown before it is applied, logged, and reversible.

## Limitations

These are properties of FL Studio's scripting API, stated plainly:

- **Plugins, audio files, and rendering are UI-only.** FL's API cannot load a plugin, load an audio file, or render audio. The plugin and preset tools therefore *suggest* — you load the chosen plugin or preset, and Claude then configures it. Audio export is done manually (File > Export); Claude can analyze the rendered file afterward.
- **Only some plugin parameters accept arbitrary values.** Levels and gains do; stepped parameters (filter types, orders, selectors) snap to their own grid steps, so an off-grid request cannot land; some parameters (Fruity Parametric EQ 2's band widths) ignore writes entirely. The parameter tools re-read and retry, then report `verified: false` with a `hint` and the value FL actually holds, instead of echoing the request as if it had landed.
- **Note writing is armed once per session.** A generated pyscript writes notes into the piano roll; FL exposes no API to run a pyscript, so you run "MCP_Apply" once from the piano roll's scripting menu at the start of a session.
- **Micro-tonal and gamaka-heavy music is approximated.** Scales with intervals smaller than a semitone (e.g. Arabic maqam) are rounded to the nearest semitone, and traditions built on gamaka/ornamentation (e.g. Carnatic) get the *scale framework* — the correct swaras and intervals — not gamaka or micro-tonal rendering. That's a limit of 12-tone MIDI, not of the tools.

## Requirements

- **macOS** or **Windows 10/11** (Linux: untested, the macOS path should apply)
- **FL Studio 2025** or newer (tested on 26.1)
- **Claude Code**, **Claude Desktop**, Cursor, Codex or any MCP client
- **Python 3.10+** (with `uvx`, [uv](https://docs.astral.sh/uv/) brings its own)
- Virtual MIDI ports:
  - macOS: nothing to install, the server creates them
  - Windows: **loopMIDI** ([download](https://www.tobias-erichsen.de/software/loopmidi.html))
- Optional: **ffmpeg** on PATH (for MP3 analysis)

## Setup

### macOS

1. **Run setup:**
   ```bash
   uvx --from git+https://github.com/rosasynthesiz/flstudio-mcp fl-studio-mcp setup
   ```
   It copies the controller script into FL Studio's user-data folder (a
   different existing copy is kept next to it as a `.bak-<date>` file), then
   waits for FL Studio.
2. **Open FL Studio and load any project.** If FL was already open, restart it
   once. Setup prints `Status: READY` when FL answers.
3. **Add the server to your client:** run `... fl-studio-mcp connect` and paste
   the entry it prints (Claude Code, Claude Desktop, Cursor, Codex).

That is all. How it works: the server creates two virtual MIDI ports that share
one name, `FLStudioMCP`. The controller script lists that name as its supported
device, so FL links the script, pairs input and output on one port number and
enables them without any clicks. FL has to see the ports when it starts the
first time; after that it re-attaches by itself.

Working from a clone instead: `./scripts/install_macos.sh` does the same inside
a private `.venv` in the repo (your system Python is not touched).

Already using IAC Driver ports named `FLStudioMCP RX` / `FLStudioMCP TX`? They
keep working and are used first. `FLSTUDIO_MCP_VIRTUAL_PORTS=0` stops the
server from creating its own ports.

### Windows

Windows cannot create MIDI ports from a program, so loopMIDI is still needed.

1. **Create two loopMIDI ports** named exactly `FLStudioMCP RX` and
   `FLStudioMCP TX`:
   - Install and open [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html).
   - Remove default ports (`loopMIDI Port`, …); those names are not detected.
   - Type `FLStudioMCP RX` in **New port-name**, click **+**. Repeat for `FLStudioMCP TX`.
   - Keep loopMIDI running (it can start with Windows).
2. **Install:**
   ```bat
   git clone https://github.com/rosasynthesiz/flstudio-mcp
   cd flstudio-mcp
   scripts\install_windows.bat
   ```
   The server goes into a `.venv` folder inside the repo, using Python
   3.12/3.11/3.10 when available. The installer prints the full paths of the
   commands. It finds your Documents folder even when it is redirected
   (OneDrive, non-English names) and follows FL's own "User data folder"
   setting; if it still cannot find the folder, run
   `setx FL_SETTINGS "<folder>\FL Studio\Settings"` once and open a new terminal.
3. **Configure FL Studio once** — Options > MIDI Settings:
   - Input list: select `FLStudioMCP RX`, turn on **Enable**, set Controller
     type to **FLStudioMCP**, and give it a Port number.
   - Output list: select `FLStudioMCP TX` and give it the **same** Port number.
4. **Check:** `.venv\Scripts\fl-studio-mcp.exe doctor` should print `Status: READY`.
5. **Add the server to your client:** `.venv\Scripts\fl-studio-mcp.exe connect`
   prints the entry, with the full path already filled in.

### Both platforms

**No daemon to start.** The first MCP server that starts owns the MIDI ports
and shares them on a local socket; a second client joins it automatically.
The standalone daemon (`fl-studio-mcp-daemon`, Windows: `scripts\start_daemon.bat`)
is still there for one case: an MCP client that cannot receive MIDI itself,
such as the Microsoft Store build of Claude Desktop. Start the daemon first and
the server joins it. An older config with `FLSTUDIO_MCP_TRANSPORT=tcp` keeps
working, with or without the daemon; the setting is no longer needed. Set
`FLSTUDIO_MCP_TRANSPORT=daemon` to make a server use the daemon only and never
open MIDI itself.

**Note writing is armed once per session.** Open the piano roll and choose
**Tools > Scripting > MCP > MCP Apply** once. On macOS the note bridge then
sends `Cmd+Opt+Y`; grant Accessibility permission to the app that runs the MCP
server (**System Settings > Privacy & Security > Accessibility**).

**Optional audio features** (not installed by default):
```
pip install -e ".[audio]"                    # tempo/key, drums to MIDI, light melody
pip install -e ".[audio,audio-accurate]"     # + CREPE (accurate melody)
pip install -e ".[audio-chords]"             # chords: then also run
pip install --no-deps basic-pitch==0.4.0     #   (skips its TensorFlow requirement)
```
The installers take `FLMCP_EXTRAS` (`all`, `none`, or any of `audio accurate chords`);
the Windows installer also asks.

**Undo is tied to the project.** Every change Claude makes can be rolled back
with `fl_rollback_last_change`, but only inside the project and FL session it
was made in. An entry from another project is refused, never applied.

After updating, run `setup` again and restart FL Studio so the controller and
the server are the same version (`doctor` reports a mismatch). See
[bridge correctness regressions](docs/bridge-correctness-regressions.md) for
numeric JSON compatibility, dry-run behavior, and localized parameter names.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Anything about connecting | `fl-studio-mcp doctor` checks each stage and prints one status code and the one next step. Start here. |
| A change is refused with `FL_BUSY` | FL Studio refuses writes while a dialog is open (the welcome screen counts). Close it or load a project, then try again. |
| Virtual MIDI ports not found / not detected | The two ports must be named **exactly** `FLStudioMCP RX` and `FLStudioMCP TX`. loopMIDI's default `loopMIDI Port` names won't work. Recreate them in loopMIDI (Windows) or IAC Driver (macOS), make sure loopMIDI is running, then re-run the installer. |
| `FL Studio Settings\Hardware folder not found` | Open FL Studio once so it creates its user-data folder. If you moved that folder (Options > File settings > User data folder), `setx FL_SETTINGS "<that folder>\FL Studio\Settings"`, open a new terminal and re-run. |
| `fl-studio-mcp-daemon` is not recognized | The commands live in the repo's `.venv\Scripts\` folder. Run them by full path (the installer prints it). |
| Python crashes on start / MIDI library fails to load (Windows) | Install Python 3.12 from python.org, delete the `.venv` folder, and re-run the installer. |
| No `[FLStudioMCP] Ready` in FL's Script output | The controller isn't registered: set the `FLStudioMCP RX` input's **Controller type** to **FLStudioMCP** in MIDI Settings, confirm `device_FLStudioMCP.py` is in `Settings\Hardware\FLStudioMCP\`, then fully restart FL Studio. |
| Claude can't reach FL / `fl_ping` fails | Run `fl-studio-mcp doctor` and do the step it prints. `fl_ping` returns the same `status` and `next`. Most common: FL Studio has no project loaded yet, or FL was opened before the server the first time (restart FL once). |
| `fl_ping` says the heartbeat is stale (`Ready` is shown, but FL stops answering) | Usually happens after changing MIDI Settings while the script is running. Open View > Script output, select the FLStudioMCP tab and click **Reload script** (or restart FL Studio). Also check that the Output port number is on `FLStudioMCP TX`, not `FLStudioMCP RX`. |
| Note-writing does nothing | Run `MCP_Apply` once from the piano roll's scripting menu this session — it arms the note bridge. |
| macOS note-trigger fails | Grant Accessibility permission to the app running the MCP server or daemon, then click the FL Piano roll and try `Cmd+Opt+Y`. |
| Audio tools error or are unavailable | Re-run the installer and answer Y to "Install audio to MIDI?" (or install the extras manually, see Setup step 2). |
| The installer stops because the MCP server is running | Claude Desktop or Claude Code is running `fl-studio-mcp.exe` from the `.venv`, which locks its files. Quit Claude Desktop or Claude Code, then re-run. |

## Usage examples

Plain-language prompts:

- "Scan my mix and tell me what's wrong."
- "Set up a vocal chain on the lead vocal using my plugins."
- "Suggest a vintage bass preset from my Serum library."
- "Compose an 8-bar melody in D Dorian and write it to the selected channel."
- "Export this arrangement to a MIDI file."
- "What tempo and key is this track?" (on an audio file)

## Tools

90 tools, grouped by area.

### Transport

- `fl_ping` — Check that FL Studio is running and the controller script is loaded.
- `fl_get_tempo` — Read the project tempo in BPM.
- `fl_set_tempo` — Set the project tempo (10–999 BPM).
- `fl_play` — Start playback.
- `fl_stop` — Stop playback.
- `fl_toggle_play` — Toggle play and stop, like the spacebar.
- `fl_record` — Toggle record-arm.
- `fl_get_play_state` — Report whether FL is playing or recording.
- `fl_get_song_position` — Read the playhead position in beats.
- `fl_set_song_position` — Move the playhead to a beat position.

### Project, mixer & channel state

- `fl_get_project_state` — Tempo, transport state, and pattern, channel and mixer counts.
- `fl_get_mixer_state` — Every mixer track with name, volume, pan, mute and solo.
- `fl_get_channel_state` — Every channel-rack channel with name, volume, pan, mute and solo.
- `fl_set_mixer_volume` — Set a mixer track's volume (linear or dB).
- `fl_set_mixer_pan` — Set a mixer track's pan (-1 left to +1 right).
- `fl_set_mixer_mute` — Mute or unmute a mixer track.
- `fl_set_mixer_solo` — Solo or unsolo a mixer track.
- `fl_set_mixer_name` — Rename a mixer track.
- `fl_set_channel_volume` — Set a channel's volume (linear or dB).
- `fl_set_channel_pan` — Set a channel's pan (-1 left to +1 right).
- `fl_set_channel_mute` — Mute or unmute a channel.
- `fl_set_channel_solo` — Solo or unsolo a channel.
- `fl_take_snapshot` — Read the current state of a scope for before/after comparison.
- `fl_rollback_last_change` — Undo the most recent write from its saved snapshot.
- `fl_set_dry_run` — Preview writes without changing the project.

### Mix Doctor & gain staging

- `fl_diagnose_mix` — Scan the whole mix and report problems with proposed fixes (read-only).
- `fl_apply_mix_fix` — Apply one Mix Doctor fix with snapshot, readback and rollback.
- `fl_mix_watch_start` — Start a full-song peak watch that keeps each track's loudest moment.
- `fl_mix_watch_status` — Report whether a peak watch is running and for how long.
- `fl_mix_watch_stop` — Stop the peak watch and diagnose the mix on full-song peaks.
- `fl_gain_stage` — Propose per-track fader trims toward a healthy level with master headroom.
- `fl_reference_match` — Compare your mix's level and tonal balance to a reference track.

### Processing intents

- `fl_apply_eq_intent` — Apply a musical EQ move on Fruity Parametric EQ 2.
- `fl_apply_compression_intent` — Compress with Fruity Limiter or FabFilter Pro-C, relative to the measured level.
- `fl_apply_reverb_intent` — Reverb moves on Fruity Reeverb 2 (decay, wet, high-cut) as one undoable change.
- `fl_apply_delay_intent` — Delay moves on Fruity Delay (time, feedback, wet, feedback cut) as one undoable change.
- `fl_get_track_level` — Measure a mixer track's level from its meter over a short window.

### Plugin parameters

- `fl_plugin_list` — List the filled effect slots on a mixer track.
- `fl_plugin_get_params` — List every named parameter of a plugin with its value and display text.
- `fl_plugin_set_param` — Set one plugin parameter, then verify it landed.
- `fl_plugin_set_params` — Set several parameters of one plugin as a single rollback unit.
- `fl_plugin_overview` — Summarise a plugin: how controllable it is and its parameters grouped by role.
- `fl_plugin_find_params` — Search a plugin's parameters by name.
- `fl_plugin_calibrate_param` — Learn a parameter's real unit (dB, Hz, ms, %) by sweeping it, then restoring it.
- `fl_plugin_set_param_value` — Set a parameter to a real-unit value, for example 6 dB or 30 %.
- `fl_plugin_intent` — Make a musical change by intent: brighter, darker, wider, more drive and others.
- `fl_load_plugin` — Explains why FL's API cannot load a plugin and what to do instead.

All plugin tools also reach channel-rack instruments: pass `slot=-1` and the channel index as `track`.

### Presets & processing chains

- `fl_list_presets` — List preset names from your FL Studio and Serum 2 preset folders.
- `fl_suggest_preset` — Suggest presets from your own library that match a description.
- `fl_list_chains` — List the built-in processing-chain recipes (vocal, drum bus, bass, master).
- `fl_list_installed_plugins` — List the plugins installed in FL Studio, de-duplicated and categorized.
- `fl_setup_chain` — Plan a processing chain over a track's existing plugins.

### Routing

- `fl_get_routing` — Show which tracks a mixer track sends to.
- `fl_get_routing_all` — Show routing for every mixer track.
- `fl_get_channel_routing` — Show which mixer track each channel is linked to.
- `fl_detect_cleanup_candidates` — Flag empty channels and unused mixer tracks, with a reason (read-only).
- `fl_set_route` — Turn a send between two mixer tracks on or off.
- `fl_group_tracks` — Route a group of tracks into a bus, and the bus to the master.

### Bulk mute, solo & color

- `fl_solo_tracks` — Solo a group (drums, vocals, …) so only it is audible.
- `fl_mute_tracks` — Mute a group of tracks.
- `fl_clear_mute_solo` — Unmute and unsolo every mixer track.
- `fl_set_track_color` — Color mixer tracks by name, group, color name or hex.
- `fl_set_channel_color` — Color channel-rack channels.

### Composition & arrangement

- `fl_write_piano_roll_notes` — Write notes into the open piano roll.
- `fl_quantize_pattern` — Quantize the notes already in the open piano roll.
- `fl_write_raga_melody` — Write a melody in any scale into the selected channel.
- `fl_write_raga_chords` — Write chords or a progression in any scale into the selected channel.
- `fl_get_step_grid` — Read which step-sequencer steps are on for a channel.
- `fl_set_step_grid` — Set exactly which step-sequencer steps are on for a channel.
- `fl_arrange_new_pattern` — Create, select and name the next empty pattern.
- `fl_arrange_select_channel` — Select a channel-rack channel.
- `fl_arrange_clone_pattern` — Clone a pattern with its notes and rename the clone.
- `fl_arrange_add_marker` — Add a named timeline marker at a bar.
- `fl_export_midi` — Write a multi-track .mid file from an arrangement.

### Playlist & arrangement

- `fl_playlist_tracks` — List playlist tracks with name, mute and solo state (paged).
- `fl_playlist_mute_track` — Mute or unmute a playlist track.
- `fl_playlist_solo_track` — Solo a playlist track; refused when it could not be undone cleanly.
- `fl_playlist_rename_track` — Rename a playlist track.
- `fl_playlist_set_track_color` — Colour a playlist track by name or hex.
- `fl_arrangement_markers` — List the timeline markers.
- `fl_arrangement_selection` — Read the current time selection in the playlist.

### Setup report

- `fl_capabilities` — Report what this setup automates and which steps stay manual.

### Patterns

- `fl_pattern_list` — List the project's patterns with their names.
- `fl_pattern_select` — Switch the working pattern; one undo step.
- `fl_pattern_rename` — Rename a pattern; one undo step.
- `fl_pattern_get_length` — Read a pattern's length in beats, bars and ticks.

### Audio analysis

- `fl_analyze_audio` — Estimate tempo and key of an audio file.
- `fl_extract_melody` — Transcribe a single-line melody from audio to notes.
- `fl_extract_chords` — Transcribe chords from audio to notes.
- `fl_extract_drums` — Detect drum hits in a loop or stem and sort them into kick, snare, clap and hi-hats.

## Architecture

A thin controller script runs inside FL Studio and returns only cheap, raw data; all judgement — diagnosis, calibration, planning — happens server-side. The two talk over MIDI SysEx, the only channel FL's script sandbox allows. The first MCP server to start owns the MIDI ports and shares them on a local socket, so several clients can use one FL Studio at once. Note authoring uses a generated pyscript bridge: the server re-triggers the armed `MCP_Apply` script with the platform run-last-script shortcut after a brief window focus. Every project-modifying tool routes through a snapshot → write → readback → rollback safety layer backed by a change log that is tied to the open project.

Design notes and findings are in [`docs/`](docs/).

## FAQ

**Can Claude control FL Studio?**
Yes. With this MCP server Claude reads and changes the open project: mixer levels, plugin parameters, piano-roll notes, step-sequencer drums, patterns, routing, tempo and transport.

**Which AI assistants does it work with?**
Any MCP client. `fl-studio-mcp connect` prints the ready-made entry for Claude Code, Claude Desktop, Cursor and Codex.

**Which FL Studio versions are supported?**
FL Studio 2025 and 2026. It is tested on 26.1 (Producer Edition), on macOS and Windows 11.

**Does it work on a Mac?**
Yes, and setup is one command: the server creates its own MIDI ports and FL Studio links them by itself. Windows needs the free loopMIDI tool.

**Can it load plugins, load samples or render audio?**
No. FL Studio's scripting API does not allow that. The assistant suggests plugins and presets from the ones you own, you load them, and it then configures them.

**Is it safe to use on a real project?**
Each change is logged with the value it replaced and can be rolled back with `fl_rollback_last_change`. Undo entries are tied to the project they were made in, so an old entry is never applied to another project. A dry-run mode shows what would change without changing it.

**Is it free?**
Yes. MIT licence, open source.

## License

MIT — see [LICENSE](LICENSE).

## Status & contributing

Beta. `main` is version 2 (in development); PyPI still carries 1.0.0 until 2.0.0 is released. Tested live on FL Studio 26.1 on macOS and Windows 11. Linux is untested; contributions are welcome. Issues and pull requests: [github.com/rosasynthesiz/flstudio-mcp](https://github.com/rosasynthesiz/flstudio-mcp).

<!-- mcp-name: io.github.rosasynthesiz/flstudio-mcp -->
