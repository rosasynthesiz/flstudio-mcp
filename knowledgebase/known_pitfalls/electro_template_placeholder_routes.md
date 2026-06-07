# Electro Template Placeholder Routes

- **Date:** 2026-06-07
- **Agent/Author:** Codex
- **Topic:** Electro template placeholder routing causes false Mix Review and cleanup findings.
- **Affected File/API:** `src/fl_studio_mcp/music/mix_doctor.py`, `src/fl_studio_mcp/tools/routing.py`, `fl_review_mix`, `fl_review_low_end_stereo`, `fl_detect_cleanup_candidates`, Project Health / Preflight.
- **Context:** The live `Electro` template reserves many default-named inserts by routing them to `Instruments ► Mix` before they contain audio, plugins, or direct Channel Rack targets.
- **Observation:** Existing generic heuristics treat non-Master outgoing routes as evidence that a mixer track is used, while cleanup detection treats default name plus no plugin/incoming route as unused. In this template, both interpretations can be wrong for tracks 22-115.
- **Tested Values:** `Insert 22`-`Insert 115` route to track 120 `Instruments ► Mix` at level `0.8` and were reported as 95 unused mixer tracks by cleanup detection. Mix Doctor returned 111 low findings, dominated by `missing_hpf` suggestions for these routed placeholders.
- **Result:** Tools should classify these tracks as `template_reserved_placeholder` when the Electro topology signature is present and should suppress cleanup, missing high-pass, audible-track, and ungrouped-track findings for them.
- **Confidence Level:** `measured_once`
- **Source/Method:** Live read-only dump and probes on FL Studio Producer Edition v25.2.5 [build 5055], controller build `channels-v38`, TCP transport.
- **Valid Ranges:** Route level `0.8` was observed for placeholder-to-instrument-bus routes. This entry does not define plugin parameter, EQ, dB, or stereo-separation mappings.
- **Example:** `Insert 22 -> Instruments ► Mix @0.8`, default name, no plugin, no direct channel target. In Electro this should not produce `missing_hpf` or `unused_mixer_track`.
- **Known Pitfalls:** Do not fix this by globally ignoring all default-named routed tracks; another project may intentionally route a default-named active track. Match a recognizable template topology first.
- **Reproduction Steps:** Open Electro, run `scratch/scripts/read_electro_template_live.py`, then run `scripts/run_mix_doctor.py --no-params --max-tracks 126 --peak-samples 1` and cleanup detection.
- **Open Questions:** Whether other standard templates use similar placeholder ranges, different bus collectors, or different route-level conventions.
- **Next Recommended Action:** Implement and test a reusable topology classifier with fixture coverage for Electro and then extend it to the remaining standard templates as they are live-read.
