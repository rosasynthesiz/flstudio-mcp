# Mixing Fundamentals

- **Date:** 2026-06-06
- **Agent/Author:** Codex
- **Topic:** General mixing guidance for Mix Review, Project Health, routing, and LLM assistant reasoning.
- **Affected File/API:** Mix Review, Gain Staging, Reference Match, Project Health, Routing Review, `fl_apply_eq_intent`, `fl_apply_compression_intent`, `fl_apply_reverb_intent`, `fl_apply_delay_intent`.
- **Context:** The Knowledgebase needs reusable non-genre-specific mixing knowledge while preserving the repository's safety rule that project-state writes require rollback.
- **Observation:** Image-Line separates mixing from mastering. Mixing focuses on relative levels, panning, EQ, compression, timing, sidechain/ducking, reverb, and delay. Video transcripts add practical FL Studio workflows such as drum buses, send reverbs, delay throws, mono compatibility checks, and gain-staging before compressors.
- **Tested Values:** No live FL Studio state was changed. Existing calibrated plugin parameter mappings remain authoritative for actual writes.
- **Result:** Assistant rules should diagnose and plan from measured/readback project state where possible, then propose one safe fix at a time. General production advice may guide explanations and plans, but it must not become an unverified parameter write.
- **Confidence Level:** `docs_confirmed` for official manual/news pages; transcript-derived workflow notes are source-confirmed but not live API verified.
- **Source/Method:** Image-Line manual "Levels, Mixing & Clipping"; official Image-Line Reverb page; local transcripts for Mixing Basics Levels, Stereo Field, Compression, Delays, Reverbs, and Mixer Routing Getting Started.
- **Valid Ranges:** This entry does not define plugin parameter ranges. dB/Hz/plugin normalized mappings must come from `knowledgebase/conversions/` or `knowledgebase/fl_api/` calibration files.
- **Example:** For a busy mix with reverb masking, the assistant may explain that delay or automated send level can preserve space with less wash, but it should only write plugin parameters through existing calibrated rollback-safe intent tools.
- **Known Pitfalls:** Do not hardcode EQ cut values from general advice. Do not apply "always mono" or "always high-pass" rules as absolutes. Do not load missing plugins. Do not treat peak meters as loudness meters.
- **Reproduction Steps:** Review the listed Image-Line manual/news pages and local transcripts. Cross-check any proposed write against existing MCP tool safety annotations and Knowledgebase calibration files.
- **Open Questions:** Whether future Mix Review rules should ingest a machine-readable "diagnosis heuristic" registry separate from plugin-parameter mappings.
- **Next Recommended Action:** Use the JSON rules in this entry as LLM guidance first; promote any rule into tool logic only after focused tests and, when needed, live FL verification.

## Assistant Guidance

- Diagnose levels from actual mixer reads and peak watch where available.
- Keep Master clipping/headroom advice separate from individual source-track balance.
- Treat 0 dBFS as the fixed-bit-depth render/output clipping boundary; internal insert-track peaks above 0 dB are not automatically fatal in 32-bit float, but they can still indicate poor gain staging or make stem renders risky.
- Prefer source trims or bus-level fixes before pulling the Master as the default answer to clipping.
- Use panning and arrangement timing to reduce masking before heavy processing.
- Treat low-frequency stereo as a compatibility risk, especially for club/car/subwoofer playback, but phrase it as a strong recommendation for main low-end elements rather than an absolute creative rule.
- Use `fl_review_low_end_stereo` for read-only pan/stereo-separation metadata and manual mono-compatibility checks; do not treat it as true phase or spectral analysis.
- Use send effects for shared reverb/delay when multiple related elements need the same space or when CPU matters.
- Set reverb/delay sends to wet-only when using the send fader to control effect amount.
- Use automation for reverb/delay throws and busy-section cleanup; do not leave large ambience constantly active if it muddies dense sections.
- For compression advice, explain input-level dependency. Changes before a compressor can change the compression behavior and should be readjusted or rebalanced.

## Source Notes

- The Mixing Advice manual says mixing should come before mastering and primarily uses level, panning, EQ, and compression on a track-by-track basis.
- The same manual warns that severe sustained clipping in rendered audio is usually not recoverable.
- The Levels transcript explains dBFS, LUFS, dynamic range, channel-volume offsets, gain plugins, and pink-noise balancing.
- The Stereo Field transcript supports mono compatibility checks, phase-correlation awareness, low-end mono caution, default circular/equal-power panning, and careful use of Haas-style widening.
- The Compression transcript supports threshold/ratio/knee/attack/release explanations, gain-staging before compressors, drum vs. tonal compression differences, Maximus bus compression, and sidechain ducking.
- The Delays and Reverbs transcripts support delay-as-space, delay throws, feedback-loop filtering/saturation, wet-only sends, pre-delay, low-end reverb caution, and send-based CPU savings.
