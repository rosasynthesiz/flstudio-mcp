# Agent Orientation Resource

- **Date**: 2026-06-07
- **Agent/Author**: Codex
- **Topic**: `fl://agent-briefing` read-only MCP resource
- **Affected File/API**: `src/fl_studio_mcp/tools/resources.py`, `tests/test_agent_briefing_resource.py`, `tests/test_resources.py`, docs and skill orientation references
- **Context**: Agents need a compact, current, safety-first entrypoint before choosing FLStudioMCP tools.
- **Observation**: `fl://agent-briefing` returns a compact orientation payload with startup guidance, safe bridge/status summary or error, current domain tools, workflow categories, token-saving strategy, safety rules, and stop rules. It avoids broad list reads and does not add controller commands or write behavior.
- **Tested Values**: Resource registration/read through the real FastMCP server path; compact-size check under 5 KB; current domain-tool names present; removed alias names absent; bridge-down-safe behavior covered by the existing resource safe-call pattern.
- **Result**: The resource is read-only, compact, and safe to read when the FL bridge is unavailable. It guides agents toward current domain/workflow tools and Knowledgebase-first behavior without changing FL Studio state.
- **Confidence Level**: implementation_verified
- **Source/Method**: Static implementation review plus focused Python resource tests. No live FL Studio write or live bridge verification was run.
- **Valid Ranges**: Resource output should remain compact; focused test enforces less than 5 KB. Bridge status read is limited to heartbeat/project-state summary when alive, or an error object when unavailable.
- **Example**: Read `fl://agent-briefing`, then `fl://status`, then choose a current workflow/domain tool such as `fl_review_mix`, `fl_project_health_overview`, `fl_mixer`, or `fl_batch`.
- **Known Pitfalls**: The resource is orientation only. It does not prove that FL Studio is connected, that a target is selected, or that a write is safe for a specific user request. Agents must still check the Knowledgebase and use rollback-backed write paths.
- **Reproduction Steps**: Run `.venv/bin/python -m pytest tests/test_agent_briefing_resource.py` and `.venv/bin/python tests/test_resources.py`.
- **Open Questions**: None for the resource shape. Live FL bridge output can vary by controller build and should be verified during live workflow smoke tests.
- **Next Recommended Action**: Keep the resource synchronized when public domain tools, workflow entrypoints, or stop rules change.
