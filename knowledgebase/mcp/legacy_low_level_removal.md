# Legacy Low-Level Removal

- **Date**: 2026-06-07
- **Agent/Author**: Codex
- **Topic**: v1.2 legacy low-level MCP alias removal
- **Affected File/API**: `src/fl_studio_mcp/server.py`, `scripts/check_tool_registration_baseline.py`, domain MCP tools
- **Context**: v1.2 Phase 6 removed redundant one-off low-level aliases after domain tools and `fl_batch` were added and parity-tested.
- **Observation**: The public FastMCP surface now registers 87 tools with 87 unique public names. Redundant aliases covered by `fl_transport`, `fl_mixer`, `fl_channel`, `fl_pattern`, `fl_playlist`, `fl_effect`, `fl_plugin`, `fl_piano_roll`, and `fl_batch` are removed without deprecation wrappers.
- **Tested Values**: Registration baseline: 87 public tools. Safety classes: 33 `write-safe`, 41 `read-only`, 4 `server-state`, 2 `external-write`, 7 unannotated Knowledgebase tools. Focused domain parity suite: 58 tests.
- **Result**: Product workflows, safety/history tools, resources, Knowledgebase tools, plugin preset guidance, and specialized workflows remain registered. The direct Internal EQ wrapper registration was removed in favor of `fl_effect`'s rollback-backed native EQ path.
- **Confidence Level**: implementation_verified
- **Source/Method**: Local registration check, focused pytest suite, safety audits, and static docs review.
- **Valid Ranges**: Not applicable; this entry tracks MCP public registration behavior, not FL value ranges.
- **Example**: Use `fl_transport(action="ping")` instead of the removed `fl_ping` alias.
- **Known Pitfalls**: Static safety audit still sees retired legacy function definitions in source because helper modules remain for tests and internal imports. Public registration is authoritative for the MCP tool surface.
- **Reproduction Steps**: Run `.venv/bin/python scripts/check_tool_registration_baseline.py`.
- **Open Questions**: Live FL Studio smoke tests were not run for this slice.
- **Next Recommended Action**: Run slice 15 final release docs and audit.
