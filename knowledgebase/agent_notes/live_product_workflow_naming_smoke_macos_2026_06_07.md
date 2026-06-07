# Live Product Workflow Naming Smoke On macOS

- **Date:** 2026-06-07
- **Agent/Author:** Codex
- **Topic:** Live verification of renamed product workflow MCP tools.
- **Affected File/API:** FastMCP public tool registration, `fl_transport`, `fl_review_mix`, `fl_gain_stage`, `fl_review_routing`, `fl_project_health_overview`, `fl_check_project_preflight`, `fl_start_guided_cleanup`, `fl_get_guided_cleanup_context`, `fl_analyze_project_organization`, `fl_setup_chain`, `fl_apply_mix_adjustment`, `fl_rollback_last_change`.
- **Context:** The product workflow naming pass intentionally removed the old public names without compatibility aliases. A live FL Studio smoke was required to confirm that the current public names run correctly against the macOS TCP bridge.
- **Observation:** FL Studio Producer Edition v25.2.5 [build 5055] responded over the TCP daemon on port 9787 with controller build marker `channels-v38`, protocol version `2`, and a fresh heartbeat. The new public product workflow names executed successfully.
- **Tested Values:** `fl_transport(action="ping")`; read-only calls `fl_review_mix`, `fl_gain_stage`, `fl_review_routing`, `fl_project_health_overview`, `fl_check_project_preflight`, `fl_start_guided_cleanup`, `fl_get_guided_cleanup_context`, `fl_analyze_project_organization`, and `fl_setup_chain(track=20, chain_type="vocal")`; rollback-safe write call `fl_apply_mix_adjustment("trim_volume", track=20, target_db=-7.09)`.
- **Result:** All read-only calls completed successfully. The write smoke changed Track 20 volume from `-6.84 dB` / `0.5718` normalized to `-7.09 dB` / `0.5639` normalized, then `fl_rollback_last_change` restored Track 20 to `-6.84 dB` / `0.5718` normalized. Public tool registration contained all new names and none of the removed names.
- **Confidence Level:** `implementation_verified`
- **Source/Method:** `scripts/probes/test_product_workflow_naming_live.py` executed with `FLSTUDIO_MCP_TRANSPORT=tcp`; results written to `scratch/product_workflow_naming_live_2026_06_07.json`.
- **Valid Ranges:** No new FL parameter ranges were introduced. The write smoke used the existing mixer fader dB path and rollback safety layer.
- **Example:** `fl_apply_mix_adjustment("trim_volume", track=20, target_db=-7.09)` followed by `fl_rollback_last_change` restored the exact pre-write normalized fader value.
- **Known Pitfalls:** Historical live verification logs may still mention removed public names because they reflect the API surface that existed at the time. Do not use old public names for new live checks.
- **Reproduction Steps:** Ensure FL Studio and the TCP daemon are running, confirm the controller reports `channels-v38`, then run `FLSTUDIO_MCP_TRANSPORT=tcp .venv/bin/python scripts/probes/test_product_workflow_naming_live.py`.
- **Open Questions:** None for the renamed product workflow smoke path on this macOS build.
- **Next Recommended Action:** Treat the naming pass as live-smoked on macOS. The next feature slice can start with the read-only Low-End/Stereo Safety Assistant.
