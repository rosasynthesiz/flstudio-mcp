# Product Workflow Registry Refactor

- **Date**: 2026-06-05
- **Agent/Author**: Codex
- **Topic**: Product workflow writes prepared through the operation registry.
- **Affected File/API**: `src/fl_studio_mcp/tools/routing.py`, `src/fl_studio_mcp/tools/mix_doctor.py`, `src/fl_studio_mcp/operations.py`, `src/fl_studio_mcp/tools/batch.py`, `safety.safe_write`, `safety.safe_write_group`.
- **Context**: v1.2 Phase 5 refactors product workflows internally only where registry reuse removes duplicate command/snapshot/restore logic without changing public workflow behavior.
- **Observation**: Routing Review route writes and mixer bus renames now use `operations.prepare_operation(...).safe_write_group_entry()` before dispatching through `safety.safe_write_group`. Mix Review `trim_volume` now uses `operations.prepare_operation("mixer", "set_volume", ...)` before dispatching through `safety.safe_write`. Persistent `fl_batch` uses the same registry helper for grouped write entries.
- **Tested Values**: `mixer.set_route` entry for source `2`, destination `0`, disabled route; `mixer.set_name` entry for track `8`; Mix Review `trim_volume` on track `4` targeting `-3.0` dB; persistent `fl_batch` mixer mute write tests; operation registry mixer volume helper tests.
- **Result**: Registry-prepared route entries preserve command and restore payloads while adding the registry's explicit `("enabled", expected)` verification. Registry-prepared mixer name and Mix Review volume writes preserve their previous command/scope/restore behavior. Public FastMCP registration does not change.
- **Confidence Level**: implementation_verified
- **Source/Method**: Focused offline pytest tests with fake bridges plus static safety audit.
- **Valid Ranges**: Inherited from operation registry specs: mixer route `src`/`dst` are non-negative integer track indices and `enabled` is boolean; mixer name `track` is a non-negative integer and `name` is a string; mixer volume `unit` is `normalized` with value `0..1` or `db` with a finite numeric value.
- **Example**: `routing._route_write_entry(2, 0, False)` now prepares the `mixer.set_route` registry spec and returns a `safe_write_group` entry with `snap_scope` and `read_scope` set to `route:2:0`.
- **Known Pitfalls**: Project Organizer channel rename and hex color helpers were intentionally not refactored. Channel name registry validation currently requires non-empty names, while the existing Project Organizer helper did not. Color registry specs accept FL-native integer colors or RGB triplets, while Project Organizer public inputs are documented as hex strings.
- **Reproduction Steps**: Run `.venv/bin/python -m pytest tests/test_operation_registry.py tests/test_batch_persistent_writes.py tests/test_product_workflow_registry_refactor.py` and `.venv/bin/python tests/test_mix_doctor.py`.
- **Open Questions**: Live FL Studio smoke tests were not run for the refactored product workflow paths. Project Organizer color input compatibility should be handled in a separate slice if that public behavior is corrected.
- **Next Recommended Action**: Keep product workflow writes aligned with the operation registry while preserving public workflow behavior.
