"""Transport tools — Phase 0 / Phase 1.

Maps the FL Studio ``transport`` and ``mixer`` (for tempo) modules to MCP tools.
Tempo lives on the mixer module in FL's API, but musicians think of it as a
transport concept so we expose it here for discoverability.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import operations, protocol, safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, get_bridge


def register(mcp: FastMCP) -> None:
    """Attach every tool in this module to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Ping FL Studio",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "read-only",
        },
    )
    def fl_ping() -> dict:
        """Check that FL Studio is running and the controller script is loaded.

        Returns the controller's reported FL Studio version, the age of the
        last heartbeat in seconds, and the MIDI port names in use. Call this
        first when something seems wrong.

        Safety: Read-Only.
        """
        return _ping_bridge(get_bridge())

    @mcp.tool(
        annotations={
            "title": "Transport domain operation",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_transport(
        action: Annotated[
            str,
            Field(
                description=(
                    "Transport action: ping, get_tempo, set_tempo, get_play_state, "
                    "play, stop, toggle_play, record, get_song_position, set_song_position, "
                    "get_time_signature, or set_time_signature."
                )
            ),
        ],
        params: Annotated[
            dict | None,
            Field(description="Action parameters. Use {} or omit for parameterless actions."),
        ] = None,
    ) -> dict:
        """Run one consolidated transport operation through the operation registry.

        Read-only actions call the bridge after registry validation. Persistent
        writes, currently tempo and time signature, use the safety layer:
        snapshot -> write -> readback -> changelog -> rollback restore. Runtime
        controls such as play, stop, record, and song-position moves are
        transient and do not persist project state.

        Safety: Write-Safe with Rollback for persistent writes; Transient
        Runtime Control for playback controls; Read-Only for transport reads.
        """
        if action == "ping":
            return _ping_bridge(get_bridge())

        try:
            prepared = operations.prepare_operation("transport", action, params or {})
        except operations.OperationValidationError as exc:
            raise ValueError(str(exc)) from exc

        bridge = get_bridge()
        if prepared.safety_class == "write-safe":
            return safety.safe_write(
                bridge,
                **prepared.safe_write_kwargs(tool=f"transport_{prepared.action}"),
            )
        if prepared.safety_class in {"read-only", "transient"}:
            return _bridge_call(
                bridge,
                prepared.command.command,
                prepared.command.params,
            )
        raise ValueError(f"unsupported transport safety class: {prepared.safety_class}")

    @mcp.tool(
        annotations={
            "title": "Get tempo (BPM)",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "read-only",
        },
    )
    def fl_get_tempo() -> dict:
        """Return the current FL Studio project tempo in beats per minute.

        Safety: Read-Only.
        """
        data = _safe_call(protocol.CMD_GET_TEMPO)
        return {"bpm": data["bpm"]}

    @mcp.tool(
        annotations={
            "title": "Set tempo (BPM)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_set_tempo(
        bpm: Annotated[
            float, Field(ge=10.0, le=999.0, description="Target tempo in BPM, FL accepts 10-999.")
        ],
    ) -> dict:
        """Set the FL Studio project tempo. Snapshot + readback; rollback restores BPM.

        Safety: Write-Safe with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="set_tempo",
            scope="tempo",
            command=protocol.CMD_SET_TEMPO,
            params={"bpm": float(bpm)},
            build_restore=lambda b: {
                "command": protocol.CMD_SET_TEMPO,
                "params": {"bpm": b["bpm"]},
            },
        )

    @mcp.tool(
        annotations={
            "title": "Play",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "transient",
        },
    )
    def fl_play() -> dict:
        """Start playback. Idempotent; calling while already playing is a no-op.

        Safety: Transient Runtime Control.
        """
        return _safe_call(protocol.CMD_PLAY)

    @mcp.tool(
        annotations={
            "title": "Stop",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "transient",
        },
    )
    def fl_stop() -> dict:
        """Stop playback. Idempotent.

        Safety: Transient Runtime Control.
        """
        return _safe_call(protocol.CMD_STOP)

    @mcp.tool(
        annotations={
            "title": "Toggle play",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "transient",
        },
    )
    def fl_toggle_play() -> dict:
        """Toggle between play and stop, mirroring the spacebar in FL.

        Safety: Transient Runtime Control.
        """
        return _safe_call(protocol.CMD_TOGGLE_PLAY)

    @mcp.tool(
        annotations={
            "title": "Toggle record",
            "readOnlyHint": False,
            "destructiveHint": True,  # Recording can overwrite material.
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "transient",
        },
    )
    def fl_record() -> dict:
        """Toggle FL Studio's record-arm state.

        Safety: Transient Runtime Control.
        """
        return _safe_call(protocol.CMD_RECORD)

    @mcp.tool(
        annotations={
            "title": "Get play state",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "read-only",
        },
    )
    def fl_get_play_state() -> dict:
        """Return whether FL is currently playing and / or recording.

        Safety: Read-Only.
        """
        return _safe_call(protocol.CMD_GET_PLAY_STATE)

    @mcp.tool(
        annotations={
            "title": "Get song position (beats)",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "read-only",
        },
    )
    def fl_get_song_position() -> dict:
        """Return the current playhead position in beats from the song start.

        Safety: Read-Only.
        """
        return _safe_call(protocol.CMD_GET_SONG_POS)

    @mcp.tool(
        annotations={
            "title": "Set song position (beats)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "transient",
        },
    )
    def fl_set_song_position(
        beats: Annotated[float, Field(ge=0.0, description="Position in beats from song start.")],
    ) -> dict:
        """Move the playhead to the given beat position.

        Safety: Transient Runtime Control.
        """
        return _safe_call(protocol.CMD_SET_SONG_POS, {"beats": float(beats)})

    @mcp.tool(
        annotations={
            "title": "Get time signature",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "read-only",
        },
    )
    def fl_get_time_signature() -> dict:
        """Return the current project time signature numerator and denominator.

        Safety: Read-Only.
        """
        return _safe_call(protocol.CMD_GET_TIME_SIG)

    @mcp.tool(
        annotations={
            "title": "Set time signature",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "write-safe",
        },
    )
    def fl_set_time_signature(
        numerator: Annotated[
            int, Field(ge=1, le=64, description="Time signature numerator (beats per bar).")
        ],
        denominator: Annotated[
            int,
            Field(description="Time signature denominator. Only 4 and 8 have safe readback."),
        ],
    ) -> dict:
        """Set the project time signature. Snapshot + readback; rollback restores it.

        Safety: Write-Safe with Rollback.
        """
        if denominator not in (4, 8):
            return {
                "ok": False,
                "api_limited": True,
                "error": "Only denominators 4 and 8 are enabled because FL readback is reliable there.",
            }
        return safety.safe_write(
            get_bridge(),
            tool="set_time_signature",
            scope="time_signature",
            command=protocol.CMD_SET_TIME_SIG,
            params={"numerator": int(numerator), "denominator": int(denominator)},
            build_restore=lambda b: {
                "command": protocol.CMD_SET_TIME_SIG,
                "params": {"numerator": b["numerator"], "denominator": b["denominator"]},
            },
        )


def _safe_call(command: str, params: dict | None = None):
    """Call the bridge and translate transport errors into MCP-friendly messages."""
    return _bridge_call(get_bridge(), command, params or {})


def _ping_bridge(bridge) -> dict:
    port_info = {
        "port_to_fl": protocol.port_to_fl_name(),
        "port_from_fl": protocol.port_from_fl_name(),
    }
    age = bridge.heartbeat_age()
    if age is None:
        return {
            "alive": False,
            "reason": "No heartbeat received. FL Studio is closed, the "
            "FLStudioMCP controller is not selected, or the "
            "loopMIDI / IAC output port number does not match "
            "the input port number in FL's MIDI Settings.",
            **port_info,
        }
    if age > protocol.HEARTBEAT_STALE_SECONDS:
        return {
            "alive": False,
            "reason": f"Heartbeat is {age:.1f}s old (stale > "
            f"{protocol.HEARTBEAT_STALE_SECONDS:.0f}s). FL may "
            f"be frozen or the controller stopped responding.",
            "heartbeat_age_seconds": round(age, 2),
            **port_info,
        }
    data = bridge.call(protocol.CMD_PING)
    return {
        "alive": True,
        "heartbeat_age_seconds": round(age, 2),
        **port_info,
        **data,
    }


def _bridge_call(bridge, command: str, params: dict | None = None):
    """Call a bridge and translate transport errors into MCP-friendly messages."""
    try:
        return bridge.call(command, params or {})
    except FLNotRunning as e:
        # FL not running is the single most common failure mode. Surface it
        # clearly so the LLM can prompt the user to start FL rather than
        # retrying blindly.
        raise RuntimeError(str(e)) from e
    except FLTimeout as e:
        raise RuntimeError(
            f"{e}. Try fl_transport(action='ping') to confirm the controller is alive."
        ) from e
    except FLCommandFailed as e:
        raise RuntimeError(f"FL Studio rejected the command: {e}") from e
