# Learning Log

Chronological inbox for new findings.

## Format Template
```md
## YYYY-MM-DD — Short Topic

Agent/Source:
Context:
Observation:
Tested values:
Result:
Confidence:
Affected files/tools:
Should update machine-readable data:
Open questions:
Next action:
```

## 2026-06-06 — General Production Knowledgebase Expansion

Agent/Source: Codex
Context: Added generic FL Studio production knowledge from official Image-Line manual/news pages and local video transcripts in `scratch/extractions`.
Observation: Gemini-structured transcript extractions are useful as an index but not sufficient as final Knowledgebase truth because they compress nuance and sometimes make heuristics sound absolute.
Tested values: Compared local raw transcripts for routing, levels, stereo field, compression, delay, reverb, FL Cloud Mastering, and CPU Meter Explained against Gemini `.json`/`.md` summaries; extracted official manual/news guidance for workflow, mixing, mastering, and performance.
Result: Added source-qualified Markdown and JSON entries under `production/`, `mixing/`, `mastering/`, and `performance/`, plus an assessment note in `agent_notes/video_extraction_assessment.md`.
Confidence: `docs_confirmed` for official Image-Line manual/news facts; transcript-derived workflow notes remain source-confirmed guidance, not live API verification.
Affected files/tools: `knowledgebase/production/fl_studio_workflow_standards.*`, `knowledgebase/mixing/mixing_fundamentals.*`, `knowledgebase/mastering/mastering_boundaries.*`, `knowledgebase/performance/fl_studio_cpu_optimization.*`, `knowledgebase/agent_notes/video_extraction_assessment.md`
Should update machine-readable data: Yes, completed for assistant-guidance rules. No FL API parameter mapping was added.
Open questions: Future Performance Review and Jam-to-Project tools need separate designs before any of these heuristics become automated write behavior.
Next action: Use these JSON rules as read-only LLM guidance first; promote to tool logic only after safety review, focused tests, and live verification where applicable.
