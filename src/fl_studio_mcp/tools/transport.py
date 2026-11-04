"""Transport tools — Phase 0 / Phase 1.

Maps the FL Studio ``transport`` and ``mixer`` (for tempo) modules to MCP tools.
Tempo lives on the mixer module in FL's API, but musicians think of it as a
transport concept so we expose it here for discoverability.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import FLCommandFailed, FLNotRunning, FLTimeout, get_bridge


def register(mcp: FastMCP) -> None:
    """Attach every tool in this module to the given FastMCP instance."""

    @mcp.tool(
        annotations={
            "title": "Ping FL Studio",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fl_ping() -> dict:
        """Check that FL Studio is running and the controller script is loaded.

        Returns the controller's reported FL Studio version, the age of the
        last heartbeat in seconds, and the MIDI port names in use. Call this
        first when something seems wrong.
        """
        bridge = get_bridge()
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
        # Round-trip a ping so we also confirm the request path is healthy.
        data = bridge.call(protocol.CMD_PING)
        return {
            "alive": True,
            "heartbeat_age_seconds": round(age, 2),
            **port_info,
            **data,
        }

    @mcp.tool(
        annotations={
            "title": "Get tempo (BPM)",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fl_get_tempo() -> dict:
        """Return the current FL Studio project tempo in beats per minute."""
        data = _safe_call(protocol.CMD_GET_TEMPO)
        return {"bpm": data["bpm"]}

    @mcp.tool(
        annotations={
            "title": "Set tempo (BPM)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fl_set_tempo(
        bpm: Annotated[float, Field(ge=10.0, le=999.0, description="Target tempo in BPM, FL accepts 10-999.")],
    ) -> dict:
        """Set the FL Studio project tempo. Range is 10-999 BPM (FL's own limits)."""
        data = _safe_call(protocol.CMD_SET_TEMPO, {"bpm": float(bpm)})
        if data.get("dry_run"):
            return data
        return {"bpm": data["bpm"]}

    @mcp.tool(
        annotations={
            "title": "Play",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fl_play() -> dict:
        """Start playback. Idempotent — calling while already playing is a no-op."""
        return _safe_call(protocol.CMD_PLAY)

    @mcp.tool(
        annotations={
            "title": "Stop",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fl_stop() -> dict:
        """Stop playback. Idempotent."""
        return _safe_call(protocol.CMD_STOP)

    @mcp.tool(
        annotations={
            "title": "Toggle play",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def fl_toggle_play() -> dict:
        """Toggle between play and stop, mirroring the spacebar in FL."""
        return _safe_call(protocol.CMD_TOGGLE_PLAY)

    @mcp.tool(
        annotations={
            "title": "Toggle record",
            "readOnlyHint": False,
            "destructiveHint": True,  # Recording can overwrite material.
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    def fl_record() -> dict:
        """Toggle FL Studio's record-arm state."""
        return _safe_call(protocol.CMD_RECORD)

    @mcp.tool(
        annotations={
            "title": "Get play state",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fl_get_play_state() -> dict:
        """Return whether FL is currently playing and / or recording."""
        return _safe_call(protocol.CMD_GET_PLAY_STATE)

    @mcp.tool(
        annotations={
            "title": "Get song position (beats)",
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fl_get_song_position() -> dict:
        """Return the current playhead position in beats from the song start."""
        return _safe_call(protocol.CMD_GET_SONG_POS)

    @mcp.tool(
        annotations={
            "title": "Set song position (beats)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def fl_set_song_position(
        beats: Annotated[float, Field(ge=0.0, description="Position in beats from song start.")],
    ) -> dict:
        """Move the playhead to the given beat position."""
        return _safe_call(protocol.CMD_SET_SONG_POS, {"beats": float(beats)})


def _safe_call(command: str, params: dict | None = None):
    """Call the bridge and translate transport errors into MCP-friendly messages."""
    if command in (protocol.CMD_SET_TEMPO, protocol.CMD_SET_SONG_POS,
                   protocol.CMD_PLAY, protocol.CMD_STOP, protocol.CMD_TOGGLE_PLAY,
                   protocol.CMD_RECORD):
        preview = safety.preview_write(tool=command, command=command, params=params)
        if preview is not None:
            return preview
    try:
        return get_bridge().call(command, params)
    except FLNotRunning as e:
        # FL not running is the single most common failure mode. Surface it
        # clearly so the LLM can prompt the user to start FL rather than
        # retrying blindly.
        raise RuntimeError(str(e)) from e
    except FLTimeout as e:
        raise RuntimeError(
            f"{e}. Try fl_ping to confirm the controller is alive."
        ) from e
    except FLCommandFailed as e:
        raise RuntimeError(f"FL Studio rejected the command: {e}") from e
