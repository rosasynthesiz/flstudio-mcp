# FL Studio MCP Knowledgebase

The purpose of this knowledgebase is to document machine-readable knowledge and
human insights about the FL Studio API and FL Studio production workflows. It is
intended to prevent LLMs from repeatedly making the same mistakes when using the
API, planning safe MCP actions, or reasoning about production workflows.

## Folder Roles
- `fl_api/`: Documentation of individual FL Studio API modules, limitations, and calibration procedures.
- `conversions/`: JSON/YAML mappings for value ranges (e.g., UI-dB to normalized floats).
- `recipes/`: Reusable workflows and templates that should not be hardcoded.
- `production/`: General FL Studio workflow, organization, and project-structure guidance.
- `mixing/`: Non-genre-specific mixing guidance and assistant heuristics.
- `mastering/`: Mastering guidance, boundaries, and manual-only workflows.
- `performance/`: CPU, audio-buffer, and project-performance guidance.
- `templates/`: FL Studio standard project template topology reports,
  machine-readable compact profiles, and profile schemas.
- `genres/`: Genre-specific production knowledge. Keep generic rules elsewhere.
- `known_pitfalls/`: Recurring errors and known issues.
- `agent_notes/`: Ongoing notes, learning logs (`learning_log.md`), and open questions.

## Maintenance Duty
Agents **must** consult this repository before making changes and document any new knowledge (see `AGENTS.md`).

## Confidence Levels
- `hypothesis`
- `user_reported`
- `docs_confirmed`
- `measured_once`
- `measured_repeated`
- `implementation_verified`
- `cross_platform_verified`
- `deprecated_or_rejected`

Markdown is sufficient for explanations only. **As soon as a mapping influences tool decisions, JSON/YAML must be updated as well.**

Important references:
- [AGENTS.md](../AGENTS.md)
- [MCP_TOOL_POLICY.md](./MCP_TOOL_POLICY.md)
- [Learning Log](./agent_notes/learning_log.md)
