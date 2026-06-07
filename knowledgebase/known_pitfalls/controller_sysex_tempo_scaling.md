# Controller SysEx and Tempo Scaling Pitfall

- **Date:** 2026-05-23
- **Agent/Author:** System Migration
- **Topic:** SysEx routing and tempo scaling bugs in the FL controller script.
- **Affected File/API:** `fl_controller/FLStudioMCP/device_FLStudioMCP.py`, `midi`, `general.processRECEvent`.
- **Context:** Bridge failures showed heartbeat timeouts and tempo writes collapsed to extremely low BPM values.
- **Observation:** Modern FL builds can deliver incoming SysEx through `OnSysEx(event)`, and `midi.REC_FromMIDI` makes tempo writes interpret raw BPM values as normalized MIDI fractions.
- **Tested Values:** End-to-end bridge checks for ping, get tempo, set tempo, play, get play state, and stop.
- **Result:** The controller supports both `OnMidiMsg` and `OnSysEx`. Tempo uses `midi.REC_UpdateValue | midi.REC_UpdateControl` without `REC_FromMIDI`.
- **Confidence Level:** `implementation_verified`
- **Source/Method:** `FIX_REPORT.md` post-mortem and controller implementation review.
- **Reproduction Steps:** Configure duplicate RX/TX MIDI output directions or write tempo with `REC_FromMIDI`; heartbeat or tempo readback fails.
- **Known Pitfalls:** RX should be FL input only and TX should be FL output only. Stale controller deployments can keep old behavior active.
- **Open Questions:** None.
- **Next Recommended Action:** Keep this entry separate from Mix Review recipes so policy loaders do not ingest controller transport findings as mix guidance.
