# Template Profile Classifier

- **Date:** 2026-06-07
- **Agent/Author:** Codex
- **Topic:** Data-driven classifier for FL Studio standard template profiles.
- **Affected File/API:** `src/fl_studio_mcp/project_templates.py`, `knowledgebase/templates/profiles/*.json`, Mix Review, Low-End/Stereo Review, Routing Review/Cleanup, Project Health / Preflight, Project Organizer.
- **Context:** The user captured 12 additional FL Studio standard template profiles after the initial `Electro` profile. Product tools must preserve those stem/mono/stereo template structures and avoid false cleanup or mix-improvement findings.
- **Observation:** Compact template profiles contain enough mixer, routing, channel-routing, role, reserved-range, control-route, and tool-policy data to classify the standard template topology without hard-coded per-template logic. Some templates are structurally identical from available readbacks.
- **Tested Values:** Profiles validated and classifier-tested: `breakbeat`, `chillout`, `chillout_ambient`, `drum_and_bass`, `dubstep`, `edm_house`, `electro`, `electro_template`, `funk`, `hiphop_trap`, `jazz`, `metal`, `rock`, `trap`.
- **Result:** `project_templates.classify_topology()` now loads compact profiles, scores live readbacks against profile names/routes/channel routes/reserved ranges, annotates track roles and tool policies, recognizes known sidechain-control routes, and returns compact candidate/ambiguity metadata for product workflows.
- **Confidence Level:** `implementation_verified`
- **Source/Method:** Offline schema validation via `scripts/validate_template_profiles.py`; parametric regression tests in `tests/test_template_topology.py`; existing Mix Doctor and Project Doctor regression tests.
- **Valid Ranges:** Role values are profile schema roles mapped to tool roles; profile `reserved_placeholder` maps to runtime `template_reserved_placeholder`; known control-route level matching allows exact profile level or absent live level.
- **Example:** A reserved range such as `Insert 24`-`Insert 115` routed to track 120 is expanded into runtime `template_reserved_placeholder` roles and suppresses unused-track, missing-HPF, ungrouped, low-end-width, off-center-bass, and stopped-layering warnings.
- **Known Pitfalls:** `Chillout`/`Chillout-Ambient`, `HipHop-Trap`/`Trap`, and `Funk`/`Rock` are indistinguishable from the current mixer/routing/channel readbacks. The classifier reports candidate templates and `ambiguous=true` instead of claiming false certainty.
- **Reproduction Steps:** Run `PYTHONPATH=src .venv/bin/python scripts/validate_template_profiles.py`, then `PYTHONPATH=src .venv/bin/python -m pytest tests/test_template_topology.py tests/test_template_profile_tools.py`.
- **Open Questions:** If exact UI template names are required for structurally identical profiles, identify an additional read-only source such as project metadata or a verified plugin-parameter fingerprint that differs between those templates.
- **Next Recommended Action:** Keep future standard-template profiles in `knowledgebase/templates/profiles/` and extend only the profile data unless a new readback field is needed to resolve known ambiguous pairs.
