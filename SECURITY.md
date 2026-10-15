# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x (latest PyPI release / `main`) | ✅ |
| < 1.0 | ❌ |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Email **rosasynthesiz@gmail.com** with "flstudio-mcp security" in the subject, or use
GitHub's private vulnerability reporting ("Report a vulnerability" under the
Security tab) if it is enabled. Include:

- what is affected (MCP server, TCP daemon, controller script, installer scripts),
- steps to reproduce or a proof of concept,
- your OS, Python version and FL Studio version.

I'll acknowledge the report within 7 days and keep you updated as I work on a fix.
Please give me a reasonable window to release a fix before disclosing publicly.

## Scope notes

flstudio-mcp drives a local DAW. Things that are especially in scope:

- the local TCP daemon (`fl-studio-mcp-daemon`) accepting connections from anything other than localhost,
- generated pyscripts / installer scripts writing outside FL Studio's user-data folders,
- MCP tools that can be coerced into arbitrary file writes or command execution.
