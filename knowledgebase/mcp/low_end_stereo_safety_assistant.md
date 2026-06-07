# Low-End/Stereo Safety Assistant

- **Date:** 2026-06-07
- **Agent/Author:** Codex
- **Topic:** Read-only Low-End/Stereo Safety Assistant for Mix Review workflows.
- **Affected File/API:** `fl_review_low_end_stereo`, `src/fl_studio_mcp/music/mix_doctor.py`, `src/fl_studio_mcp/tools/mix_doctor.py`, `fl_controller/FLStudioMCP/device_FLStudioMCP.py`, `mixer_list_tracks.stereo_sep`.
- **Context:** The updated mixing Knowledgebase contains low-end mono-compatibility guidance. The MCP tool surface needed a dedicated read-only report for bass/sub, mono compatibility, stereo-width metadata, and Master headroom without adding FL write paths.
- **Observation:** `mixer_list_tracks` now includes the existing `mixer.getTrackStereoSep()` readback as `stereo_sep`, and `fl_review_low_end_stereo` uses track names, pan, stereo separation metadata, and peak data where available. The assistant returns findings, manual checks, compact KB rule IDs, confidence levels, safety limits, and top-level source-qualified KB references.
- **Tested Values:** Synthetic snapshots covering off-center kick pan `+0.28`, widened sub `stereo_sep=+0.32`, hot low-end peak `-2.0 dBFS`, Master peak `-0.5 dBFS`, three active low-end layers, and stopped/no-level behavior.
- **Result:** Offline tests confirm conservative findings for off-center low-end, widened low-end metadata, hot low-end, Master headroom, and low-end layering. Stopped snapshots skip hot peak rules when `levels_valid` is false. The tool output omits full per-row KB rule objects and keeps compact metadata.
- **Confidence Level:** `implementation_verified`
- **Source/Method:** `.venv/bin/python tests/test_mix_doctor.py`; `.venv/bin/python -m py_compile src/fl_studio_mcp/music/mix_doctor.py src/fl_studio_mcp/tools/mix_doctor.py fl_controller/FLStudioMCP/device_FLStudioMCP.py tests/test_mix_doctor.py`.
- **Valid Ranges:** `pan` is read as FL mixer pan `-1..+1`; `stereo_sep` is read from FL mixer stereo separation `-1..+1` where positive values widen/separate; peak values are dBFS derived from mixer peak reads or full-song watch data.
- **Example:** A track named `Sub Bass` with `stereo_sep=+0.32` produces a `low_end_stereo_width` finding and manual mono-compatibility checks, but no automatic stereo-separation or mid-side EQ write.
- **Known Pitfalls:** The assistant cannot measure true phase correlation, mono-sum cancellation, or sub-band spectrum width. Name-based low-end detection misses unlabeled low-frequency parts. Hot low-end and Master-headroom findings need playback or watch peak data.
- **Reproduction Steps:** Run `.venv/bin/python tests/test_mix_doctor.py` and inspect the Low-End/Stereo Safety Assistant section.
- **Open Questions:** Live verification should compare controller build `channels-v39` `mixer_list_tracks.stereo_sep` with `mixer_get_track.stereo_sep` in FL Studio.
- **Next Recommended Action:** Run a rollback-free live smoke after installing/reloading controller build `channels-v39`; then document FL build, controller marker, tested tracks, and readback parity.
