# FL Studio MCP (Claude plugin)

Control FL Studio from Claude. The plugin starts a local MCP server with 98 tools: diagnose a mix, adjust mixer levels and plugin parameters, write drum patterns and piano roll notes, set tempo and arrange patterns. Every change is logged and can be rolled back. It runs on your own computer and talks to FL Studio over virtual MIDI; it makes no calls to the internet.

## Requirements

- FL Studio 2025 or newer, with the one-time setup done (controller script and MIDI ports). Steps are in the project README: https://github.com/rosasynthesiz/flstudio-mcp#setup
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed. See uv's own install page for your system.
- Python 3.11 or 3.12 already installed. The server is launched with `--no-python-downloads`, so uv will not fetch Python for you, and the pinned MIDI package ships wheels for these versions only.
- macOS (Apple silicon or Intel) or Windows 64-bit. On macOS, note writing needs Accessibility permission for the app that runs Claude.

## Install

In Claude Code:

```
/plugin marketplace add rosasynthesiz/flstudio-mcp
/plugin install rosa-fl-studio@flstudio-mcp
```

Or in one line from your terminal:

```
claude plugin install rosa-fl-studio --marketplace rosasynthesiz/flstudio-mcp
```

## Use

Open FL Studio with a project, then ask Claude to call `fl_ping`. It reports what is missing, if anything.

More: https://rosasynthesiz.com/products/fl-studio-mcp

License: MIT.
