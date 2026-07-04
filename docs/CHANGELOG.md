# Changelog

## Unreleased -- tool-surface expansion (fl_* tools)

New tools (no changes to existing tool signatures). Each is read-only or routes
writes through the existing snapshot -> write -> readback -> rollback safety
layer. The FL controller gains matching thin handlers (build marker `xplat-v15`).

- **Capabilities**: `fl_capabilities` + `fl://capabilities` resource -- reports
  what is automated vs. manual per OS/transport, and the FL API limits.
- **Plugin / generic VST control**:
  - `fl_plugin_get_params` / `fl_plugin_set_param` now accept `slot=-1` to
    address a channel-rack **generator** (Serum/Vital/etc.), not just mixer
    effects.
  - `fl_plugin_find_params` -- search a plugin's parameters by name (for big
    synths with hundreds of params).
  - `fl_plugin_set_params` -- set several params as ONE reversible change.
  - `fl_plugin_overview` -- role-grouped params + a controllability tier
    (full / partial / opaque).
  - `fl_plugin_calibrate_param` -- sweep a param and learn its real-unit curve
    (cached under `~/.flstudio-mcp/`); snapshots + restores the param.
  - `fl_plugin_set_param_value` -- set a param to a musical target (e.g.
    "cutoff = 2 kHz"); degrades to normalised control when a plugin is opaque.
  - `fl_plugin_intent` -- semantic moves (brighter/darker/more_attack/wider/...)
    mapped to the right knob via role detection.
- **Patterns**: `fl_pattern_list` / `fl_pattern_select` / `fl_pattern_rename` /
  `fl_pattern_get_length`.
- **Playlist**: `fl_playlist_tracks` + mute/solo/rename/color (reversible).
- **Arrangement (read)**: `fl_arrangement_selection`, `fl_arrangement_markers`.
- **Channel step grid**: `fl_channel_get_grid`, `fl_channel_set_step`,
  `fl_channel_set_steps`, `fl_channel_clear_grid` (reversible).
- **Plugin loading**: `fl_load_plugin` is capability-aware -- FL's API can't
  instantiate plugins, so it explains why + the reliable alternatives rather
  than performing fragile UI automation.

Windows behavior and the existing tool contract are unchanged.

## v0.2.0 -- MIDI SysEx transport

**Breaking change**: the transport between the MCP server and the FL
controller script switched from a file-based JSON queue to MIDI SysEx.
Protocol version bumped 1 -> 2. v0.1 clients and v0.2 controllers (or vice
versa) refuse to talk.

### Why

FL Studio's controller-script Python sandbox blocks every form of file
write. Confirmed on FL 24+ with MIDI scripting version 40 / embedded Python
3.12.1:

- `open("...", "w").write("...")` ->
  `SystemError: <class '_io.FileIO'> returned NULL without setting an exception`
- `os.open(..., O_WRONLY|O_CREAT|O_TRUNC)` ->
  `TypeError: bad argument type for built-in operation`
- `os.makedirs(...)` ->
  `mkdir returned NULL without setting an exception`

A normal OS process writing to the same directory succeeds, so it is the
controller-script sandbox specifically, not OS permissions. Piano Roll
`.pyscript`s run in a different sandbox and do allow file I/O, but those
only execute on explicit user trigger -- they're not suitable for the
heartbeat / always-on loop the server depends on.

So all transport moved to MIDI SysEx, which is allowed in controller
scripts via `device.midiOutSysex` (out) and `OnMidiMsg` (in).

### What changed

- `src/fl_studio_mcp/protocol.py`: new SysEx wire format, manufacturer ID
  `0x7D`, magic `"MCP"`, base64-JSON payload. Default port names
  `FLStudioMCP RX` (server -> FL) and `FLStudioMCP TX` (FL -> server).
- `src/fl_studio_mcp/connection.py`: rewritten on `mido` + `python-rtmidi`.
  Background callback dispatches incoming SysEx, blocks the caller on a
  `threading.Event` keyed by request id. Heartbeat detected via incoming
  `DIR_HEARTBEAT` messages from FL.
- `fl_controller/FLStudioMCP/device_FLStudioMCP.py`: rewritten with
  `OnMidiMsg` dispatch and `device.midiOutSysex` response, plus a 500 ms
  heartbeat in `OnIdle`. No more file I/O.
- `pyproject.toml`: added `mido>=1.3.2` and `python-rtmidi>=1.5.8`.
- `server.py`: new `--list-ports` flag for debugging port mismatches.
- `fl_ping`: reports `port_to_fl` and `port_from_fl` instead of a bridge
  root.

### What did NOT change

- The 10 Phase 0 tool names and signatures
  (`fl_ping`, `fl_get_tempo`, `fl_set_tempo`, `fl_play`, `fl_stop`,
  `fl_toggle_play`, `fl_record`, `fl_get_play_state`,
  `fl_get_song_position`, `fl_set_song_position`).
- The command-name catalogue (`CMD_PING`, `CMD_GET_TEMPO`, etc).
- The tool-side error model (`FLNotRunning`, `FLTimeout`,
  `FLCommandFailed`). A new `FLPortMissing` was added for the MIDI-port
  setup failure mode.

### Setup deltas vs v0.1

You now need two virtual MIDI ports created up front:

- Windows: install loopMIDI, create `FLStudioMCP RX` and `FLStudioMCP TX`.
- macOS: add two ports of those names under IAC Driver in Audio MIDI Setup.

Then in FL: Options -> MIDI Settings, enable both ports, set their Port
numbers to the same value (the controller script uses the matching number
to route its responses to the correct output).

## v0.1.0 -- File-queue bridge (withdrawn)

Initial release. Withdrawn because the file-queue design did not work on
FL builds that sandbox controller-script file I/O (which appears to be
every recent FL build, not an edge case).
