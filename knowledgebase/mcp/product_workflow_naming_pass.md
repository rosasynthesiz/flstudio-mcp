# Product Workflow Naming Pass

- **Date:** 2026-06-06
- **Agent/Author:** Codex
- **Topic:** Public MCP product workflow naming cleanup.
- **Affected File/API:** `src/fl_studio_mcp/tools/mix_doctor.py`, `src/fl_studio_mcp/tools/routing.py`, `src/fl_studio_mcp/tools/project_doctor.py`, FastMCP public tool registration, user guide, roadmap, evals, and KB policy `tool_implications`.
- **Context:** Product workflow tools overused the "Doctor" naming pattern, making the public MCP surface harder to scan. The branch already accepts API-breaking tool-surface changes, so this pass removes the old public names instead of adding compatibility aliases.
- **Observation:** Mix, routing, project health, preflight, and guided cleanup workflows can keep the same safety behavior while exposing clearer public names.
- **Tested Values:** `fl_review_mix`, `fl_apply_mix_adjustment`, `fl_review_routing`, `fl_plan_routing_cleanup`, `fl_apply_routing_cleanup`, `fl_apply_bus_layout`, `fl_project_health_overview`, `fl_check_project_preflight`, `fl_start_guided_cleanup`, `fl_get_guided_cleanup_context`, `mix_review_watch`, `health_overview`, and `project_preflight`.
- **Result:** The public FastMCP names were renamed without adding new FL Studio API capability claims or new write paths. Existing rollback-backed write safety remains unchanged.
- **Confidence Level:** `implementation_verified`
- **Source/Method:** Static code review, focused offline tests, tool registration baseline check, JSON parse check, safety audit, and 2026-06-07 live macOS smoke via `scripts/probes/test_product_workflow_naming_live.py`.
- **Valid Ranges:** Not applicable; this entry documents public MCP names rather than FL Studio parameter ranges.
- **Example:** Use `fl_review_mix` for read-only mix diagnosis and `fl_apply_mix_adjustment` for one approved rollback-backed trim instead of the removed `fl_diagnose_mix` and `fl_apply_mix_fix` public names.
- **Known Pitfalls:** Do not keep old `fl_*doctor*` aliases in registration unless a future compatibility policy explicitly adds them. Historical live verification notes may still mention old names because those are records of the tool surface that existed at the time.
- **Reproduction Steps:** Register the MCP tools, inspect the public tool set, run focused tests for mix review, project health, routing cleanup, and KB policy references, run static safety audits, then run `FLSTUDIO_MCP_TRANSPORT=tcp .venv/bin/python scripts/probes/test_product_workflow_naming_live.py` against a live FL Studio session.
- **Open Questions:** Whether future product workflow names should prefer "Review", "Assistant", "Overview", or "Cleanup" on a case-by-case basis.
- **Next Recommended Action:** Keep future public workflow names descriptive and avoid defaulting to "Doctor" unless the user-facing distinction is intentional.

## Public Tool Mapping

| Removed name | Current name |
|---|---|
| `fl_diagnose_mix` | `fl_review_mix` |
| `fl_apply_mix_fix` | `fl_apply_mix_adjustment` |
| `fl_analyze_routing` | `fl_review_routing` |
| `fl_plan_routing_fix` | `fl_plan_routing_cleanup` |
| `fl_apply_routing_batch` | `fl_apply_routing_cleanup` |
| `fl_create_bus_layout` | `fl_apply_bus_layout` |
| `fl_project_health_dashboard` | `fl_project_health_overview` |
| `fl_preflight_project` | `fl_check_project_preflight` |
| `fl_start_guided_fix_mode` | `fl_start_guided_cleanup` |
| `fl_get_guided_fix_context` | `fl_get_guided_cleanup_context` |

## Output Field Mapping

| Removed field/value | Current field/value |
|---|---|
| `mix_doctor_watch` | `mix_review_watch` |
| `health_dashboard` | `health_overview` |
| `preflight_project` | `project_preflight` |
