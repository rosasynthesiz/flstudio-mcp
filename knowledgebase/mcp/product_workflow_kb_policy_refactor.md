# Product Workflow Knowledgebase Policy Refactor

- **Date:** 2026-06-06
- **Agent/Author:** Codex
- **Topic:** Product workflow tools now attach source-qualified Knowledgebase policy metadata.
- **Affected File/API:** `src/fl_studio_mcp/kb_policy.py`, `src/fl_studio_mcp/music/mix_doctor.py`, `src/fl_studio_mcp/tools/mix_doctor.py`, `src/fl_studio_mcp/tools/project_doctor.py`, `src/fl_studio_mcp/tools/routing.py`, `src/fl_studio_mcp/tools/project_organizer.py`, `src/fl_studio_mcp/tools/chains.py`.
- **Context:** Updated mixing, mastering, production, and performance Knowledgebase entries should improve existing tools without creating unsafe new FL Studio write paths.
- **Observation:** Product tools benefit from KB rules as policy metadata and conservative diagnosis wording. KB entries must not be interpreted as executable operations.
- **Tested Values:** Mix Review synthetic clipping/headroom, missing high-pass, gain-stage, watch, balance snapshots, and user-facing compact KB output shape; Knowledgebase policy lookup for `master_peak_boundary`, `mix_doctor_insert_headroom_context`, and `mix_doctor_existing_plugin_only`.
- **Result:** A read-only `kb_policy` helper loads whitelisted JSON policy files. Mix Review user-facing findings/proposals include compact `kb_rule_ids`, `kb_confidence_levels`, and `safety_limits`, while full source-qualified rule details stay centralized in top-level `kb_policy_refs`. Project Health, Routing Review, Project Organizer, and Chain Planner return KB policy refs where relevant. Project Organizer color writes now use operation-registry-prepared RGB payloads instead of raw hex strings.
- **Confidence Level:** `implementation_verified`
- **Source/Method:** Static implementation review, live macOS smoke test, and focused offline tests.
- **Valid Ranges:** No new FL parameter ranges are introduced. Mixer/channel color payloads use existing operation-registry validation for `r/g/b` 0..255 or restore `color.int`.
- **Example:** An insert track above 0 dBFS is reported as headroom/stem risk with `mix_doctor_insert_headroom_context`; Master peaks at or above 0 dBFS use `mix_doctor_master_output_boundary`.
- **Known Pitfalls:** Do not load arbitrary KB JSON as commands. Do not repeat full KB rule details on every Mix Review finding/proposal; keep per-row metadata compact and source details centralized. Do not assume KB policy confidence is equivalent to live API verification. Keep plugin loading, render/export, and FL Cloud Mastering manual.
- **Reproduction Steps:** Run `.venv/bin/python tests/test_kb_policy.py` and `.venv/bin/python tests/test_mix_doctor.py`.
- **Open Questions:** None for the compact KB metadata output shape; future feature slices still need their own live or offline verification.
- **Next Recommended Action:** Completed by `knowledgebase/mcp/low_end_stereo_safety_assistant.*`; next step is live readback parity for controller build `channels-v39`.
