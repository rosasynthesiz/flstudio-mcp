# Pattern And Playlist Domain Tools

- **Date**: 2026-06-04
- **Agent/Author**: Codex
- **Topic**: Consolidated `fl_pattern` and `fl_playlist` MCP wrappers
- **Affected File/API**: `src/fl_studio_mcp/tools/pattern.py`, `src/fl_studio_mcp/tools/playlist.py`, `src/fl_studio_mcp/operations.py`, pattern and playlist-track protocol commands
- **Context**: v1.2 slice 08 introduced the pattern/playlist domain tools additively for parity testing and lower tool-selection overhead. In the current v2.0 public surface, legacy pattern/playlist aliases covered by `fl_pattern` and `fl_playlist` are retired.
- **Observation**: `fl_pattern(action, params)` and `fl_playlist(action, params)` validate through the internal operation registry. Read-only actions use registry-built protocol payloads. Persistent writes route through `safety.safe_write`.
- **Tested Values**: Pattern `list`, `get`, `rename`, `select`, invalid `delete`, invalid `set_length`; playlist `list`, `get`, `set_mute`, `set_name`, invalid `clip_delete`, invalid `set_mute` state.
- **Result**: Pattern and playlist track reads/writes execute through the expected registry and safety paths. Prohibited pattern deletion and playlist clip editing attempts are rejected as unknown operations before bridge dispatch.
- **Confidence Level**: implementation_verified
- **Source/Method**: Focused FastMCP unit tests with a fake bridge, static safety audit, and registration baseline check.
- **Valid Ranges**: Pattern and playlist indices are 1-based integers. Pattern length `beats` must be greater than 0. RGB components are 0..255, or an existing FL color integer can be supplied. Playlist mute/solo/select state values must be booleans.
- **Example**: `fl_pattern(action="rename", params={"index": 2, "name": "Chorus"})`; `fl_playlist(action="set_mute", params={"index": 2, "state": true})`
- **Known Pitfalls**: `fl_pattern` and `fl_playlist` are annotated `write-safe` because each public function can perform persistent writes; individual action safety is enforced by registry dispatch and documented in the tool docstrings. Playlist scope is track metadata/control only. Playlist clip placement, movement, deletion, and editing remain unsupported. Pattern deletion remains unsupported.
- **Reproduction Steps**: Run `.venv/bin/python -m pytest tests/test_pattern_playlist_domain.py`.
- **Open Questions**: Live FL Studio smoke tests were not run in this slice; behavior mirrors existing legacy wrappers and registry specs. Pattern length writes remain documented-unconfirmed on affected FL builds.
- **Next Recommended Action**: Keep `fl_pattern` and `fl_playlist` aligned with the operation registry and public registration baseline.
