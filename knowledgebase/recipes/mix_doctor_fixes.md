# Mix Review Diagnosis and Fix Policy

- **Date:** 2026-06-06
- **Agent/Author:** Codex
- **Topic:** Source-qualified policy rules used by Mix Review diagnosis, Low-End/Stereo Safety, gain staging, and gated fix planning.
- **Affected File/API:** `src/fl_studio_mcp/music/mix_doctor.py`, `src/fl_studio_mcp/tools/mix_doctor.py`, `fl_review_low_end_stereo`, `fl_apply_mix_adjustment`.
- **Context:** Mix Review uses measured mixer state, peak watch data, loaded plugin names, and EQ parameter readback to produce read-only findings plus one-at-a-time rollback-backed trim proposals.
- **Observation:** Updated mixing and mastering Knowledgebase entries distinguish Master/output clipping from insert-track headroom risk, prefer source or bus trims before Master trims, keep plugin loading/mastering/render actions manual, and treat low-frequency stereo as a compatibility risk rather than an absolute creative failure.
- **Tested Values:** Existing offline Mix Review tests use synthetic snapshots for clipping, headroom, missing high-pass, ungrouped tracks, EQ clash, trim planning, watch maxima, gain staging, low-end pan, mixer stereo separation metadata, low-end layer count, and Master headroom.
- **Result:** Mix Review should attach KB rule references to findings/proposals, keep all diagnosis read-only, and apply only approved `trim_volume` changes through the existing mixer volume safe-write path. `fl_review_low_end_stereo` should stay read-only and should report pan/stereo metadata and manual mono-compatibility checks without claiming true phase or spectral analysis.
- **Confidence Level:** `implementation_verified` for current tool safety path; `docs_confirmed` for general mixing/mastering guidance.
- **Source/Method:** Existing Mix Review tests plus `knowledgebase/mixing/mixing_fundamentals.*` and `knowledgebase/mastering/mastering_boundaries.*`.
- **Valid Ranges:** This entry does not define new dB, Hz, or plugin normalized ranges. Existing mixer fader calibration and plugin conversion files remain authoritative for writes.
- **Example:** If the Master clips and two source tracks are hot, propose source trims first. A Master trim may be listed only as an alternative and must not be combined blindly with source trims.
- **Known Pitfalls:** Do not treat every insert-track peak above 0 dBFS as an output clipping failure. Do not auto-load limiters or EQs. Do not promote missing high-pass hints to automatic writes without an already-loaded EQ2 slot and user approval.
- **Open Questions:** Whether a future live verification should compare `mixer_list_tracks.stereo_sep` against `mixer_get_track.stereo_sep` after installing controller build `channels-v39`.
- **Next Recommended Action:** Keep Mix Review policy metadata small and source-qualified; add focused tests for KB references whenever diagnosis behavior changes.

## Rules

- `mix_doctor_master_output_boundary`: Master peaks near or above 0 dBFS are output/render clipping or headroom risk and should be high priority.
- `mix_doctor_insert_headroom_context`: Insert-track peaks above 0 dBFS are diagnostic context and possible stem/headroom risk, not automatically the same severity as Master clipping.
- `mix_doctor_source_trim_first`: Prefer trimming hot source tracks or relevant buses before defaulting to a Master fader pull.
- `mix_doctor_existing_plugin_only`: EQ, compression, reverb, delay, limiting, and mastering suggestions may configure already-loaded plugins only through safe wrappers.
- `low_end_stereo_assistant_read_only`: Low-End/Stereo Safety Assistant reports metadata-backed risk and manual checks only; it must not write stereo separation, mid-side EQ, plugins, render, save, or mastering automation.
