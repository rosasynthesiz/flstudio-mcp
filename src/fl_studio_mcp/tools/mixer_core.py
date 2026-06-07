"""Phase 1 MCP tools.

- Read:   fl_get_project_state, fl_get_mixer_state, fl_get_channel_state
- Write:  fl_set_mixer_{volume,pan,mute,solo,name}, fl_set_channel_{volume,pan,mute,solo}
- Safety: fl_take_snapshot, fl_rollback_last_change, fl_set_dry_run

All writes route through ``safety.safe_write`` (snapshot -> log -> execute ->
read back), honor dry-run, and are individually rollback-able.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from ..music import levels
from .targets import mixer_track_error


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

    # ---- reads ----------------------------------------------------------
    @mcp.tool(annotations={"title": "Get project state", **_RO})
    def fl_get_project_state() -> dict:
        """Tempo, transport state, pattern/channel/mixer counts.

        Safety: Read-Only.
        """
        return get_bridge().call(protocol.CMD_GET_PROJECT_STATE)

    @mcp.tool(annotations={"title": "Get mixer state", **_RO})
    def fl_get_mixer_state() -> dict:
        """All mixer tracks (index, name, volume, pan, mute, solo). Names in
        this overview are truncated; use a single-track read for the full name.

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_MIXER_LIST_TRACKS, "tracks")

    @mcp.tool(annotations={"title": "Get channel state", **_RO})
    def fl_get_channel_state() -> dict:
        """All channel-rack channels (index, name, volume, pan, mute, solo).

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_CHANNEL_LIST, "channels")

    # ---- mixer writes ---------------------------------------------------
    @mcp.tool(annotations={"title": "Set mixer track volume", **_WR})
    def fl_set_mixer_volume(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
        value: Annotated[float, Field(description="Volume; normalized 0..1 (0.8=unity) or dB.")],
        unit: Annotated[str, Field(description="'normalized' or 'db'.")] = "normalized",
    ) -> dict:
        """Set a mixer track volume. unit='db' uses 0.8=unity (0 dB).

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer volume write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_volume",
            scope=f"mixer_track:{track}",
            command=protocol.CMD_MIXER_SET_VOLUME,
            params={"track": track, "value": value, "unit": unit},
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_VOLUME,
                "params": {"track": track, "value": b["vol_norm"], "unit": "normalized"},
            },
        )

    @mcp.tool(annotations={"title": "Set mixer track pan", **_WR})
    def fl_set_mixer_pan(
        track: Annotated[int, Field(ge=0)],
        value: Annotated[float, Field(ge=-1.0, le=1.0, description="-1 left .. +1 right.")],
    ) -> dict:
        """Set a mixer track's pan position (-1 left .. +1 right).

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer pan write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_pan",
            scope=f"mixer_track:{track}",
            command=protocol.CMD_MIXER_SET_PAN,
            params={"track": track, "value": value},
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_PAN,
                "params": {"track": track, "value": b["pan"]},
            },
        )

    @mcp.tool(annotations={"title": "Set mixer track mute", **_WR})
    def fl_set_mixer_mute(track: Annotated[int, Field(ge=0)], state: bool) -> dict:
        """Mute or unmute a mixer track (state=True mutes).

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer mute write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_mute",
            scope=f"mixer_track:{track}",
            command=protocol.CMD_MIXER_SET_MUTE,
            params={"track": track, "state": state},
            verify=("mute", state),
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_MUTE,
                "params": {"track": track, "state": b["mute"]},
            },
        )

    @mcp.tool(annotations={"title": "Set mixer track solo", **_WR})
    def fl_set_mixer_solo(track: Annotated[int, Field(ge=0)], state: bool) -> dict:
        """Solo or unsolo a mixer track (state=True solos).

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer solo write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_solo",
            scope=f"mixer_track:{track}",
            command=protocol.CMD_MIXER_SET_SOLO,
            params={"track": track, "state": state},
            verify=("solo", state),
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_SOLO,
                "params": {"track": track, "state": b["solo"]},
            },
        )

    @mcp.tool(annotations={"title": "Set mixer track name", **_WR})
    def fl_set_mixer_name(track: Annotated[int, Field(ge=0)], name: str) -> dict:
        """Rename a mixer track.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer name write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_name",
            scope=f"mixer_track:{track}",
            command=protocol.CMD_MIXER_SET_NAME,
            params={"track": track, "name": name},
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_NAME,
                "params": {"track": track, "name": b["name"]},
            },
        )

    # ---- channel writes -------------------------------------------------
    @mcp.tool(annotations={"title": "Set channel volume", **_WR})
    def fl_set_channel_volume(
        channel: Annotated[int, Field(ge=0)],
        value: Annotated[float, Field(description="Normalized 0..1 (0.8=unity) or dB.")],
        unit: Annotated[str, Field(description="'normalized' or 'db'.")] = "normalized",
    ) -> dict:
        """Set a channel-rack channel's volume. unit='db' uses 0.8=unity (0 dB).

        Safety: Write-Safe with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="channel_set_volume",
            scope=f"channel:{channel}",
            command=protocol.CMD_CHANNEL_SET_VOLUME,
            params={"channel": channel, "value": value, "unit": unit},
            build_restore=lambda b: {
                "command": protocol.CMD_CHANNEL_SET_VOLUME,
                "params": {"channel": channel, "value": b["vol_norm"], "unit": "normalized"},
            },
        )

    @mcp.tool(annotations={"title": "Set channel pan", **_WR})
    def fl_set_channel_pan(
        channel: Annotated[int, Field(ge=0)],
        value: Annotated[float, Field(ge=-1.0, le=1.0)],
    ) -> dict:
        """Set a channel-rack channel's pan position (-1 left .. +1 right).

        Safety: Write-Safe with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="channel_set_pan",
            scope=f"channel:{channel}",
            command=protocol.CMD_CHANNEL_SET_PAN,
            params={"channel": channel, "value": value},
            build_restore=lambda b: {
                "command": protocol.CMD_CHANNEL_SET_PAN,
                "params": {"channel": channel, "value": b["pan"]},
            },
        )

    @mcp.tool(annotations={"title": "Set channel mute", **_WR})
    def fl_set_channel_mute(channel: Annotated[int, Field(ge=0)], state: bool) -> dict:
        """Mute or unmute a channel-rack channel (state=True mutes).

        Safety: Write-Safe with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="channel_set_mute",
            scope=f"channel:{channel}",
            command=protocol.CMD_CHANNEL_SET_MUTE,
            params={"channel": channel, "state": state},
            verify=("mute", state),
            build_restore=lambda b: {
                "command": protocol.CMD_CHANNEL_SET_MUTE,
                "params": {"channel": channel, "state": b["mute"]},
            },
        )

    @mcp.tool(annotations={"title": "Set channel solo", **_WR})
    def fl_set_channel_solo(channel: Annotated[int, Field(ge=0)], state: bool) -> dict:
        """Solo or unsolo a channel-rack channel (state=True solos).

        Safety: Write-Safe with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="channel_set_solo",
            scope=f"channel:{channel}",
            command=protocol.CMD_CHANNEL_SET_SOLO,
            params={"channel": channel, "state": state},
            verify=("solo", state),
            build_restore=lambda b: {
                "command": protocol.CMD_CHANNEL_SET_SOLO,
                "params": {"channel": channel, "state": b["solo"]},
            },
        )

    # ---- mixer pack v2 (phase 2) ----------------------------------------
    @mcp.tool(annotations={"title": "List mixer tracks", **_RO})
    def fl_mixer_list_tracks() -> dict:
        """List all mixer tracks (index, name, volume, pan, mute, solo).

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_MIXER_LIST_TRACKS, "tracks")

    @mcp.tool(annotations={"title": "Get mixer track details", **_RO})
    def fl_mixer_get_track(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
    ) -> dict:
        """Get details for a single mixer track.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer track read")
        if error is not None:
            return error
        return bridge.call(protocol.CMD_MIXER_GET_TRACK, {"index": track})

    @mcp.tool(annotations={"title": "Set mixer track volume", **_WR})
    def fl_mixer_set_volume(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
        value: Annotated[float, Field(description="Volume; normalized 0..1 (0.8=unity) or dB.")],
        unit: Annotated[str, Field(description="'normalized' or 'db'.")] = "normalized",
    ) -> dict:
        """Set a mixer track volume. unit='db' uses 0.8=unity (0 dB).

        Safety: Write-Safe with Rollback.
        """
        return fl_set_mixer_volume(track=track, value=value, unit=unit)

    @mcp.tool(annotations={"title": "Set mixer track pan", **_WR})
    def fl_mixer_set_pan(
        track: Annotated[int, Field(ge=0)],
        value: Annotated[float, Field(ge=-1.0, le=1.0, description="-1 left .. +1 right.")],
    ) -> dict:
        """Set a mixer track's pan position (-1 left .. +1 right).

        Safety: Write-Safe with Rollback.
        """
        return fl_set_mixer_pan(track=track, value=value)

    @mcp.tool(annotations={"title": "Set mixer track mute", **_WR})
    def fl_mixer_set_mute(track: Annotated[int, Field(ge=0)], state: bool) -> dict:
        """Mute or unmute a mixer track (state=True mutes).

        Safety: Write-Safe with Rollback.
        """
        return fl_set_mixer_mute(track=track, state=state)

    @mcp.tool(annotations={"title": "Set mixer track solo", **_WR})
    def fl_mixer_set_solo(track: Annotated[int, Field(ge=0)], state: bool) -> dict:
        """Solo or unsolo a mixer track (state=True solos).

        Safety: Write-Safe with Rollback.
        """
        return fl_set_mixer_solo(track=track, state=state)

    @mcp.tool(annotations={"title": "Select mixer track", **_WR})
    def fl_mixer_select_track(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
    ) -> dict:
        """Select a mixer track to drive UI focus; rollback restores the previous selection.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer track selection")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="mixer_select_track",
            scope="mixer_selection",
            command=protocol.CMD_MIXER_SELECT_TRACK,
            params={"track": track},
            verify=("track", track),
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SELECT_TRACK,
                "params": {"track": b["track"]},
            },
        )

    @mcp.tool(annotations={"title": "Get mixer track routing", **_RO})
    def fl_mixer_get_route(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
    ) -> dict:
        """Which destination tracks this mixer track sends to:
        {track, name, routes_to:[{dst, dst_name, level?}]}.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer routing read")
        if error is not None:
            return error
        return bridge.call(protocol.CMD_MIXER_GET_ROUTING, {"track": track})

    @mcp.tool(annotations={"title": "Set mixer routing (src -> dst)", **_WR})
    def fl_mixer_set_route(
        src: Annotated[int, Field(ge=0, description="Source mixer track.")],
        dst: Annotated[int, Field(ge=0, description="Destination mixer track (0 = Master).")],
        enabled: Annotated[bool, Field(description="True = route on, False = off.")] = True,
    ) -> dict:
        """Enable/disable a send from src to dst; rollback restores the prior route state.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        for track, purpose in ((src, "mixer route source"), (dst, "mixer route destination")):
            error = mixer_track_error(bridge, track, purpose=purpose)
            if error is not None:
                return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_route",
            scope=f"route:{src}:{dst}",
            command=protocol.CMD_MIXER_SET_ROUTE,
            params={"src": src, "dst": dst, "enabled": enabled},
            verify=("enabled", enabled),
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_ROUTE,
                "params": {"src": src, "dst": dst, "enabled": b["enabled"]},
            },
        )

    @mcp.tool(annotations={"title": "Get mixer track levels", **_RO})
    def fl_mixer_get_levels(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
        samples: Annotated[int, Field(ge=1, le=100, description="Reads over ~samples*100ms.")] = 20,
    ) -> dict:
        """Measure a mixer track's level by sampling meter peaks over a short window.
        {track, playing, avg_db, peak_db, n_reads}

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer level read")
        if error is not None:
            return error
        return levels.measure_track_level(bridge, track, samples=samples)

    @mcp.tool(annotations={"title": "Set mixer track stereo separation", **_WR})
    def fl_mixer_set_stereo_separation(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
        value: Annotated[
            float,
            Field(
                ge=-1.0,
                le=1.0,
                description="Stereo separation: -1.0 mono to 1.0 separated.",
            ),
        ],
    ) -> dict:
        """Set a mixer track's stereo separation (-1.0 mono .. 1.0 fully separated).

        Safety: Write-Safe with Rollback. Some FL builds execute this command
        without persistent readback; safe_write prevents unverified success.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="mixer stereo separation write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="mixer_set_stereo_separation",
            scope=f"mixer_track:{track}",
            command=protocol.CMD_MIXER_SET_STEREO_SEP,
            params={"track": track, "value": value},
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_STEREO_SEP,
                "params": {"track": track, "value": b["stereo_sep"]},
            },
        )

    # ---- safety ---------------------------------------------------------
    @mcp.tool(annotations={"title": "Take snapshot", **_RO, "safetyClass": "server-state"})
    def fl_take_snapshot(
        scope: Annotated[
            str,
            Field(description="'mixer_track:N' | 'channel:N' | 'mixer_all' | 'channels_all'"),
        ],
    ) -> dict:
        """Read current state for a scope for before/after diffing.

        Safety: Server-State. This reads FL and uses the MCP safety snapshot
        machinery, but does not mutate FL project state.
        """
        return safety.take_snapshot(get_bridge(), scope)

    @mcp.tool(annotations={"title": "Get change history", **_RO})
    def fl_get_change_history(
        limit: Annotated[
            int,
            Field(ge=1, le=50, description="Number of recent changes to return."),
        ] = 10,
        include_payload: Annotated[
            bool,
            Field(description="Include full before/after/restore payloads."),
        ] = False,
    ) -> dict:
        """Return recent MCP-managed changes. Read-only; does not touch FL.

        Safety: Read-Only.
        """
        return safety.change_history(limit, include_payload=include_payload)

    @mcp.tool(annotations={"title": "Get change log summary", **_RO})
    def fl_get_change_log_summary(
        limit: Annotated[
            int,
            Field(ge=1, le=50, description="Number of recent changes to summarize."),
        ] = 10,
    ) -> dict:
        """Return a human-readable markdown summary table of recent changes to easily see rollback IDs.

        Safety: Read-Only.
        """
        history = safety.change_history(limit, include_payload=False).get("history", [])

        if not history:
            return {"summary": "No changes recorded."}

        markdown = "| ID | Time | Tool | Unit | Batch? |\n|---|---|---|---|---|\n"
        for h in history:
            ts = h.get("ts", 0)
            id_ = h.get("change_id", "?")
            tool = h.get("tool", "?")
            unit = h.get("rollback_unit", "")
            is_batch = h.get("is_group", False)

            markdown += f"| `{id_}` | {ts} | {tool} | {unit} | {'Yes' if is_batch else 'No'} |\n"

        return {
            "markdown_table": markdown,
            "note": "Use fl_rollback_change(change_id) to undo the most recent valid change.",
        }

    @mcp.tool(
        annotations={
            "title": "Export change log",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "external-write",
        }
    )
    def fl_export_change_log(
        output_path: Annotated[
            str | None,
            Field(
                description="Optional JSON export path. Defaults to the live jsonl changelog path."
            ),
        ] = None,
        include_payload: Annotated[
            bool,
            Field(description="Include full before/after/restore payloads."),
        ] = True,
    ) -> dict:
        """Export or locate the server-side MCP changelog. Does not touch FL.

        Safety: External-Write. This may write a JSON file on disk, but it does
        not mutate FL project state.
        """
        return safety.export_change_log(output_path, include_payload=include_payload)

    @mcp.tool(
        annotations={
            "title": "Rollback last change",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "server-state",
        }
    )
    def fl_rollback_last_change() -> dict:
        """Undo the most recent write by replaying its pre-change snapshot.

        Safety: Server-State. This is the MCP rollback path for prior
        write-safe changes and only operates from recorded restore payloads.
        """
        return safety.rollback_last_change(get_bridge())

    @mcp.tool(
        annotations={
            "title": "Rollback change by id",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
            "safetyClass": "server-state",
        }
    )
    def fl_rollback_change(
        change_id: Annotated[str, Field(description="Change id from fl_get_change_history.")],
    ) -> dict:
        """Rollback a change by id.

        Only the latest entry is accepted to avoid unsafe non-LIFO rollback.

        Safety: Server-State. This is the MCP rollback path for prior
        write-safe changes and only permits LIFO rollback by change id.
        """
        return safety.rollback_change(get_bridge(), change_id)

    @mcp.tool(
        annotations={
            "title": "Set dry-run mode",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
            "safetyClass": "server-state",
        }
    )
    def fl_set_dry_run(enabled: bool) -> dict:
        """When on, write tools return a 'planned' preview without changing FL.

        Safety: Server-State. This toggles MCP runtime state only.
        """
        return safety.set_dry_run(enabled)
