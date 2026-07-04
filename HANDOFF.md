# HANDOFF — Windows hardening pass

This branch (`windows-hardening`) is a starting point for an agent/human to
run a **Windows hardening + regression pass** on flstudio-mcp on a real Windows
machine. It is intentionally near-empty so the Windows work starts from a clean,
known base.

## Why this exists

The macOS hardening was done in an extended session on macOS (see the local
`macos-parity-hardening` branch and fork PR `dabertram#1`). Upstream maintainer
feedback (issue #2) asked for two things before cross-platform follow-ups merge:

1. **Preserve existing Windows behavior** — this is the top priority. Base macOS
   support already landed upstream via PR #4 without changing the Windows path or
   the MCP tool contract.
2. **A live Windows regression pass** — loopMIDI, Fruity Parametric EQ 2 apply,
   and reference-match, since that path has not been re-verified after the
   cross-platform work.

## First steps for the next session

1. **Sync with upstream first.** This branch was cut from a local `main` that
   predates the merged macOS PRs. Before doing anything:
   ```bat
   git remote add upstream https://github.com/rosasynthesiz/flstudio-mcp
   git fetch upstream
   git rebase upstream/main        :: or recreate this branch off upstream/main
   ```
   Upstream `main` now contains: base macOS support (#4) and the CI mock-bridge
   smoke test (#5).

2. **Set up the Windows dev environment** (see README "Windows" setup):
   ```bat
   python -m venv .venv & .venv\Scripts\activate
   pip install -e ".[dev]"
   scripts\install_windows.bat
   ```
   Create the two **loopMIDI** ports `FLStudioMCP RX` / `FLStudioMCP TX`, wire
   them in FL (Options > MIDI Settings, matching Port numbers), and confirm
   `[FLStudioMCP] Ready` in FL's Script output.

3. **Run the offline suite + lint** (should already pass):
   ```bat
   pytest -q
   ruff check src tests
   ```

## The Windows regression checklist (the core ask)

Run these on a live FL Studio (record FL edition + build):

- [ ] `fl-studio-mcp-daemon` starts; `fl_ping` succeeds; heartbeat fresh.
- [ ] Transport: play / stop / tempo get+set (verify exact BPM) / song position.
- [ ] Mixer: list tracks, get track, set volume/pan/mute/solo with readback.
- [ ] Channels: list + set volume/pan/mute/solo.
- [ ] **Fruity Parametric EQ 2 apply** — `fl_apply_eq_intent` on a track with an
      EQ 2; confirm the band moves match the calibrated curve.
- [ ] **Reference-match** — run the reference-match flow; confirm sane output.
- [ ] Mix Doctor: diagnose while playing (levels_valid true) and stopped
      (partial-diagnosis note).
- [ ] Note bridge: arm `MCP_Apply` once, write notes, confirm they land
      (Ctrl+Alt+Y focus path — the Windows-specific `ctypes.windll` focus).
- [ ] Safety: every write is followed by `fl_rollback_last_change` and verified
      to restore the prior state.

Capture pass/fail + FL build in the PR description.

## Windows-specific things to harden / watch

- **Focus/trigger path**: `src/fl_studio_mcp/_trigger_win32.py` (AttachThreadInput
  + synthetic Alt + Ctrl+Alt+Y). Verify it still steals focus reliably and the
  note bridge lands. This is the behavior the maintainer most wants preserved.
- **loopMIDI**: port name matching, duplicate-port pitfalls (see docs/FIX_REPORT.md
  — the historical "both ports enabled as outputs on the same Port number" bug).
- **MSIX/Store Claude Desktop**: the daemon (`FLSTUDIO_MCP_TRANSPORT=tcp`) exists
  precisely because that build launches the server without MIDI access — verify.
- **Paths**: FL user-data under `%USERPROFILE%\Documents\Image-Line\FL Studio` —
  confirm plugin-db / preset / piano-roll-scripts discovery resolves.
- **`pygetwindow`** is now a Windows-only dependency — confirm it installs and
  the focus helper works, and that macOS/Linux don't require it.

## Related work to cherry-pick / compare (from the macOS session)

The following are Windows-safe by construction (gated off on win32) and may be
proposed as focused follow-ups once the Windows regression is green:

- `paths.py` FL-data-dir discovery (branch `macos/paths-discovery`).
- Virtual CoreMIDI/ALSA opt-in `FLSTUDIO_MCP_VIRTUAL_PORTS` (branch
  `macos/virtual-ports`) — no effect on Windows (MME can't create virtual ports;
  auto-off on win32).
- New `fl_*` tools: capabilities, pattern/playlist/channel-grid, plugin
  generator/search/batch, VST calibration/intent, loader (branch `feat/fl-tools`)
  — tool-surface expansion; review with a changelog entry, run the Windows
  regression on these too since they share the bridge.

See the session plan/notes for the full rationale. Keep the controller THIN and
every write reversible (AGENTS.md).
