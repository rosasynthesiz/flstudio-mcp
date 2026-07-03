# HANDBACK — Windows hardening pass (results)

This is the completion report for the `windows-hardening` pass started in
`HANDOFF.md`. Hand this file to the next machine/session to consolidate.

**Bottom line: the full HANDOFF checklist passed on a live FL Studio. Windows
behavior is preserved after the macOS merge (PR #4). No source changes were
needed — this was a verification pass.**

## Environment used

- **FL Studio**: 2025 Producer Edition **v25.1 build 4868** (Windows 11)
- **Python**: 3.11.3 in `.venv`
- **Transport**: `tcp` (daemon `fl-studio-mcp-daemon` 0.3.0 on 127.0.0.1:9787)
- **Virtual MIDI**: loopMIDI ports `FLStudioMCP RX 1` / `FLStudioMCP TX 1`
- **Branch**: `windows-hardening`, rebased onto `upstream/main` @ `ba94a6d`
  (macOS PR #4) with the HANDOFF commit on top.

## Regression results — all green

| Check | Result | Notes |
|---|---|---|
| Daemon start / `fl_ping` / fresh heartbeat | ✅ | heartbeat age ~0.2–0.5 s |
| Transport: play / stop / tempo get+set / toggle / song-pos | ✅ | exact BPM verified |
| Mixer: list / get / volume / pan / mute / solo + readback | ✅ | 18 tracks (Master + Insert 1–17) |
| Channels: list / volume / pan / mute + readback | ✅ | |
| Track coloring + rollback | ✅ | note: tool arg is `tracks` (list), not `track` |
| Dry-run (`fl_set_dry_run`) — plan only, no write | ✅ | |
| **Fruity Parametric EQ 2 apply** + rollback | ✅ | `remove_mud@0.5` → Band 1 Peaking / 250 Hz / −3.0 dB / 40% (matches calibrated curve) |
| **Reference-match** | ✅ | audio deps present; reference analyzed (8.0 s, RMS −3.1 dB, peak +2.4 dB); honest output on empty mix |
| Mix Doctor: playing vs stopped | ✅ | `levels_valid=True` playing; partial-diagnosis note when stopped |
| Windows focus/trigger path (`force_focus`) | ✅ | returned foreground on live FL window |
| **Note bridge** (write → notes land) | ✅ | 4-note melody C5→E5→G5→C6, mode=replace; **user visually confirmed notes appeared in piano roll** |
| Safety: rollback after every write | ✅ | changelog at `~/.flstudio-mcp/changelog.jsonl` |
| `record` | ⚠ expected | pops FL's record-mode modal that blocks the script reply — **FL behavior, not a bug** |

## ⚠ Windows preliminary setup is heavier than macOS

The biggest practical takeaway: **getting to a live bridge on Windows takes
noticeably more manual GUI steps than macOS did.** Budget extra time on the
next machine. In rough order:

1. **loopMIDI must be installed separately** (TobiasErichsen.loopMIDI). The
   `winget install` needs **UAC/admin approval** — it will block on a consent
   prompt. macOS uses the OS's built-in IAC/CoreMIDI virtual ports, so there's
   no third-party install there.
2. **Two virtual ports created by hand** in loopMIDI: `FLStudioMCP RX` and
   `FLStudioMCP TX`. (They came out as `... RX 1` / `... TX 1` — the substring
   matcher handles the numeric suffix fine.)
3. **FL MIDI Settings wiring is fiddly and easy to get wrong**:
   - RX port → set as **input**, Controller type **FLStudioMCP**, **Port 42**.
   - TX port → set as **output**, **Port 42**.
   - **Disable the RX port as an output** (the historical "both ports enabled as
     outputs on the same Port number" bug — see `docs/FIX_REPORT.md`).
   - FL's Output list has **no enable toggle** — it's controlled purely by the
     Port-number field, which is unintuitive.
4. **PowerShell execution policy blocks `.venv\Scripts\activate`.** Call the
   interpreter directly: `.venv\Scripts\python.exe -m ...`. (macOS `source
   .venv/bin/activate` just works.)
5. **Note bridge requires arming `MCP_Apply` once** from the **Piano roll's own
   menu** (top-left of the piano-roll window, F7) under the **MCP** category →
   "MCP Apply". This is easy to miss — it is *not* under FL's main Tools menu.
6. **MSIX/Store Claude Desktop** launches the server without MIDI access, which
   is exactly why the TCP daemon (`FLSTUDIO_MCP_TRANSPORT=tcp`) exists. Plan to
   run the daemon separately on Windows.

By contrast, on macOS the virtual ports are OS-native, no admin install is
needed, and venv activation is frictionless — so the macOS README's "setup"
section understates what a Windows user faces. **Recommend expanding the
Windows setup docs** with the port-wiring specifics above.

## Doc/code discrepancies noticed (for follow-up, not fixed here)

- HANDOFF referenced `src/fl_studio_mcp/_trigger_win32.py`; the actual file is
  [src/fl_studio_mcp/pyscript_trigger.py](src/fl_studio_mcp/pyscript_trigger.py)
  (Windows path gated on `sys.platform == "win32"`: `AttachThreadInput` +
  synthetic Alt + Ctrl+Alt+Y). Verified working.
- HANDOFF's offline suite says `pytest -q` / `ruff check src tests`, but **there
  is no `tests/` directory** on this branch — PR #5 (CI mock-bridge smoke test)
  was **not** merged into `upstream/main` (only PR #4 was). Offline verification
  was done via import/build checks + tool/resource enumeration (67 tools, 6
  resources) instead.
- `ruff check src` reports **302 pre-existing cosmetic warnings** (E501/UP031).
  Out of scope for this pass; flag as a separate cleanup PR if desired.

## Branch / repo state

- `origin` = `git@github.com:dabertram/flstudio-mcp.git` (fork)
- `upstream` = `git@github.com:rosasynthesiz/flstudio-mcp.git`
- `windows-hardening` = `upstream/main` (`ba94a6d`) + HANDOFF commit + this
  HANDBACK commit. **No source changes** — verification only.
- Temp regression scripts used during the pass were deleted; working tree clean.

## What's left / next-session candidates

The regression is green, so the macOS follow-ups from HANDOFF are now unblocked
for review (all Windows-safe by construction, gated off on win32):

- `paths.py` FL-data-dir discovery (branch `macos/paths-discovery`).
- Virtual CoreMIDI/ALSA opt-in `FLSTUDIO_MCP_VIRTUAL_PORTS` (branch
  `macos/virtual-ports`) — no effect on Windows.
- New `fl_*` tools (branch `feat/fl-tools`) — run the Windows regression on
  these too since they share the bridge.

Also recommended: **expand the Windows setup section of the README** with the
port-wiring detail in the section above, and consider **merging the CI
mock-bridge (PR #5)** so `pytest` has a target.
