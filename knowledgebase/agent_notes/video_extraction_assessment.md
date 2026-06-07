# Video Extraction Assessment

- **Date:** 2026-06-06
- **Agent/Author:** Codex
- **Topic:** Assessment of Gemini-structured video transcript extractions.
- **Affected File/API:** `scratch/extractions/*.json`, `scratch/extractions/*.md`, `scratch/extractions/*_raw.txt`, Knowledgebase production/mixing/mastering/performance entries.
- **Context:** The repository is adding general FL Studio production knowledge for workflow, organization, performance, mixing, and mastering assistants. Genre-specific material is intentionally deferred.
- **Observation:** The Gemini "high" extractions are useful as a first-pass topic map, but they should not be treated as the final Knowledgebase source. They compress source nuance, sometimes turn heuristics into absolutes, and include concrete values or UI actions without enough safety qualification for MCP decision logic.
- **Tested Values:** Compared the Gemini summaries against the local raw transcripts for `4ICwZjBvgpo`, `Mx7AnMUCDic`, `UWW-ppRjmCQ`, `gJUmUd4FfeM`, `EvqGNWS1LIs`, `hFRwk1LOdBU`, `fDQsazzDwUU`, and `fWuC-OHsqiY`.
- **Result:** Use Gemini output as an index only. Re-extract reusable Knowledgebase rules from raw transcripts and official Image-Line manual/news pages. Store machine-relevant guidance as conservative JSON rules with source, confidence, and safety limits.
- **Confidence Level:** `docs_confirmed` for official manual/news facts; `user_reported` for locally supplied transcript-derived summaries until independently rechecked against the transcript.
- **Source/Method:** Manual review of local transcript files and official Image-Line pages listed in the new thematic Knowledgebase entries.
- **Valid Ranges:** Not applicable. This assessment does not define FL Studio API value ranges or parameter mappings.
- **Example:** Gemini's stereo extraction says kick and bass "must" be mono. The raw transcript and manual support this as a strong club/car-system recommendation for main low frequencies, not as an absolute rule for every creative context.
- **Known Pitfalls:** Do not copy transcript-derived plugin parameter values into tool write logic. Do not turn manual UI workflows into MCP write tools if plugin loading, UI automation, playlist clip editing, or rollback-safe readback is unavailable.
- **Reproduction Steps:** Open a Gemini `.json` file, open its matching `_raw.txt`, and compare concrete actions, warnings, and numeric values against the transcript.
- **Open Questions:** Whether future transcript extraction should use a shared schema that separates manual UI guidance, assistant heuristics, and candidate tool logic at extraction time.
- **Next Recommended Action:** For future video batches, keep raw transcript, structured extraction, and final Knowledgebase rule as separate artifacts. Prefer official manual pages for high-confidence general rules.

## Per-Video Assessment

| Video | Gemini assessment | Use in Knowledgebase |
|---|---|---|
| `4ICwZjBvgpo` Mixer Routing Getting Started | Good coverage of routing, sends, bus creation, naming/coloring, and external I/O. | Re-extract as workflow/routing guidance. Do not imply plugin insertion can be automated by MCP. |
| `Mx7AnMUCDic` Mixing Basics - Levels | Good coverage of dBFS, LUFS, channel volume offsets, gain plugins, and pink-noise balancing. | Re-extract with manual support from Mixing Advice. Keep pink-noise as a manual workflow, not a tool default. |
| `UWW-ppRjmCQ` Mixing Basics - Stereo Field | Useful, but some language is too absolute. | Re-extract as mono-compatibility and low-frequency stereo risk guidance. |
| `gJUmUd4FfeM` Mixing Basics - Compression | Useful concepts and workflows. | Re-extract with existing Fruity Limiter calibration kept authoritative for actual parameter writes. |
| `EvqGNWS1LIs` Mixing Basics - Delays | Useful for delay roles and automation ideas. | Re-extract as creative/manual workflow guidance. Avoid unverified Fruity Delay 3 parameter writes. |
| `hFRwk1LOdBU` Mixing Basics - Reverbs | Useful and aligns with official Reverb article. | Re-extract as send/space/automation guidance with CPU and low-end cautions. |
| `fDQsazzDwUU` FL Cloud Mastering | Mostly accurate as manual guidance. | Store as mastering boundary guidance. MCP must not claim export/master automation. |
| `fWuC-OHsqiY` CPU Meter Explained | Good conceptual explanation. | Combine with official performance and audio-settings manual pages for CPU assistant rules. |

