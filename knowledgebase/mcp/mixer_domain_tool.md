# Mixer Domain Tool (fl_mixer)

## Metadata

- **Date**: 2026-06-04
- **Agent/Author**: Antigravity (Claude Sonnet Thinking)
- **Topic**: Consolidated `fl_mixer` domain tool — v1.2 Phase 3 Slice 06
- **Affected File/API**: `src/fl_studio_mcp/tools/mixer.py`
- **Confidence Level**: `implementation_verified`
- **Source/Method**: Code implementation, static audit, unit tests
- **Related**: `knowledgebase/mcp/transport_domain_tool.md`

---

## Observation

`fl_mixer(action, params)` is the public mixer domain entrypoint in the
compact v2.0 tool surface. It was introduced additively during the v1.2
shadow phase; legacy mixer aliases covered by this domain tool are now retired
from public registration. It dispatches through
`operations.prepare_operation("mixer", ...)`,
which validates the action and parameters using the existing
`OperationSpec` registry before any FL mutation occurs.

---

## Actions and Safety Classes

| Action | Safety Class | Notes |
|---|---|---|
| `list` | read-only | Paginated via `fetch_all_pages` |
| `get` | read-only | Single track read |
| `get_selected` | read-only | Currently selected track |
| `get_route` | read-only | Routing read for a track |
| `select` | write-safe | Rollback restores prior selection |
| `set_color` | write-safe | Accepts int or r/g/b |
| `set_mute` | write-safe | Verify pair on mute field |
| `set_name` | write-safe | |
| `set_pan` | write-safe | Range -1..1 |
| `set_route` | write-safe | Verify pair on enabled field |
| `set_solo` | write-safe | Verify pair on solo field |
| `set_stereo_separation` | write-safe | Range -1..1 |
| `set_volume` | write-safe | unit: normalized or db |

---

## Implementation Notes

- Track-scoped write and read actions pre-validate with `mixer_track_error`
  before calling `prepare_operation`.  This catches invalid track indices
  early against the current project's dynamic mixer track count.
- `set_route` validates both `src` and `dst` indices before dispatching.
- `list` paginates automatically; all tracks are returned in a single
  MCP response.
- All writes go through `safety.safe_write` via `prepared.safe_write_kwargs`.
  This guarantees: scoped snapshot → write → readback → changelog →
  rollback restore.
- The tool annotation is `write-safe` because the tool can execute
  persistent writes; individual action safety is enforced by registry
  dispatch and documented in the docstring.

---

## Known Pitfalls

- `set_stereo_separation` may lack persistent readback on some FL builds
  (inherited constraint from the legacy `fl_mixer_set_stereo_separation`
  tool; `safe_write` prevents unverified success).
- Dynamic mixer track count is fetched via `CMD_GET_PROJECT_STATE`; if FL
  is not running, `mixer_track_error` returns `None` (permissive fallback)
  and the error surfaces later at bridge call time.

---

## Open Questions

- None for this slice. Live smoke testing remains deferred until FL Studio
  is available for the next verification checkpoint.

## Next Recommended Action

- Keep `fl_mixer` aligned with the operation registry and public registration
  baseline.
