# Mastering Boundaries

- **Date:** 2026-06-06
- **Agent/Author:** Codex
- **Topic:** Mastering guidance and limits for FL Studio MCP assistants.
- **Affected File/API:** Export readiness, Mix Review, Reference Match, plugin-chain planning, `fl_plugin`, `fl_effect`, manual FL Cloud Mastering guidance.
- **Context:** Users may ask the assistant to master a track, but the current project safety rules prohibit render automation and plugin loading, and FL Cloud Mastering is a UI/file workflow.
- **Observation:** Image-Line describes mastering as final polish after the mix, with loudness target selection, tonal/reference comparison, and blind A/B comparison in FL Cloud Mastering. Maximus is documented as a multiband maximizer/compressor/limiter suited to final-stage mastering or per-track use, but actual parameter writes require loaded plugins and verified parameter mappings.
- **Tested Values:** No live FL Studio state was changed. No FL Cloud Mastering workflow was automated.
- **Result:** Assistants should treat mastering as plan/checklist/report guidance unless working with already-loaded, parameter-readable plugins through rollback-safe tools. Export and FL Cloud Mastering remain manual.
- **Confidence Level:** `docs_confirmed`
- **Source/Method:** Image-Line FL Cloud Mastering news/video transcript, Image-Line Maximus manual, Image-Line Mixing Advice manual.
- **Valid Ranges:** No Maximus parameter ranges are documented here. Any future Maximus parameter write needs plugin parameter readback and calibration.
- **Example:** The assistant may say "prepare the mix for mastering, verify no Master clipping, then use File > Export > Master manually", but it must not claim to trigger FL Cloud Mastering through MCP.
- **Known Pitfalls:** Mastering cannot repair a bad mix. Louder is not automatically better. Blind comparison helps avoid choosing a louder result only because it is louder. FL Cloud Mastering requires manual export workflow and internet-backed analysis.
- **Reproduction Steps:** Review the FL Cloud Mastering transcript and Maximus manual. Verify current MCP tool limitations in README and Engineering Standards.
- **Open Questions:** Whether future offline reference-analysis tools should produce a mastering-prep report without attempting render or master automation.
- **Next Recommended Action:** Add a read-only Export & Delivery Assistant slice before any mastering-oriented write logic.

## Assistant Guidance

- First run mix readiness checks: clipping, headroom, routing, muted/soloed states, loud audio clips, and unresolved organization issues.
- If the user asks for mastering, explain whether the project is mix-ready before giving mastering steps.
- Treat FL Cloud Mastering as manual guidance: File menu workflow, loudness target selection, reference selection, render/analyze/master, compare outputs, and choose the result.
- Encourage blind A/B comparison between original and mastered files to avoid visual or loudness bias.
- Recommend Maximus only as an already-loaded plugin or manual-load suggestion. Do not load it automatically.
- For already-loaded Maximus or other mastering plugins, use parameter listing/readback first; only write through safe plugin-parameter paths when the target parameter is resolved and rollback-safe.

## Source Notes

- FL Cloud Mastering produces final masters as 16-bit WAV files in the video workflow.
- The FL Cloud Mastering transcript says loudness targets can be selected by streaming preset or manual LUFS value, and references influence tonal balance and compression.
- The Maximus manual documents Maximus as a multiband maximizer with HML bands, per-band/master compression/limiting, look-ahead, saturation, stereo separation, and optional IIR or linear-phase band splitting.
- The Mixing Advice manual says to build the mix first, then master it.

