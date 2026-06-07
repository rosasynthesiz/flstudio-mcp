# Contributing to flstudio-mcp

Thanks for your interest in improving flstudio-mcp. This project is a Model
Context Protocol server that lets an AI assistant drive FL Studio 2025 — mixer, plugins,
piano roll, routing, and project — through calibrated, safety-checked tools.
Contributions of all kinds are welcome: bug reports, fixes, new tools, docs,
and platform support.

This repository is the maintained `thunderdew-dawn/flstudio-mcp` fork of
`rosasynthesiz/flstudio-mcp`. The package and command names remain stable for
compatibility, but contributions should follow this fork's rollback-first
safety layer, API-evidence discipline, and roadmap in `ROADMAP.md`.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it to understand the expectations for behavior in our community.

## Ways to contribute

- **Report a bug** — open an issue with steps to reproduce, your FL Studio build, and the relevant Script output / server log.
- **Request or add a tool** — propose a new capability (a mixing intent, an analysis tool, etc.) in an issue first, so we can agree on the shape before you build it.
- **Improve docs** — README, setup, troubleshooting, and the design notes in docs/ are all fair game.
- **Port to Linux** — the server is cross-platform Python; the friction is the virtual MIDI ports and the controller-script paths. This is the most valuable open contribution. Open an issue before starting so we can coordinate.

## Before you start

Please read the **Limitations** section of the README. Several things are *not* bugs — they are constraints of FL Studio's scripting API:

- Plugins, audio files, and rendering are UI-only. The API cannot load a plugin or render audio, so plugin/preset tools suggest; the user loads.
- Note writing is armed once per session via MCP_Apply in the piano roll.
- Micro-tonal scales are rounded to the nearest semitone (12-tone MIDI).

A PR that tries to "fix" one of these by working around the sandbox will likely be declined unless it's genuinely reliable across FL builds.

## Development setup

You'll need the same environment as a user, plus an editable install:

- Windows 10/11 or macOS 12+, FL Studio 2025+, Python 3.12
- loopMIDI on Windows or the IAC Driver on macOS, with two ports named exactly
  FLStudioMCP RX and FLStudioMCP TX
- An MCP client (like Claude Desktop or Cursor) for end-to-end testing

Install steps: clone the repo, cd into it, run `scripts\install_windows.bat` or
`./scripts/install_macos.sh`, then `pip install -e ".[audio]"` if you'll touch
the audio analysis code. Wire the MIDI ports in FL (Options > MIDI Settings),
confirm `[FLStudioMCP] Ready` in FL's Script output, start the bridge with
`fl-studio-mcp-daemon`, then verify the link by asking your AI assistant to call
`fl_transport(action="ping")`.

## Project layout

- src/fl_studio_mcp/ — the MCP server: tool definitions, calibration, diagnosis, planning. Almost all logic lives here.
- fl_controller/FLStudioMCP/ — the thin controller script that runs inside FL. Keep it cheap: return raw data, do no judgement here.
- fl_pyscripts/ — the note-bridge pyscript (MCP_Apply).
- scripts/ — installer and tooling.
- skills/ — the production skill packaged with the server.
- docs/ — design notes and findings.

The guiding split: the controller returns cheap raw data; all judgement (diagnosis, calibration, planning) happens server-side. New tools should follow this — don't push decision-making into the controller.

## Safety layer (important)

Every tool that modifies the project must route through the snapshot → write → readback → rollback safety layer and the persisted change log. Tools should be reversible and should show the planned change before applying it. A new write-tool that bypasses this won't be merged. Read-only tools (state, levels, analysis) don't need it.

## Anti-Vibe Coding Audits (important)

To enforce coding discipline and prevent LLM "vibe coding" (undisciplined trial-and-error, unverified knowledge, sandbox violations, or lazy placeholder code), this repository enforces strict static checks. 

You can run the audit manually at any time:
```bash
.venv/bin/python scripts/audit_anti_vibe.py
```

It is highly recommended to install the pre-commit hook so your commits are blocked if they violate these rules:
```bash
.venv/bin/python scripts/install_precommit_anti_vibe.py
```

The audit blocks:
- **Sandbox violations**: Importing `os` or calling `open()` inside the FL Studio controller script.
- **Knowledgebase gaps**: Missing required JSON fields in `knowledgebase/` entries according to `AGENTS.md`.
- **Lazy coding patterns**: Keywords such as `TODO: fix later`, `HACK`, `print("here")`, `stub implementation`, etc. in source code.

## Pull requests

1. Open an issue first for anything beyond a small fix, so the approach can be agreed on.
2. Branch from main; keep PRs focused on one change.
3. Test on a real FL Studio session — note in the PR what you verified and on which FL build. Hardware-tested changes are strongly preferred, since much of this can't be unit-tested without FL.
4. Match the existing style: clear tool names, parameters documented, errors returned as structured results rather than raised blindly.
5. Update the README / docs if you add or change a tool or its behavior.
6. Write clear commit messages describing what changed and why.

## Reporting bugs

A good report includes:

- FL Studio edition and build (e.g. Producer Edition v25.2.5 [build 5319])
- What you asked the AI assistant to do, and what happened vs. what you expected
- Relevant FL Script output and server/daemon logs
- Whether `fl_transport(action="ping")` succeeds

## Code of conduct

Be respectful and constructive. This is a small project — assume good faith, keep discussion technical, and help newcomers get set up.

## License

By contributing, you agree that your contributions are licensed under the project's MIT License (see LICENSE).
