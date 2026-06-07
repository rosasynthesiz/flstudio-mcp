# Backlog Research

This file stores long-term research, including sister-project consolidation notes, official API expansion backlog, and experimental ideas.

## Sister Project Consolidation — geezoria/FLStudioMCP

Reference: <https://github.com/geezoria/FLStudioMCP>. The sister project is a
useful feature-discovery source, but not a design to copy wholesale. It exposes
a very broad 160+ tool surface, including TCP transport, step sequencer writes,
playlist/arrangement tools, automation recording, piano-roll transforms,
generators, voice-to-MIDI, and audio analysis. Our adoption rule is stricter:
each persistent FL mutation must fit the snapshot -> write -> readback ->
rollback contract, or it stays read-only/dry-run/manual.

### Adopt as high-priority product capabilities

These overlap strongly with real user workflows and are backed by FL scripting
APIs we have already documented or probed.

1. **Step Sequencer Pack**
   - Add grid read/write, full step-pattern write, clear, shift, and velocity
     humanization.
   - Snapshot changed grid bits and step parameters as one rollback unit.
   - This is the strongest missing composition workflow because it avoids the
     Piano Roll bridge entirely.

2. **Channel Organizer Pack**
   - Add channel rename, channel type detail, pitch, target mixer assignment,
     and "assign to free mixer track".
   - Promote the user's audio-default request only where API-backed:
     channel volume 50%, name/color/route are in scope; Normalize and Stretch
     Pro stay probe-dependent.
   - v1 shipped: details read, unassigned-channel detection, rename, explicit
     mixer-target assignment, and assign-to-free-mixer-track. Pitch write and
     Normalize/Stretch Pro remain out of scope.

3. **Pattern Management Pack**
   - Add first-class current/list/select/rename/color/length/clone/move/find
     empty tools.
   - Do not add delete/merge/split until there is a proven restore story.

4. **Playlist Track Organizer**
   - Add playlist track list/name/color/mute/solo/select.
   - Add `fl://playlist` as a resource capped like existing mixer/channel
     resources.
   - Do not claim general clip enumeration, overlap detection, clip movement,
     or clip deletion until a reliable API path exists.

5. **Effect Slot and Native EQ Pack**
   - Add effect slot read, slot mix, track-slot enable/bypass, and native mixer
     EQ read/write.
   - Support setting Low/High bands to Low Cut (High Pass) and High Cut (Low Pass)
     modes via `general.processRECEvent` (using `mixer.REC_Mixer_EQ_Type`,
     `_Freq`, and `_Q` event IDs) to allow plugin-free, CPU-friendly channel high-passing.
   - Snapshot slot mix/enabled state and every changed EQ band parameter.
   - Treat per-slot mute as live-test-required before user-facing exposure.

6. **Safety / Change History Pack**
   - Expose recent MCP changelog entries, export the changelog, and rollback by
     recent index or change id.
   - Add named grouped rollback units for organizer, routing cleanup, and bulk
     cleanup operations.
   - Optionally anchor large grouped writes with `general.saveUndo` where FL
     exposes it, without replacing MCP-level restore payloads.

7. **Project Health**
   - Build as orchestration over safe primitives, not as a second write layer.
   - Combine Mix Review, Routing Review, organizer findings, plugin/effect-slot
     state, muted/soloed tracks, duplicate names, too-hot levels, and export
     readiness into one read-only report.
   - Apply one approved fix at a time, each with its own rollback unit.

### Adopt later, with architecture changes

- **Piano Roll comfort transforms**: clear, transpose, duplicate, humanize,
  velocity ramp, delete selected/region. These are real inside Piano Roll
  scripts, but MCP readback remains the hard part. Keep them undo-backed and
  explicit about limited readback unless a reliable return channel is added.
- **High-level generators**: chord progressions, drum grooves, basslines,
  arpeggios, melodies, and DnB grooves are valuable, but should compile to our
  existing `fl_export_midi`, step sequencer, or safe Piano Roll writer instead
  of becoming many thin write tools.
- **Voice-to-MIDI**: useful, but should first ship as read-only transcription
  to note JSON/MIDI. Writing into FL must route through the safe Piano Roll
  writer and requires clear optional dependency handling.
- **Audio melody-to-Piano-Roll and sample flip workflows**: keep analysis
  read-only first; generated MIDI/notes are reviewable artifacts before any FL
  write.
- **Automation via REC events**: promising but risky. Build probes first for
  tempo, channel volume/pan, mixer volume, and plugin params; only expose tools
  where the created automation can be read back or safely undone.
- **TCP bridge / push events**: attractive for throughput and event streaming,
  but not a near-term replacement for the now-working MIDI SysEx bridge. Treat
  it as an experimental transport branch after the product tool surface is
  safer and better tested.

### Do not copy into the roadmap as user-facing tools

- Raw escape hatches such as `fl_call_raw`; they bypass reviewable safety.
- Project open/new/render as automated tools; they are UI/file-workflow heavy
  and high-risk without a stronger backup story.
- Pattern delete, playlist clip delete/place, marker delete, full clip
  enumeration, and arrangement switching unless probes prove current FL builds
  expose them reliably.
- Plugin loading/insertion; keep the current "suggest/load manually/configure
  loaded plugin" model.
- Broad UI window tools. Keep focus/window controls as infrastructure and
  diagnostics, not core product surface.
- Full FLP snapshot/restore claims. MCP snapshots restore the affected state,
  not an entire project file.

### Revised build order after consolidation

1. **Safety primitives first**
   - Snapshot scopes for channel name/type/pitch/target, step grid/params,
     pattern name/color/length/current selection, playlist track state, effect
     slots, native EQ, time signature, and undo metadata.
   - Changelog browsing and rollback by id/index.

2. **API-backed quick wins**
   - Step Sequencer Pack.
   - Channel Organizer Pack.
   - Pattern Management Pack.
   - Playlist Track Organizer.
   - Effect Slot and Native EQ Pack.

3. **Product-level workflows**
   - Project Organizer MVP.
   - Routing Review 2.0.
   - Project Health / Preflight Report.
   - Export readiness report.

4. **Creative intelligence**
   - Generator pack that emits reviewable notes/MIDI/step patterns.
   - Voice/audio transcription as optional read-only analysis first.
   - Safe write path only after generated material is inspectable and
     rollback-backed.

5. **Experimental infrastructure**
   - Push events and optional TCP transport.
   - Piano Roll readback/return-channel research.
   - REC automation write/readback probes.

## Official API Expansion Backlog

These items come from the official MIDI Controller, Piano Roll, Edison/Audio
Editor, and Slicex scripting surfaces. They are prioritized for product value
and compatibility with the safety contract.

### Priority 1 — rollback-backed production primitives

1. **Effect Slot + Native EQ Pack**
   - Add user-facing tools for mixer effect slot readback, slot mix, slot
     enabled/bypass state where verified, and native mixer EQ band read/write.
   - Snapshot every changed slot and EQ band parameter before writes.
   - Read back slot/EQ state after every mutation and log a restore payload.
   - Treat per-slot bypass/mute and EQ type changes as live-smoke-required
     before exposing them broadly.

2. **Step Parameter Pack**
   - Extend the Step Sequencer Pack beyond grid bits to step velocity, pan,
     pitch, release, and modulation parameters where the MIDI Controller API
     exposes stable read/write calls.
   - Snapshot the affected channel's step grid and changed step parameters as
     one named rollback unit for full-pattern operations.
   - Add read-only inspection first for any step parameter whose value range or
     restore behavior differs across FL Studio versions.

3. **Pattern Organizer Completion**
   - Add rollback-backed tools for pattern color, pattern length, current
     pattern selection snapshot/restore, find-empty-pattern, and clone/move if
     readback proves stable.
   - Keep pattern delete, merge, split, and destructive cleanup out of scope
     until restore data is complete.
   - Use one grouped rollback unit for multi-pattern organizer actions.

4. **Project Health / Export Readiness Report**
   - Build a read-only aggregate report over existing safe primitives:
     routing, mixer peaks, plugin parameter visibility, muted/solo states,
     duplicate or empty names, unassigned channels, suspicious pattern lengths,
     and playlist organization.
   - Produce fix plans as dry-run recommendations first.
   - Apply fixes only one approved rollback-backed operation at a time.

### Priority 2 — Piano Roll productivity after return-channel research

1. **Piano Roll Return-Channel Probe**
   - Research whether generated Piano Roll scripts can return structured note
     data to the MCP server through a reliable file, clipboard, bridge, or
     controller-mediated path.
   - Keep `fl_piano_get_notes` explicitly API-limited until this probe is
     proven and tested.
   - Document failure modes and FL version assumptions before enabling any
     readback-dependent tool.

2. **Piano Roll Comfort Transforms**
   - Add selected/all scope transforms for duplicate, humanize timing,
     humanize velocity, velocity ramp, gate/length, legato, overlap trim,
     strum, arpeggiate, mute/unmute, note color, slide, porta, and
     snap-to-scale.
   - Every transform must use the Piano Roll undo-backed safety path and return
     an explicit readback limitation until the return-channel probe is solved.
   - Avoid destructive delete-selected/delete-region tools unless the selected
     note set can be captured and restored.

3. **Piano Roll Marker Pack**
   - Add scale, section, time-signature, and cue marker helpers where the Piano
     Roll scripting API can write them predictably.
   - Keep marker edits undo-backed and grouped with related note transforms
     when they are part of one musical operation.
   - Prefer generated reviewable script payloads over broad opaque commands.

Tracking the full scope — eight phases shipping the MCP server, the scale/mode
composition tools, the SKILL.md, evals, and plugin marketplaces
bundle.

Each phase is shippable on its own. Each ends with `python scripts/test_bridge.py`
still passing.
