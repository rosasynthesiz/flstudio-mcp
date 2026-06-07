# Effect And Plugin Domain Tools

- **Date**: 2026-06-04
- **Agent/Author**: Codex
- **Topic**: Consolidated `fl_effect` and `fl_plugin` MCP wrappers
- **Affected File/API**: `src/fl_studio_mcp/tools/effect.py`, `src/fl_studio_mcp/tools/plugin_domain.py`, `src/fl_studio_mcp/operations.py`, effect-slot, native EQ, and plugin-parameter protocol commands
- **Context**: v1.2 slice 09 introduced the effect/plugin domain tools additively for parity testing and lower tool-selection overhead. In the current v2.0 public surface, legacy effect, native EQ, and plugin-parameter aliases covered by `fl_effect` and `fl_plugin` are retired.
- **Observation**: `fl_effect(action, params)` validates effect-slot and native EQ actions through the internal operation registry. `fl_plugin(action, params)` validates already-loaded plugin list/parameter actions through the registry and resolves string parameter names to concrete integer indices before dispatch. Persistent writes route through `safety.safe_write`.
- **Tested Values**: Effect `get_slot`, `get_eq`, `set_slot_mix`, `set_eq_band`, invalid action, invalid slot mix; plugin `list`, `list_params`, `get_param`, `set_param`, invalid action, invalid parameter value, and explicit plugin-loading rejection.
- **Result**: Effect-slot, native EQ, and already-loaded plugin parameter reads/writes execute through the expected registry and safety paths. Plugin loading or insertion attempts are rejected before bridge dispatch.
- **Confidence Level**: implementation_verified
- **Source/Method**: Focused FastMCP unit tests with a fake bridge, static safety audit, and registration baseline check.
- **Valid Ranges**: Effect slots are integers `0..9`. Native EQ bands are integers `0..2`. Effect slot mix, plugin parameter values, and native EQ gain/frequency/bandwidth are normalized floats `0..1`. Plugin parameter indices must be concrete non-negative integers after name resolution.
- **Example**: `fl_effect(action="set_slot_mix", params={"track": 1, "slot": 0, "mix": 0.5})`; `fl_plugin(action="set_param", params={"track": 1, "slot": 0, "param": 2, "value": 0.75})`
- **Known Pitfalls**: `fl_effect` and `fl_plugin` are annotated `write-safe` because each public function can perform persistent writes; individual action safety is enforced by registry dispatch and documented in the tool docstrings. Plugin loading, plugin insertion, plugin removal, preset navigation writes, and full effect-chain restore remain unsupported. Native EQ type writes remain documented-unconfirmed on current live evidence and should only be trusted where readback verifies the change.
- **Reproduction Steps**: Run `.venv/bin/python -m pytest tests/test_effect_plugin_domain.py`.
- **Open Questions**: Live FL Studio smoke tests were not run in this slice; behavior mirrors existing legacy wrappers and registry specs. Some plugin parameters are plugin/build dependent and may not stick even though rollback remains safe.
- **Next Recommended Action**: Keep `fl_effect` and `fl_plugin` aligned with the operation registry and public registration baseline.
