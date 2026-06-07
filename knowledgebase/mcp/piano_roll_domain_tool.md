# Piano Roll Domain Tool

- **Date**: 2026-06-04
- **Agent/Author**: Codex
- **Topic**: Consolidated `fl_piano_roll` MCP wrapper
- **Affected File/API**: `src/fl_studio_mcp/tools/pianoroll.py`, `src/fl_studio_mcp/safety.py`, `CMD_ENSURE_PIANO_ROLL`, `CMD_GENERAL_UNDO`, generated Piano Roll `.pyscript` helpers
- **Context**: v1.2 slice 10 introduced the Piano Roll domain tool additively for parity testing and lower tool-selection overhead. In the current v2.0 public surface, legacy Piano Roll aliases covered by `fl_piano_roll` are retired.
- **Observation**: `fl_piano_roll(action, params)` consolidates existing undo-backed note writes, chord writes, clear, quantize, transpose, duplicate, velocity ramp, marker helpers, and explicit readback-limit reports. Generated-script writes route through `safety.safe_piano_roll_write`, which logs FL Studio undo as the restore action.
- **Tested Values**: `write_notes`, `transpose`, `add_marker`, invalid action, invalid note payload, invalid velocity range, `get_notes`, and `probe_return_channel`.
- **Result**: The domain entrypoint dispatches write actions through the existing Piano Roll undo-backed safety path and returns explicit API-limited responses for note readback.
- **Confidence Level**: implementation_verified
- **Source/Method**: Focused FastMCP unit tests with a fake bridge, static safety audit, and registration baseline check.
- **Valid Ranges**: MIDI pitches are integers `0..127`; note starts are `>= 0` bars; note lengths are `> 0` bars; note velocities and velocity-ramp endpoints are normalized floats `0..1`; optional channel indices are `>= 0`; optional pattern indices are `>= 1`; marker positions are `>= 0` bars; time-signature numerator and denominator are integers `>= 1`.
- **Example**: `fl_piano_roll(action="write_notes", params={"notes": [{"pitch": 60, "time_bars": 0, "length_bars": 0.25}], "mode": "append"})`
- **Known Pitfalls**: Note and marker readback to MCP remains API-limited. Rollback uses FL Studio undo, not scoped note snapshots, so Piano Roll write actions must stay out of generic persistent `fl_batch` writes. The generated script still requires the existing Piano Roll scripting setup where FL must run the MCP Apply script once per session for hotkey replay.
- **Reproduction Steps**: Run `.venv/bin/python -m pytest tests/test_piano_roll_domain.py`.
- **Open Questions**: Live FL Studio smoke tests were not run in this slice. A stable return channel for Piano Roll note/marker readback remains future research.
- **Next Recommended Action**: Keep `fl_piano_roll` aligned with the undo-backed safety path and public registration baseline.
