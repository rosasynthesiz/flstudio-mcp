# flstudio-mcp

**Control FL Studio with any MCP-compatible LLM: AI mixing, composition, and mix diagnosis through natural language.**

![version](https://img.shields.io/badge/version-2.0.0-blue)
![status](https://img.shields.io/badge/status-stable-green)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.10+-blue)
![Windows](https://img.shields.io/badge/Windows-0078D6?style=flat&logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-000000?style=flat&logo=apple&logoColor=white)
![FL Studio](https://img.shields.io/badge/FL%20Studio-2025%2B-orange)

![The LLM assistant diagnosing and fixing a mix in FL Studio](docs/demo.gif)

*The LLM assistant diagnosing and fixing a mix in FL Studio through natural language.*

## Overview

flstudio-mcp is a Model Context Protocol (MCP) server that lets any MCP client (like Claude Desktop, ChatGPT, or Cursor) drive FL Studio 2025 directly — the mixer, plugins, piano roll, routing, and project — from plain-language requests. Ask for a mix diagnosis, a vocal chain, a chord progression in a particular scale, or a full arrangement, and the LLM assistant carries it out through FL's scripting API and a set of calibrated, safety-checked tools.

**Key upgrades in v2.0.0:**
- **Consolidated domain tools:** Dozens of single-purpose functions were folded into higher-level endpoints such as `fl_transport`, `fl_mixer`, `fl_channel`, `fl_effect`, and `fl_batch`. This reduces tool-selection noise and leaves more context for the assistant to reason about the project.
- **Agent orientation resource:** Agents should start with `fl://agent-briefing` and `fl://status` for current tool selection, safety gates, and stop rules before live FL work.
- **Knowledgebase-backed parameters:** API values, dB/Hz mappings, known limits, and safe ranges are captured in the local Knowledgebase so agents can prefer verified project evidence over guesses.
- **Rollback-first writes:** Persistent FL Studio mutations route through the safety layer: scoped snapshot, smallest practical write, readback where supported, changelog entry, and rollback path. Grouped writes are stored as named rollback units.

## High-Level Tools (New in v2.0.0)

This release focuses on rollback-first FL Studio production tooling and a strict agent workflow. The tools below are the highest-value entry points for day-to-day use.

*(For detailed usage, examples, and the full tool catalog, refer to the [User Guide (docs/USER_GUIDE.md)](docs/USER_GUIDE.md)).*

1. **Mix Review:** Scan your mix for clipping, masking, and balance issues, then apply gated, reversible fixes one at a time after approval.
2. **Project Organizer & Naming Standard Assistant:** Turn a messy project into a neatly colored, grouped, and logically routed session. Batch rename and color Step Sequencer channels and Mixer tracks.
3. **Routing Review 2.0:** Detect routing issues, unrouted channels, and automatically propose and apply optimal bus layouts.
4. **Plugin & Preset Assistant:** Get tailored vocal chains and synth patches based directly on your *actual installed* plugins (read directly from FL's plugin database and preset folders on disk).
5. **Composition & Scale Composer:** Generate chord progressions and melodies in any mode or scale directly into the piano roll, with grid quantization.
6. **Audio Clip Safe Defaults:** Inspect Audio Clips to dynamically provide safe volume defaults and free mixer tracks.
7. **Audio Analyzer:** Extract tempo, key, and convert audio melodies to MIDI effortlessly (via CREPE pitch tracking).
8. **Project Preflight & Health Overview:** Combine Mix Review, Routing Review, and Project Organizer checks into an export-readiness report.

Known FL Studio API limitation:
Deep Audio Clip parameters such as Stretch Mode, Normalize state, and some sample internals are not exposed by the FL Studio Python API. The assistant can organize and route Audio Clips, but it will not claim to set Stretch Pro or Normalize automatically (it will generate manual checklists instead).

## How it Works: 8 Production Phases

FL Studio's Python API is useful but has strict boundaries. This project combines safe controller calls, local file analysis, generated Piano Roll scripts, and a snapshot/rollback safety layer. The summary below explains what is automated and where FL Studio still requires manual action.

### Phase 1: Ideation & Composition (Notes & Audio)
- **Audio Analysis (`fl_analyze_audio`, `fl_extract_melody`)**
  - *The Limitation:* FL Studio's API cannot read or analyze audio files.
  - *How it works:* These tools read `.wav` or `.mp3` files directly from disk and analyze them with Python libraries such as CREPE when the optional accurate audio extras are installed.
- **Piano Roll & Scales (`fl_piano_roll`, `fl_scale_get`)**
  - *The Limitation:* The API does not allow external programs to arbitrarily push notes directly into the Piano Roll at runtime.
  - *How it works:* The assistant generates a temporary `MCP_Apply` script. A background daemon triggers the armed script with a keyboard shortcut (`Cmd+Opt+Y` on macOS), causing FL Studio to write the notes to the selected Piano Roll target.

### Phase 2: Arrangement & Structure
- **Patterns & Playlist (`fl_pattern`, `fl_playlist`)**
  - *The Limitation:* Direct editing, splitting, or moving of Audio/MIDI clips in the playlist is blocked by the API.
  - *How it works:* The assistant manages supported structure such as pattern creation, pattern cloning where exposed, section markers, and track metadata through unified domain tools.

### Phase 3 & 4: Diagnosis & Preparation
- **Audio Clip Safe Defaults (`fl_inspect_audio_clips`)**
  - *The Limitation:* Deep Audio Clip features like "Stretch Pro" or the "Normalize" toggle are not exposed.
  - *How it works:* The tools can apply safe Channel Rack volume limits, check for free mixer tracks, and generate manual checklists for Stretch/Normalize states that the FL API cannot verify.
- **Project Organizer (`fl_channel`, `fl_mixer`, `fl_apply_color_standard`)**
  - *Safety:* Renaming and coloring a large project uses scoped snapshots and named rollback units so supported changes can be audited and restored through the MCP safety layer.

### Phase 5: Signal Flow & Routing
- **Routing Tools (`fl_review_routing`, `fl_apply_bus_layout`, `fl_group_tracks`)**
  - *How it works:* Routing tools detect structural issues, propose bus layouts, and apply supported routing changes as named rollback units.

### Phase 6: Sound Design (The Strictest API Boundary)
- **Chain Planner & Presets (`fl_setup_chain`, `fl_suggest_preset`)**
  - *The Hard Limit:* It is technically impossible to load or insert a plugin via the FL Studio API.
  - *The workflow:* The assistant scans FL Studio plugin database and preset folders on disk, suggests chains from what it finds, and can configure parameters after the user manually loads the chosen plugin.

### Phase 7: Mixing & Dynamics
- **Mix Doctor (`fl_review_mix`, `fl_mix_watch_start`)**
  - *The Limitation:* A static "snapshot" of a song is useless because audio is dynamic.
  - *How it works:* During peak watch, the user plays the song while the tool polls live API peak meters and keeps running peak evidence for each track.
- **Knowledgebase & Intents (`fl_apply_eq_intent`)**
  - *The Problem:* AI notoriously "hallucinates" plugin parameter values (e.g. setting a knob to 150% when the limit is 100%).
  - *How it works:* Before sending supported parameter changes to FL Studio, the assistant checks requested values against Knowledgebase conversion entries such as `kb_get_conversion` and sends normalized values within verified ranges.

### Phase 8: Export, Health & Safety
- **Project Health Checks (`fl_check_project_preflight`)**
  - *How it works:* Before a manual audio render, the assistant can run combined Mix Review, Routing Review, and cleanup checks to report export-readiness risks.
- **Audio Export (`fl_export_midi`)**
  - *The Limitation:* The API cannot click "Render to WAV". 
  - *How it works:* The tools write standard `.mid` files directly to disk for arrangement exports. Audio bouncing remains manual.
- **The Safety Layer (`fl_rollback_last_change`)**
  - *The Limitation:* FL Studio's native Undo (`Ctrl+Z`) is highly unreliable for API scripts.
  - *How it works:* The MCP safety layer stores scoped snapshots and changelog entries for supported writes. Calling rollback restores the affected supported state through the MCP rollback path.

The server exposes a comprehensive suite of tools across all these phases. For a user-facing workflow overview, full tool catalog, and precise command prompts, see the **[USER_GUIDE](docs/USER_GUIDE.md)**.


## Maintained fork

This repository is a materially extended fork of
[`rosasynthesiz/flstudio-mcp`](https://github.com/rosasynthesiz/flstudio-mcp),
now maintained at
[`thunderdew-dawn/flstudio-mcp`](https://github.com/thunderdew-dawn/flstudio-mcp).
The project keeps the `fl-studio-mcp` package and command names for
compatibility, while the fork's engineering direction is now explicit:
rollback-first FL Studio production tooling, documented API-evidence handling,
live-probe discipline for build-dependent behavior, macOS support, CI safety
audits, prompt evals, and a committed agent workflow guide.

See [`NOTICE.md`](NOTICE.md) for provenance and attribution.

## Quickstart

```bat
scripts\install_windows.bat        :: Windows: controller + server + note bridge
fl-studio-mcp-daemon               :: start the bridge, keep it running
```

```bash
./scripts/install_macos.sh         # macOS: controller + server + note bridge
.venv/bin/fl-studio-mcp-daemon     # start the bridge, keep it running
```

Wire the two loopMIDI ports in FL (Options > MIDI Settings), arm `MCP_Apply` once in the piano roll, then ask the LLM assistant in plain language:

> "Scan my mix and tell me what's wrong." — "Set up a vocal chain from my plugins." — "Export this arrangement to MIDI."

Full setup is below.

## What sets it apart

flstudio-mcp is built as a mixing and production assistant, not only a note sender. It diagnoses and repairs a whole mix, makes decisions from real measured levels rather than guesswork, and is aware of your actual plugin and preset library when it makes suggestions. Every change that touches the project is shown before it is applied, logged, and reversible.

## Limitations

These are properties of FL Studio's scripting API, stated plainly:

- **Plugins, audio files, and rendering are UI-only.** FL's API cannot load a plugin, load an audio file, or render audio. The plugin and preset tools therefore *suggest* — you load the chosen plugin or preset, and the LLM assistant then configures it. Audio export is done manually (File > Export); the LLM assistant can analyze the rendered file afterward.
- **Note writing is armed once per session.** A generated pyscript writes notes into the piano roll; FL exposes no API to run a pyscript, so you run "MCP_Apply" once from the piano roll's scripting menu at the start of a session.
- **Micro-tonal and gamaka-heavy music is approximated.** Scales with intervals smaller than a semitone (e.g. Arabic maqam) are rounded to the nearest semitone, and traditions built on gamaka/ornamentation (e.g. Carnatic) get the *scale framework* — the correct swaras and intervals — not gamaka or micro-tonal rendering. That's a limit of 12-tone MIDI, not of the tools.

## Requirements

- **Windows 10/11** (tested on Windows 11) or **macOS 12+** (Intel & Apple Silicon)
- **Last live-verified FL Studio build:** Producer Edition v25.2.5, build
  5055, with controller build marker `channels-v38`. The current source
  controller marker is `channels-v39` and should be live-smoked after reload.
  FL Studio 20.7+ has the required MIDI scripting foundation, but individual
  API behavior can be build-dependent; use `fl_transport(action="ping")` and
  the live smoke/probe scripts before relying on a new FL build for writes.
- **Claude Desktop** or **ChatGPT Desktop** (or any MCP client)
- **Python 3.10+**
- Virtual MIDI ports:
  - **loopMIDI** on Windows ([download](https://www.tobias-erichsen.de/software/loopmidi.html))
  - **IAC Driver** (built into macOS)
- Optional: **ffmpeg** on PATH (for MP3 analysis)

## Setup

### 1. Configure MIDI Ports

* **Windows**: Create two virtual MIDI ports in loopMIDI, named exactly `FLStudioMCP RX` and `FLStudioMCP TX`.
* **macOS**:
  1. Open the **Audio MIDI Setup** app.
  2. Choose **Window > Show MIDI Studio** (or press `Cmd+8`).
  3. Double-click the **IAC Driver** icon.
  4. Tick the **Device is online** checkbox.
  5. Under **Ports** (or **Buses**), add/rename two ports to exactly:
     * `FLStudioMCP RX`
     * `FLStudioMCP TX`
  6. Click **Apply**.

### 2. Install the Controller Script & Server

#### Windows:
```bat
git clone https://github.com/thunderdew-dawn/flstudio-mcp
cd flstudio-mcp
scripts\install_windows.bat
```

#### macOS:
```bash
git clone https://github.com/thunderdew-dawn/flstudio-mcp
cd flstudio-mcp
chmod +x scripts/install_macos.sh
./scripts/install_macos.sh
```
This script will copy the controller script, create a virtual environment (`.venv`), install the server inside it, and verify that the IAC Driver ports are online. It also pre-seeds the note-bridge script (`MCP_Apply.pyscript`) inside your FL Studio user data directory.

> [!IMPORTANT]
> **macOS Accessibility Permissions**: Since the note-writing tool simulates keyboard shortcuts (`Cmd+Opt+Y`) via `pyautogui` to trigger script runs in FL Studio, the application executing the MCP server (e.g., your terminal, iTerm, Warp, or your MCP client app like Claude Desktop/ChatGPT) must be granted Accessibility permissions. Go to **System Settings > Privacy & Security > Accessibility** and ensure the app you are running is enabled.

For optional audio/melody analysis extras:
* Windows: `pip install -e ".[audio,audio-accurate]"`
* macOS: `.venv/bin/pip install -e ".[audio,audio-accurate]"`

### 3. Configure FL Studio (All Platforms)

1. Open FL Studio.
2. Go to **Options > MIDI Settings**:
   * **Input list**: Click `FLStudioMCP RX`, tick **Enable**, set **Controller type** to `FLStudioMCP`, and set **Port** to `42`.
   * **Output list**: Click `FLStudioMCP TX`, tick **Enable**, and set **Port** to `42` (MUST match the input port).
3. Go to **View > Script output**. It should show `[FLStudioMCP] Ready`.

### 4. Connect to your MCP Client

#### Option A: Claude Desktop, Cursor, or other stdio clients
1. Start the MIDI bridge daemon (recommended so MIDI ports are held by a stable background process):
   * Windows: Run `fl-studio-mcp-daemon`
   * macOS: Run `.venv/bin/fl-studio-mcp-daemon`
2. Configure your client (e.g., Claude Desktop). Add this to your configuration file (Windows: `%APPDATA%\Claude\claude_desktop_config.json`, macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):
   ```json
   {
     "mcpServers": {
       "fl-studio": {
         "command": "/path/to/flstudio-mcp/.venv/bin/fl-studio-mcp",
         "env": {
           "FLSTUDIO_MCP_TRANSPORT": "tcp"
         }
       }
     }
   }
   ```
   *(Note: On Windows, use `fl-studio-mcp` for the command instead of the `.venv` path if installed globally.)*

#### Option B: ChatGPT Desktop (SSE)
ChatGPT Desktop does not support local stdio subprocesses and requires a remote/SSE connection:
1. Start the MIDI bridge daemon in a terminal:
   * Windows: `fl-studio-mcp-daemon`
   * macOS: `.venv/bin/fl-studio-mcp-daemon`
2. Start the MCP server with the SSE transport in another terminal:
   * Windows: `set FLSTUDIO_MCP_TRANSPORT=tcp && fl-studio-mcp --sse --port 8080`
   * macOS: `export FLSTUDIO_MCP_TRANSPORT=tcp && .venv/bin/fl-studio-mcp --sse --port 8080`
3. Enable Developer Mode in ChatGPT Desktop (Settings > Developer).
4. Go to **Settings > Developer > MCP**, click **Add New Server**:
   * **Name**: `FL Studio`
   * **Type**: `sse`
   * **URL**: `http://localhost:8080/sse`
   * Click **Save**.

### 5. Arm the Note Bridge (Per Session)

Open the FL Studio Piano Roll, click the arrow menu (top-left), and run **MCP_Apply** once from the **File > Script** menu. This arms the note bridge for composition tools.

Verify the connection by asking your AI assistant to run
`fl_transport(action="ping")`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| loopMIDI ports not found / not detected | The two ports must be named **exactly** `FLStudioMCP RX` and `FLStudioMCP TX`. Recreate them in loopMIDI and re-run the installer. |
| No `[FLStudioMCP] Ready` in FL's Script output | The controller isn't registered: set the `FLStudioMCP RX` input's **Controller type** to **FLStudioMCP** in MIDI Settings, confirm `device_FLStudioMCP.py` is in `Settings\Hardware\FLStudioMCP\`, then fully restart FL Studio. |
| The LLM assistant can't reach FL / transport ping fails | Make sure the daemon is running (`fl-studio-mcp-daemon`); check the transport matches (`FLSTUDIO_MCP_TRANSPORT=tcp` uses the daemon, unset uses direct MIDI); restart your MCP client after editing its config. |
| Note-writing does nothing | Run `MCP_Apply` once from the piano roll's scripting menu this session — it arms the note bridge. |
| Audio tools error or are unavailable | Install the optional extras: `pip install -e ".[audio]"` (or `".[audio,audio-accurate]"`). |

## Usage examples

Plain-language prompts:

- "Scan my mix and tell me what's wrong."
- "Set up a vocal chain on the lead vocal using my plugins."
- "Suggest a vintage bass preset from my Serum library."
- "Compose an 8-bar melody in D Dorian and write it to the selected channel."
- "Export this arrangement to a MIDI file."
- "What tempo and key is this track?" (on an audio file)

For examples by module, assistant, and diagnostic check, see the
[`User Guide`](docs/USER_GUIDE.md).

## Architecture

A thin controller script runs inside FL Studio and returns only cheap, raw data; all judgement — diagnosis, calibration, planning — happens server-side. A standalone daemon owns the MIDI port so the server works regardless of how the MCP client is launched. Note authoring uses a generated pyscript bridge: the daemon re-triggers the armed `MCP_Apply` script with a keystroke (via pyautogui) after a brief window force-focus. Every project-modifying tool routes through a snapshot → write → readback → rollback safety layer backed by a persisted change log.

Design notes and findings are in [`docs/`](docs/).

## License

MIT — see [LICENSE](LICENSE).

## Status & contributing

Stable — the public 2.0.0 release. Fully compatible with Windows and macOS.
Issues and pull requests:
[github.com/thunderdew-dawn/flstudio-mcp](https://github.com/thunderdew-dawn/flstudio-mcp).

<!-- mcp-name: io.github.thunderdew-dawn/flstudio-mcp -->
