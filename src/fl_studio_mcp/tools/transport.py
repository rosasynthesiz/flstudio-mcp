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

        Returns `status` (READY, FL_CLOSED, CONTROLLER_MISSING, NO_HEARTBEAT,
        VERSION_MISMATCH, ...) and `next`: the one step that fixes it. Call
        this first, and again whenever another tool fails.
        """
        from .. import setup_cli

        report = setup_cli.diagnose(wait=3.0)
        out = {
            "alive": report["status"] == "READY",
            "status": report["status"],
            "next": report["next"],
            "server_version": report["server_version"],
        }
        if report.get("fl_version"):
            out["fl_version"] = report["fl_version"]
        if out["alive"]:
            bridge = get_bridge()
            age = bridge.heartbeat_age()
            out["heartbeat_age_seconds"] = round(age, 2) if age is not None else None
            out["protocol_version"] = protocol.PROTOCOL_VERSION
        else:
            # Kept for older prompts that read `reason`.
            out["reason"] = report["next"]
            out["failed_check"] = next(
                (c for c in report["checks"] if c["ok"] is False), None)
        return out

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
        """Set the FL Studio project tempo. Range is 10-999 BPM (FL's own limits).

        Reversible like every other write: fl_rollback_last_change restores
        the tempo that was set before.
        """
        try:
            data = safety.safe_write(
                get_bridge(), tool="set_tempo", scope="tempo",
                command=protocol.CMD_SET_TEMPO, params={"bpm": float(bpm)},
                build_restore=lambda before: {"command": protocol.CMD_SET_TEMPO,
                                              "params": {"bpm": before["bpm"]}})
        except FLNotRunning as e:
            raise RuntimeError(str(e)) from e
        except FLTimeout as e:
            raise RuntimeError(f"{e}. Try fl_ping to confirm the controller is alive.") from e
        except FLCommandFailed as e:
            raise RuntimeError(f"FL Studio rejected the command: {e}") from e
        if data.get("dry_run"):
            return data
        return {"bpm": data["after"]["bpm"], "previous_bpm": data["before"]["bpm"]}

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
