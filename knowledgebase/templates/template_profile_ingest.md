# Template Profile Ingest

- **Date:** 2026-06-07
- **Agent/Author:** Codex
- **Topic:** Compact profile schema and normalization workflow for FL Studio standard project templates.
- **Affected File/API:** `knowledgebase/templates/template_profile.schema.json`, `knowledgebase/templates/profiles/*.json`, `scripts/normalize_template_dump.py`, `scripts/validate_template_profiles.py`.
- **Context:** The `Electro` template was live-measured first, and the user wants to capture 12 additional standard templates without spending large Codex context budgets on raw FL Studio dumps.
- **Observation:** Raw live dumps can be normalized into compact profiles that preserve mixer topology, routing, plugin signatures, pan, stereo separation, channel routing, reserved placeholder ranges, and sidechain control routes. Placeholder banks should be stored as ranges instead of repeated track rows.
- **Tested Values:** `Electro` profile generated from `scratch/analysis/2026-06-07_electro_template/electro_template_live_read.json`; profile path `knowledgebase/templates/profiles/electro.json`; maximum stored plugin parameters per plugin set to `8` for the reference profile.
- **Result:** `scripts/normalize_template_dump.py` creates schema-shaped compact profiles from read-only dump JSON. `scripts/validate_template_profiles.py` validates profile shape and cross-checks duplicate tracks, reserved ranges, control routes, detection anchors, confidence levels, and tool policy keys.
- **Confidence Level:** `implementation_verified`
- **Source/Method:** Offline implementation and focused tests in `tests/test_template_profile_tools.py`; validator run against `knowledgebase/templates/profiles/electro.json`.
- **Valid Ranges:** Confidence levels follow `knowledgebase/README.md`; roles are limited to `master`, `premaster`, `stem_bus`, `source`, `sidechain_control`, `reserved_placeholder`, `utility`, and `unknown`; plugin parameter signatures store normalized values as observed in `0..1` readbacks when available.
- **Example:** `knowledgebase/templates/profiles/electro.json` stores `Insert 22`-`Insert 115` as one reserved range routed to track 120 instead of 94 separate placeholder track objects.
- **Known Pitfalls:** Do not feed raw dumps directly to implementation agents when a compact validated profile is sufficient. Do not let external analysis infer mix-quality recommendations; profiles are factual topology inputs.
- **Reproduction Steps:** Run `PYTHONPATH=src .venv/bin/python scripts/normalize_template_dump.py <dump.json> --template-name <Name> --template-slug <slug> --output knowledgebase/templates/profiles/<slug>.json`, then run `PYTHONPATH=src .venv/bin/python scripts/validate_template_profiles.py --profile knowledgebase/templates/profiles/<slug>.json`.
- **Open Questions:** Decide whether future live smoke tests should capture an additional discriminator for structurally identical template profiles.
- **Next Recommended Action:** Keep standard-template updates profile-driven; use Gemini or another external analyzer only to normalize large dumps into this schema, then validate locally before implementation work.
