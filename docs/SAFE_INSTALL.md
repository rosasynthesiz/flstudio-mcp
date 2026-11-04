# Safe installation, diagnostics and recovery

These scripts install from source. This draft does not publish a signed Windows
installer, notarized Mac package, PyPI upload, or release asset. Windows and Mac
native validation remain distinct from fake-folder CI.

## Install or repair

1. Open FL once to create its user Settings/Hardware folder, then close FL and
   every MCP server/daemon. Save projects yourself before closing. Python 3.10+
   is required; Windows prefers an installed Python 3.12/3.11/3.10 launcher.
2. Run `scripts/install_windows.bat` or `bash scripts/install_macos.sh` from a
   complete checkout. Pass `--settings "<absolute FL Studio/Settings>"` for a
   custom folder, or set `FL_SETTINGS`. Keep this folder and `.runtimes` in place.
   Redirected links/junctions are refused; choose the actual custom folder.
3. The default excludes optional audio packages. Set `FLMCP_EXTRAS=all` or a
   space-separated subset of `audio accurate chords` before installation if
   wanted. A requested dependency failure aborts; it does not report success.
4. Each run creates a fresh `.runtimes/<id>` virtual environment and installs a
   regular package, not an editable source link. It validates runtime imports
   before any installed controller file changes. Existing system Python,
   `.venv`, previous runtimes, MIDI configuration and client config are preserved.
5. Originals of the exact controller file, MCP_Apply and runtime selection file
   are saved under `.install-backups/<id>` with `manifest.json`. Other controller
   files are left alone. A deployment failure restores originals where possible
   and reports the backup path and any failed recovery. Incomplete staging
   runtimes are retained for inspection, not selected for use.
6. Use the printed full server command and both printed environment values in
   your MCP client: `FLSTUDIO_MCP_TRANSPORT=tcp` and `FL_SETTINGS`. Preserve other
   client entries. Windows `start_daemon.bat` reads the new runtime selection.
   On Mac, export the same FL_SETTINGS before running the printed daemon command.

An installation interrupted by power loss/process termination may need manual
recovery; caught-exception rollback is not a power-loss transaction. A leftover
`.flmcp-install.lock` must only be removed after confirming its recorded process
has stopped. Do not delete old runtimes until the new setup is verified and all
clients use the new full executable paths.

## Check the setup

Use the installed runtime's Python (`python` in `.flmcp-runtime.json`):

```
"<installed Python>" -m fl_studio_mcp.diagnostics
"<installed Python>" -m fl_studio_mcp.diagnostics --live
```

The first command checks Settings file presence and enumerates MIDI ports; it
never creates ports or sends commands. It distinguishes RX as a server output
and TX as a server input. The optional `--live` performs only get_project_state
through the loopback daemon. A missing controller token tells you the old
controller is still loaded. Reload the matching updated controller, restart the
daemon, and reconnect the client. Do not interpret file presence or an enumerated
port as successful routing inside FL.

Manually configure RX input with the FLStudioMCP controller and TX output using
the same FL port number. Run MCP_Apply once per FL session to arm note writes.
Mac hotkeys also require Accessibility permission for the sender. Diagnostics
cannot prove these manual steps or arbitrary third-party plugin compatibility.

## Undo boundaries

The controller exposes an opaque in-memory project/session generation. Every
project-load notification and controller lifecycle transition invalidates it,
including same-name and unsaved projects. Loading/error states refuse guarded
operations. Snapshot writes persist recovery *before* dispatch and carry the
token so FL checks it in the callback doing the operation. Step-grid writes
also require the same selected pattern. An older controller without identity
refuses snapshot writes until upgraded. Old history without identity is retained
but never replayed automatically.

Undo checks project identity, restores in reverse order, and independently
reads the fields owned by each restore command. Unrelated manual edits are
preserved. Group undo also verifies the combined restored fields at the end,
so a later restore cannot silently invalidate an earlier one. A refused, failed, uncertain or mismatched restore retains the
entry and returns `ok: false`; a setter echo alone never clears history. Retry
only after inspecting state. Multi-item undo can partially restore before a
later failure; it is not an atomic DAW transaction. The original recovery entry
remains available for retry. Separate clients coordinate undo-file transactions
with an OS file lock; keep just one active client while diagnosing problems.

These tokens protect project/session and grid-pattern boundaries. They do not
identify plugin replacement, channel deletion/reordering or all routing/solo
side effects within a project. Do not replay old index-based undo after such
structural edits. Transport/arrangement/piano-roll actions are not all covered
by this snapshot log; save a project copy and use disposable projects for tests.

## Recover or uninstall

Stop FL, daemon and clients first. Inspect `.install-backups/<id>/manifest.json`.
Each entry names the original absolute path and its numbered backup; `null`
means no previous file existed. Restore only the reviewed files from that
backup. A failed restoration is explicitly reported by the installer. Preserve
custom files. Select the previous server/daemon commands in the client and
restore the previous runtime manifest together with its matching controller.

For removal, remove only this integration's controller file, generated
MCP_Apply, and its client entry after backing them up. Keep other scripts,
projects, MIDI devices and plugin files. Remove unused repository runtimes
manually only after no client points to them.

## Local transport

Daemon bind and client target accept only IPv4 loopback or `localhost`. There is
no remote mode or authentication boundary between programs running as the same
local user. Never forward the port. JSON requests are bounded to 1 MiB with a
10-second idle socket timeout. This does not claim comprehensive local sandboxing.

## Open validation gates

- Exact-head Windows/macOS CI, including custom Settings paths and optional audio.
- Native FL load/reload/new/failed-load callback behavior on each supported build;
  disposable-project write/undo, project-switch refusal, pattern-switch refusal.
- Multiple native FL instances: each must have its own routed MIDI pair and daemon
  port. Cross-instance port ambiguity is not solved by installer file checks.
- Mac FL/IAC coexistence and Accessibility/hotkey testing; native ALSA integration
  remains experimental/missing, as tracked in held validation drafts #34/#35.
- Representative native/VST/AU plugin replacement and preset/layout invalidation.
- Platform signing/notarization, actual packaged installers, release approval.

API reference used for lifecycle semantics:
[Image-Line MIDI scripting](https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm)
(`OnProjectLoad`: start 0, success 100, error 101). Stub coverage proves our handling
of these events, not that every FL build emits them at every project boundary.
