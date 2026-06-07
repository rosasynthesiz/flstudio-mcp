# Live macOS Smoke Test Report (2026-06-06)

* **Date:** 2026-06-06
* **Agent/Author:** Antigravity (Advanced Agentic Coding)
* **Topic:** Live macOS Smoke Test - Architecture Foundation & Tool Efficiency (v2.0.0 Metadata Layer Verification)
* **Affected File/API:** Core MCP tools (`fl_transport`, `fl_mixer`, `fl_channel`, `fl_pattern`, `fl_playlist`, `fl_effect`, `fl_plugin`, `fl_piano_roll`, `fl_batch`), Safety layer (`src/fl_studio_mcp/safety.py`), TCP Bridge, SSE Server.
* **Context:** Verifying the newly restructured metadata layer and consolidated domain tools against a live running FL Studio instance on macOS via the SSE server (port 8080) and TCP bridge (port 9787).
* **Observation:** The consolidated domain tools correctly execute read-only audits and successfully enforce safety policies/KB metadata at runtime. The rollback contract was fully verified on a mixer color modification.
* **Tested Values:**
  * Transport ping: build marker `channels-v38`, protocol version `2`, FL Studio Producer Edition `v25.2.5 [build 5055]`.
  * Read-only sweep: `fl_diagnose_mix`, `fl_gain_stage`, `fl_preflight_project`, `fl_analyze_routing`, `fl_analyze_project_organization`, and `fl_setup_chain` (vocal chain test on Track 20).
  * Color modification: Track 20 ("Toploop") changed from `#ABA362` to `#FF0080` (RGB: `255, 0, 128`), and then rolled back.
* **Result:** Success. The original color `#ABA362` was correctly restored on rollback. All read-only sweeps returned correct metadata, safety limits, and KB references.
* **Confidence Level:** `implementation_verified`
* **Source/Method:** Executed programmatic checks via SSE client connecting to `http://localhost:8080/sse` sending tool calls, with results saved to `scratch/smoke_test_results.json`.
* **Reproduction Steps:**
  1. Ensure TCP daemon is active on port 9787.
  2. Ensure SSE server is running on port 8080.
  3. Execute `python scratch/run_live_mcp_checks.py`.
  4. Inspect output in `scratch/smoke_test_results.json`.
* **Open Questions:** None. The API behavior matches existing documentation.
* **Next Recommended Action:** Proceed with the rest of the Roadmap v2.0.0 milestones.

---

## Technical Details

### 1. Read-Only Sweep
* **`fl_transport` (action="ping")**: Confirmed connected and alive. Heartbeat age was 0.07 seconds.
* **`fl_diagnose_mix`**: Successfully identified EQ clashes (e.g. compenting EQ around 144Hz, 1153Hz, 2482Hz, and 2901Hz). Returned `mix_doctor_existing_plugin_only` KB rule.
* **`fl_gain_stage`**: Recommended level trims.
* **`fl_preflight_project`**: Returned export preflight checks.
* **`fl_analyze_routing`**: Analyzed mixer routing structure and returned correct KB policy rules.
* **`fl_analyze_project_organization`**: Identified unnamed/ungrouped channels and mapped KB rules.
* **`fl_setup_chain`**: Planned a vocal chain structure on Track 20, listing installed effects by role and advising the user to load them manually.

### 2. Rollback-Safe Mixer Color Modification
The color test on Track 20 ("Toploop") verified:
* **Original Track state read**: Color `#ABA362` (RGB: `171, 163, 98`).
* **Write application**: Set color to `#FF0080` (RGB: `255, 0, 128`) via `fl_mixer(action="set_color")`.
* **Readback verification**: Color readback confirmed new color was `#FF0080`.
* **Rollback application**: Called `fl_rollback_last_change`.
* **Verification post-rollback**: Readback confirmed track color returned to `#ABA362` (RGB: `171, 163, 98`).
* **Rollback Status**: Verified success.

### 3. Policy Compliance Check
* **Mutations with rollback**: Yes. No changes persisted after rollback.
* **KB-Refs in Tool outputs**: Yes, confirmed rule IDs such as `mix_doctor_existing_plugin_only`, `preserve_existing_structure_first`, etc. were included in the JSON response payload.
* **Tool boundaries**: All tools stayed within constraints (no plugin loading, saving, rendering, or FL Cloud Mastering automation).
