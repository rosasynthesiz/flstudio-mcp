"""Phase 4 MCP tools -- author notes, chords, and apply transformations into FL's piano roll.

Uses the generate-script bridge: since FL's controller API cannot directly read or write
notes, we generate a .pyscript with note data or actions baked in, write it to the Piano Roll
scripts folder, and send Ctrl+Alt+Y (Cmd+Opt+Y on macOS) to trigger it.
Requires a one-time arm: run "MCP Apply" once from the Piano Roll Scripting menu.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import protocol, safety
from ..connection import get_bridge
from ..music.scales import parse_root_note
from ..pyscript_gen import quantize_notes


class PianoRollNote(BaseModel):
    pitch: int = Field(ge=0, le=127, description="MIDI note (60 = middle C; FL displays it as C5).")
    time_bars: float = Field(0.0, ge=0.0, description="Start, in bars from the pattern start.")
    length_bars: float = Field(1.0, gt=0.0, description="Duration in bars.")
    velocity: float = Field(
        100 / 127.0, ge=0.0, le=1.0, description="0.0-1.0 (0.787 ~= MIDI velocity 100)."
    )


CHORD_TEMPLATES = {
    "maj": [0, 4, 7],
    "major": [0, 4, 7],
    "": [0, 4, 7],
    "min": [0, 3, 7],
    "minor": [0, 3, 7],
    "m": [0, 3, 7],
    "7": [0, 4, 7, 10],
    "dom7": [0, 4, 7, 10],
    "maj7": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10],
    "min7": [0, 3, 7, 10],
    "m7b5": [0, 3, 6, 10],
    "halfdim": [0, 3, 6, 10],
    "dim7": [0, 3, 6, 9],
    "dim": [0, 3, 6, 9],
    "aug": [0, 4, 8],
    "sus4": [0, 5, 7],
    "sus2": [0, 2, 7],
    "9": [0, 4, 7, 10, 14],
    "maj9": [0, 4, 7, 11, 14],
    "m9": [0, 3, 7, 10, 14],
    "min9": [0, 3, 7, 10, 14],
}


def _target_payload(channel: int | None, pattern: int | None) -> dict:
    payload = {}
    if channel is not None:
        payload["channel"] = int(channel)
    if pattern is not None:
        payload["pattern"] = int(pattern)
    return payload


def _ensure_piano_roll(bridge, channel: int | None, pattern: int | None) -> dict:
    return bridge.call(protocol.CMD_ENSURE_PIANO_ROLL, _target_payload(channel, pattern))


def _readback_limit_response() -> dict:
    return {
        "ok": False,
        "error": "Piano Roll readback to the MCP server is currently api-limited.",
        "readback_available": False,
        "status": "api-limited",
        "details": (
            "Generated Piano Roll scripts can read and mutate notes locally, but this branch "
            "does not have a verified return channel from that script sandbox back to the MCP "
            "server. Use undo-backed writes and rollback with fl_rollback_last_change."
        ),
    }


def _coerce_params(params: dict | None) -> dict:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    return dict(params)


def _target_from_params(params: dict) -> tuple[int | None, int | None]:
    channel = _optional_int(params, "channel", minimum=0)
    pattern = _optional_int(params, "pattern", minimum=1)
    return channel, pattern


def _optional_int(params: dict, key: str, *, minimum: int | None = None) -> int | None:
    value = params.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if minimum is not None and out < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    return out


def _required_int(params: dict, key: str, *, minimum: int | None = None) -> int:
    if key not in params:
        raise ValueError(f"{key} is required")
    value = _optional_int(params, key, minimum=minimum)
    assert value is not None
    return value


def _optional_float(
    params: dict,
    key: str,
    *,
    default: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    required: bool = False,
) -> float | None:
    if key not in params:
        if required:
            raise ValueError(f"{key} is required")
        return default
    try:
        out = float(params[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if minimum is not None and out < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    if maximum is not None and out > maximum:
        raise ValueError(f"{key} must be <= {maximum}")
    return out


def _mode(params: dict, *, default: str) -> str:
    mode = str(params.get("mode", default)).strip().lower()
    if mode not in {"replace", "append"}:
        raise ValueError("mode must be 'replace' or 'append'")
    return mode


def _notes_from_params(params: dict) -> list[dict]:
    raw_notes = params.get("notes")
    if not isinstance(raw_notes, list):
        raise ValueError("notes must be a list")
    return [PianoRollNote.model_validate(note).model_dump() for note in raw_notes]


def _run_piano_roll_action(action: str, params: dict | None) -> dict:
    """Dispatch one consolidated Piano Roll action without calling public MCP tools."""
    resolved = _coerce_params(params)
    normalized = str(action).strip().lower()

    if normalized in {"get_notes", "readback_limit"}:
        return _readback_limit_response()

    if normalized == "probe_return_channel":
        out = _readback_limit_response()
        out["ok"] = True
        out["reason"] = out.pop("error")
        out["recommended_path"] = (
            "Use write actions with FL undo-backed rollback. Treat note and marker readback "
            "as unavailable until a version-stable return channel is implemented."
        )
        return out

    bridge = get_bridge()
    channel, pattern = _target_from_params(resolved)

    if normalized == "write_notes":
        arr = _notes_from_params(resolved)
        quantize = _optional_float(resolved, "quantize", default=0.0, minimum=0.0)
        assert quantize is not None
        if quantize > 0:
            arr = quantize_notes(arr, quantize)
        mode = _mode(resolved, default="replace")
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_write_notes",
            params={
                "notes": arr,
                "mode": mode,
                "quantize": quantize,
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(arr, mode, channel=channel, pattern=pattern),
        )

    if normalized == "write_chord":
        chord_name = str(resolved.get("chord_name", "")).strip()
        if not chord_name:
            raise ValueError("chord_name is required")
        if "root_note" not in resolved:
            raise ValueError("root_note is required")
        try:
            root = parse_root_note(resolved["root_note"])
        except ValueError as exc:
            raise ValueError(f"Invalid root note: {exc}") from exc
        chord_type = chord_name.lower()
        if chord_type not in CHORD_TEMPLATES:
            raise ValueError(f"unknown chord type: {chord_name!r}")
        time_bars = _optional_float(resolved, "time_bars", default=0.0, minimum=0.0)
        length_bars = _optional_float(resolved, "length_bars", default=1.0, minimum=0.0)
        velocity = _optional_float(
            resolved, "velocity", default=100 / 127.0, minimum=0.0, maximum=1.0
        )
        assert time_bars is not None and length_bars is not None and velocity is not None
        if length_bars <= 0:
            raise ValueError("length_bars must be > 0")
        mode = _mode(resolved, default="append")
        chord_notes = [
            {
                "pitch": root + offset,
                "time_bars": time_bars,
                "length_bars": length_bars,
                "velocity": velocity,
            }
            for offset in CHORD_TEMPLATES[chord_type]
            if 0 <= root + offset <= 127
        ]
        if not chord_notes:
            raise ValueError("chord produced no in-range MIDI notes")
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_write_chord",
            params={
                "chord_name": chord_name,
                "root_note": resolved["root_note"],
                "time_bars": time_bars,
                "length_bars": length_bars,
                "velocity": velocity,
                "mode": mode,
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(chord_notes, mode, channel=channel, pattern=pattern),
        )

    if normalized == "clear":
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_clear",
            params=_target_payload(channel, pattern),
            apply=lambda: bridge.apply_notes([], mode="replace", channel=channel, pattern=pattern),
        )

    if normalized == "quantize":
        grid_bars = _optional_float(resolved, "grid_bars", default=0.0625, minimum=0.0)
        assert grid_bars is not None
        if grid_bars <= 0:
            raise ValueError("grid_bars must be > 0")
        snap_ends = bool(resolved.get("snap_ends", False))
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_quantize",
            params={
                "grid_bars": grid_bars,
                "snap_ends": snap_ends,
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                quantize=grid_bars,
                snap_ends=snap_ends,
                channel=channel,
                pattern=pattern,
            ),
        )

    if normalized == "transpose":
        semitones = _required_int(resolved, "semitones")
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_transpose",
            params={"semitones": semitones, **_target_payload(channel, pattern)},
            apply=lambda: bridge.apply_notes(
                [], trigger=True, transpose=semitones, channel=channel, pattern=pattern
            ),
        )

    if normalized == "duplicate":
        offset_bars = _optional_float(resolved, "offset_bars", default=1.0, minimum=0.0)
        assert offset_bars is not None
        if offset_bars <= 0:
            raise ValueError("offset_bars must be > 0")
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_duplicate",
            params={"offset_bars": offset_bars, **_target_payload(channel, pattern)},
            apply=lambda: bridge.apply_notes(
                [], trigger=True, duplicate_bars=offset_bars, channel=channel, pattern=pattern
            ),
        )

    if normalized == "velocity_ramp":
        start = _optional_float(resolved, "start", minimum=0.0, maximum=1.0, required=True)
        end = _optional_float(resolved, "end", minimum=0.0, maximum=1.0, required=True)
        assert start is not None and end is not None
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_velocity_ramp",
            params={"start": start, "end": end, **_target_payload(channel, pattern)},
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                velocity_ramp=(start, end),
                channel=channel,
                pattern=pattern,
            ),
        )

    if normalized == "add_marker":
        time_bars = _optional_float(resolved, "time_bars", minimum=0.0, required=True)
        name = str(resolved.get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        mode = _optional_int(resolved, "mode", minimum=0)
        if mode is None:
            mode = 0
        assert time_bars is not None
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_add_marker",
            params={
                "time_bars": time_bars,
                "name": name,
                "mode": mode,
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                marker_add={"time_bars": time_bars, "name": name, "mode": mode},
                channel=channel,
                pattern=pattern,
            ),
        )

    if normalized == "add_time_signature_marker":
        time_bars = _optional_float(resolved, "time_bars", minimum=0.0, required=True)
        numerator = _required_int(resolved, "numerator", minimum=1)
        denominator = _required_int(resolved, "denominator", minimum=1)
        name = str(resolved.get("name", "Time Signature")).strip() or "Time Signature"
        assert time_bars is not None
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_add_time_signature_marker",
            params={
                "time_bars": time_bars,
                "numerator": numerator,
                "denominator": denominator,
                "name": name,
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                marker_add={
                    "time_bars": time_bars,
                    "name": name,
                    "mode": 8,
                    "ts_num": numerator,
                    "ts_den": denominator,
                },
                channel=channel,
                pattern=pattern,
            ),
        )

    if normalized == "clear_markers":
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_roll_clear_markers",
            params=_target_payload(channel, pattern),
            apply=lambda: bridge.apply_notes(
                [], trigger=True, marker_clear=True, channel=channel, pattern=pattern
            ),
        )

    raise ValueError(f"unknown piano roll action: {action}")


def register(mcp: FastMCP) -> None:
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }
    _WR = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "write-safe",
    }

    # ---- Legacy Tool Names (Aliased/Kept for Backwards Compatibility) -------

    @mcp.tool(
        annotations={
            "title": "Write piano-roll notes (legacy)",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        }
    )
    def fl_write_piano_roll_notes(
        notes: list[PianoRollNote],
        mode: Annotated[
            str,
            Field(description="'replace' clears first; 'append' adds."),
        ] = "replace",
        quantize: Annotated[float, Field(description="Quantization grid in bars.")] = 0.0,
    ) -> dict:
        """Legacy write notes wrapper. Use fl_piano_write_notes instead.

        Safety: Write-Safe with Rollback. Piano Roll writes are undo-backed;
        note readback to MCP remains API-limited.
        """
        return fl_piano_write_notes(notes, mode, quantize)

    @mcp.tool(annotations={"title": "Quantize piano-roll notes (legacy)", **_WR})
    def fl_quantize_pattern(
        grid_bars: Annotated[float, Field(gt=0, description="Snap resolution.")] = 0.0625,
        snap_ends: Annotated[bool, Field(description="Snap note lengths.")] = False,
    ) -> dict:
        """Legacy quantize wrapper. Use fl_piano_quantize instead.

        Safety: Write-Safe with Rollback. Piano Roll writes are undo-backed;
        note readback to MCP remains API-limited.
        """
        return fl_piano_quantize(grid_bars, snap_ends)

    # ---- Phase 4 First-Class Piano Roll Tools -------------------------------

    @mcp.tool(
        annotations={
            "title": "Piano Roll domain operation",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        }
    )
    def fl_piano_roll(
        action: Annotated[
            str,
            Field(
                description=(
                    "Piano Roll action: write_notes, write_chord, clear, quantize, "
                    "transpose, duplicate, velocity_ramp, add_marker, "
                    "add_time_signature_marker, clear_markers, get_notes, "
                    "probe_return_channel."
                )
            ),
        ],
        params: Annotated[
            dict | None,
            Field(
                description=(
                    "Action parameters. Common optional keys for write actions: "
                    "{channel?: int, pattern?: int}. write_notes: {notes: list, "
                    "mode?: replace|append, quantize?: float}. write_chord: "
                    "{chord_name, root_note, time_bars?, length_bars?, velocity?, mode?}. "
                    "quantize: {grid_bars?, snap_ends?}. transpose: {semitones}. "
                    "duplicate: {offset_bars?}. velocity_ramp: {start, end}. "
                    "add_marker: {time_bars, name, mode?}. "
                    "add_time_signature_marker: {time_bars, numerator, denominator, name?}."
                )
            ),
        ] = None,
    ) -> dict:
        """Run one consolidated Piano Roll note, transform, marker, or probe action.

        Generated-script write actions use the existing Piano Roll safety path:
        the controller retargets/opens the Piano Roll where requested, the
        generated script executes inside FL's undo section where available, and
        ``fl_rollback_last_change`` replays FL Studio undo through
        ``general.undoUp``. Note and marker readback remain API-limited; use
        ``get_notes`` or ``probe_return_channel`` to return that explicit limit.

        Safety: Write-Safe with Rollback for generated-script writes; Read-Only
        for readback-limit reports. Piano Roll actions are intentionally not
        eligible for generic persistent ``fl_batch`` writes.
        """
        return _run_piano_roll_action(action, params)

    @mcp.tool(
        annotations={
            "title": "Write notes to Piano roll",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        }
    )
    def fl_piano_write_notes(
        notes: list[PianoRollNote],
        mode: Annotated[
            str,
            Field(description="'replace' clears the pattern first; 'append' adds to it."),
        ] = "replace",
        quantize: Annotated[
            float,
            Field(description="Optional grid (bars) to snap note starts to: 0.0625=1/16, 0=off."),
        ] = 0.0,
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget before writing."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before writing."),
        ] = None,
    ) -> dict:
        """Write notes into the currently active pattern's Piano roll.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; note readback to MCP remains API-limited.
        """
        arr = [n.model_dump() for n in notes]
        if quantize and quantize > 0:
            arr = quantize_notes(arr, float(quantize))
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)

        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_write_notes",
            params={
                "notes": arr,
                "mode": mode,
                "quantize": quantize,
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(arr, mode, channel=channel, pattern=pattern),
        )

    @mcp.tool(annotations={"title": "Write chord to Piano roll", **_WR})
    def fl_piano_write_chord(
        chord_name: Annotated[
            str,
            Field(description="Chord type, for example 'maj7', 'min7', 'sus4', 'm9'."),
        ],
        root_note: Annotated[
            str | int,
            Field(description="Root note as name or MIDI number."),
        ],
        time_bars: Annotated[
            float,
            Field(ge=0.0, description="Start in bars from pattern start."),
        ] = 0.0,
        length_bars: Annotated[float, Field(gt=0.0, description="Duration in bars.")] = 1.0,
        velocity: Annotated[
            float,
            Field(ge=0.0, le=1.0, description="Velocity 0-1."),
        ] = 100 / 127.0,
        mode: Annotated[
            str,
            Field(description="'replace' clears first; 'append' adds."),
        ] = "append",
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget before writing."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before writing."),
        ] = None,
    ) -> dict:
        """Write a named chord into the Piano roll at the active pattern.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; note readback to MCP remains API-limited.
        """
        try:
            root = parse_root_note(root_note)
        except ValueError as e:
            return {"ok": False, "error": f"Invalid root note: {e}"}

        chord_type = chord_name.strip().lower()
        if chord_type not in CHORD_TEMPLATES:
            return {
                "ok": False,
                "error": (
                    f"Unknown chord type: {chord_name!r}. "
                    f"Supported types: {list(CHORD_TEMPLATES.keys())}"
                ),
            }

        intervals = CHORD_TEMPLATES[chord_type]
        chord_notes = []
        for offset in intervals:
            pitch = root + offset
            if 0 <= pitch <= 127:
                chord_notes.append(
                    {
                        "pitch": pitch,
                        "time_bars": float(time_bars),
                        "length_bars": float(length_bars),
                        "velocity": float(velocity),
                    }
                )

        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)

        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_write_chord",
            params={
                "chord_name": chord_name,
                "root_note": root_note,
                "time_bars": time_bars,
                "length_bars": length_bars,
                "velocity": velocity,
                "mode": mode,
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(chord_notes, mode, channel=channel, pattern=pattern),
        )

    @mcp.tool(annotations={"title": "Clear all notes in Piano roll", **_WR})
    def fl_piano_clear(
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget before clearing."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before clearing."),
        ] = None,
    ) -> dict:
        """Clear all notes in the currently active pattern's Piano roll.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; note readback to MCP remains API-limited.
        """
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_clear",
            params=_target_payload(channel, pattern),
            apply=lambda: bridge.apply_notes([], mode="replace", channel=channel, pattern=pattern),
        )

    @mcp.tool(annotations={"title": "Quantize piano-roll notes", **_WR})
    def fl_piano_quantize(
        grid_bars: Annotated[
            float, Field(gt=0, description="Snap grid in bars: 0.0625=1/16, 0.125=1/8, 0.25=1/4.")
        ] = 0.0625,
        snap_ends: Annotated[
            bool, Field(description="Also snap note lengths to the grid.")
        ] = False,
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget before quantizing."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before quantizing."),
        ] = None,
    ) -> dict:
        """Quantize the notes in the active Piano roll.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; note readback to MCP remains API-limited.
        """
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_quantize",
            params={
                "grid_bars": float(grid_bars),
                "snap_ends": bool(snap_ends),
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                quantize=float(grid_bars),
                snap_ends=snap_ends,
                channel=channel,
                pattern=pattern,
            ),
        )

    @mcp.tool(annotations={"title": "Transpose notes in Piano roll", **_WR})
    def fl_piano_transpose(
        semitones: Annotated[
            int,
            Field(description="Number of semitones to shift notes."),
        ],
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget before transposing."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before transposing."),
        ] = None,
    ) -> dict:
        """Transpose all notes in the active pattern's Piano roll.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; note readback to MCP remains API-limited.
        """
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_transpose",
            params={"semitones": semitones, **_target_payload(channel, pattern)},
            apply=lambda: bridge.apply_notes(
                [], trigger=True, transpose=semitones, channel=channel, pattern=pattern
            ),
        )

    @mcp.tool(annotations={"title": "Duplicate Piano roll notes forward", **_WR})
    def fl_piano_duplicate(
        offset_bars: Annotated[
            float,
            Field(gt=0.0, description="How far forward to duplicate notes, in bars."),
        ] = 1.0,
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget before duplicating."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before duplicating."),
        ] = None,
    ) -> dict:
        """Duplicate all notes in the active Piano roll forward by a bar offset.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; note readback to MCP remains API-limited.
        """
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_duplicate",
            params={"offset_bars": float(offset_bars), **_target_payload(channel, pattern)},
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                duplicate_bars=float(offset_bars),
                channel=channel,
                pattern=pattern,
            ),
        )

    @mcp.tool(annotations={"title": "Apply Piano roll velocity ramp", **_WR})
    def fl_piano_velocity_ramp(
        start: Annotated[float, Field(ge=0.0, le=1.0, description="Start velocity 0..1.")],
        end: Annotated[float, Field(ge=0.0, le=1.0, description="End velocity 0..1.")],
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget before editing."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before editing."),
        ] = None,
    ) -> dict:
        """Apply a linear velocity ramp over note order in the active Piano roll.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; note readback to MCP remains API-limited.
        """
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_velocity_ramp",
            params={"start": float(start), "end": float(end), **_target_payload(channel, pattern)},
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                velocity_ramp=(float(start), float(end)),
                channel=channel,
                pattern=pattern,
            ),
        )

    @mcp.tool(annotations={"title": "Probe Piano roll return channel", **_RO})
    def fl_piano_probe_return_channel() -> dict:
        """Report current Piano roll note-readback capability and known limitations.

        Safety: Read-Only.
        """
        return {
            "ok": True,
            "readback_available": False,
            "status": "api-limited",
            "reason": (
                "Piano Roll scripts can read notes locally, but there is no verified, "
                "safe return channel back to the MCP server in this branch."
            ),
            "recommended_path": (
                "Use write tools with undo-backed rollback. Treat note readback as probe-only "
                "until a version-stable return channel is implemented."
            ),
        }

    @mcp.tool(annotations={"title": "Add Piano roll marker", **_WR})
    def fl_piano_add_marker(
        time_bars: Annotated[float, Field(ge=0.0, description="Marker position in bars.")],
        name: Annotated[str, Field(min_length=1, description="Marker label.")],
        mode: Annotated[int, Field(description="Marker mode/type integer.", ge=0)] = 0,
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget first."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before adding marker."),
        ] = None,
    ) -> dict:
        """Add one marker in the active Piano roll.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; marker readback to MCP remains API-limited.
        """
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_add_marker",
            params={
                "time_bars": float(time_bars),
                "name": name,
                "mode": int(mode),
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                marker_add={"time_bars": float(time_bars), "name": name, "mode": int(mode)},
                channel=channel,
                pattern=pattern,
            ),
        )

    @mcp.tool(annotations={"title": "Add Piano roll time-signature marker", **_WR})
    def fl_piano_add_time_signature_marker(
        time_bars: Annotated[float, Field(ge=0.0, description="Marker position in bars.")],
        numerator: Annotated[int, Field(ge=1, description="Time-signature numerator.")],
        denominator: Annotated[int, Field(ge=1, description="Time-signature denominator.")],
        name: Annotated[
            str, Field(description="Optional marker label, defaults to 'Time Signature'.")
        ] = "Time Signature",
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget first."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before adding marker."),
        ] = None,
    ) -> dict:
        """Add a time-signature marker in the active Piano roll.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; marker readback to MCP remains API-limited.
        """
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_add_time_signature_marker",
            params={
                "time_bars": float(time_bars),
                "numerator": int(numerator),
                "denominator": int(denominator),
                "name": name,
                **_target_payload(channel, pattern),
            },
            apply=lambda: bridge.apply_notes(
                [],
                trigger=True,
                marker_add={
                    "time_bars": float(time_bars),
                    "name": name,
                    "mode": 8,
                    "ts_num": int(numerator),
                    "ts_den": int(denominator),
                },
                channel=channel,
                pattern=pattern,
            ),
        )

    @mcp.tool(annotations={"title": "Clear Piano roll markers", **_WR})
    def fl_piano_clear_markers(
        channel: Annotated[
            int | None,
            Field(ge=0, description="Optional channel-rack index to retarget first."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional FL pattern index to select before clearing markers."),
        ] = None,
    ) -> dict:
        """Clear all markers in the active Piano roll.

        Safety: Write-Safe with Rollback. The generated Piano Roll script uses
        FL undo for rollback; marker readback to MCP remains API-limited.
        """
        bridge = get_bridge()
        _ensure_piano_roll(bridge, channel, pattern)
        return safety.safe_piano_roll_write(
            bridge,
            tool="piano_clear_markers",
            params=_target_payload(channel, pattern),
            apply=lambda: bridge.apply_notes(
                [], trigger=True, marker_clear=True, channel=channel, pattern=pattern
            ),
        )

    @mcp.tool(annotations={"title": "Get notes in active Piano roll (API Limited)", **_RO})
    def fl_piano_get_notes() -> dict:
        """Read back notes from the Piano roll (API Limited -- returns error).

        Safety: Read-Only.
        """
        return {
            "ok": False,
            "error": "Piano Roll readback to the MCP server is currently api-limited.",
            "details": (
                "FL Studio's Python controller script API does not expose any methods to read "
                "back notes from a pattern, and the Piano Roll script sandbox has no communication "
                "channel back to the MIDI/MCP server. Note operations are write-only."
            ),
        }
