# Channel Domain Tool (fl_channel)

## Metadata

- **Date**: 2026-06-04
- **Agent/Author**: Antigravity (Claude Sonnet Thinking)
- **Topic**: Consolidated `fl_channel` domain tool — v1.2 Phase 3 Slice 07
- **Affected File/API**: `src/fl_studio_mcp/tools/channel.py`
- **Confidence Level**: `implementation_verified`
- **Source/Method**: Code implementation, static audit, unit tests
- **Related**: `knowledgebase/mcp/mixer_domain_tool.md`

---

## Observation

`fl_channel(action, params)` is the public channel domain entrypoint in the
compact v2.0 tool surface. It was introduced additively during the v1.2
shadow phase; legacy channel aliases covered by this domain tool are now
retired from public registration. It dispatches through
`operations.prepare_operation("channel", ...)`,
which validates the action and parameters using the existing
`OperationSpec` registry before any FL mutation occurs.

The `classify` action is a compound read-only operation that groups all
channels by their detected type. It is handled directly in the tool rather
than via the registry because it calls `fetch_all_pages` and aggregates
data server-side.

---

## Actions and Safety Classes

| Action | Safety Class | Notes |
|---|---|---|
| `list` | read-only | Paginated via `fetch_all_pages` |
| `get` | read-only | Single channel read |
| `get_selected` | read-only | Currently selected channel |
| `get_steps` | read-only | Step sequencer grid read |
| `classify` | read-only | Groups channels by type (AudioClip, Sampler, etc.) |
| `select` | write-safe | Rollback restores prior selection |
| `set_color` | write-safe | Accepts int or r/g/b |
| `set_mute` | write-safe | Verify pair on mute field |
| `set_mixer_target` | write-safe | Verify pair on target_fx_track |
| `set_name` | write-safe | |
| `set_pan` | write-safe | Range -1..1 |
| `set_solo` | write-safe | Verify pair on solo field |
| `set_steps` | write-safe | Full grid snapshot/restore per channel+pattern |
| `set_volume` | write-safe | unit: normalized or db |

---

## Implementation Notes

- All writes go through `safety.safe_write` via `prepared.safe_write_kwargs`.
  This guarantees: scoped snapshot → write → readback → changelog →
  rollback restore.
- `set_steps` resolves the current pattern index via `CMD_PATTERN_SELECTED`
  when `pattern` is not supplied in params, then re-prepares the operation
  so the snapshot scope correctly encodes the resolved pattern index.
- `list` paginates automatically via `fetch_all_pages`; all channels are
  returned in a single MCP response.
- `classify` calls `fetch_all_pages` on `CMD_CHANNEL_ROUTING_SUMMARY` and
  groups results by `type.label`. This preserves the previous channel
  classification behavior through the domain tool.
- The tool annotation is `write-safe` because the tool can execute
  persistent writes; individual action safety is enforced by registry
  dispatch and documented in the docstring.
- Legacy low-level channel aliases for details, naming, mixer assignment, and
  step sequencing are retired from public registration. Specialized workflow
  tools such as audio-clip helpers remain separate public tools.

---

## Known Pitfalls

- Audio clip multi-step workflows (`inspect_audio_clips`,
  `plan_audio_clip_safe_defaults`, `apply_audio_clip_safe_defaults`) are
  not exposed through `fl_channel`. They involve multi-channel logic,
  free-track lookup, and grouped writes that belong in the legacy workflow
  tools until a dedicated workflow tool is planned.
- `set_steps` with no `pattern` param reads the current pattern index with
  a live bridge call inside the tool before preparing the operation. If FL
  is not running, this raises `RuntimeError` before registry dispatch.

---

## Open Questions

- None for this slice. Live smoke testing remains deferred until FL Studio
  is available for the next verification checkpoint.

## Next Recommended Action

- Keep `fl_channel` aligned with the operation registry and public
  registration baseline.
