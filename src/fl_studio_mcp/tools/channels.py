"""Channel organizer tools.

This module contains channel-level organization primitives that are higher
level than the Phase 1 volume/pan/mute/solo setters but still small enough to
be audited and rolled back individually.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from .targets import mixer_track_error, no_free_mixer_track_response


def _looks_default_channel_name(name: str) -> bool:
    if not name:
        return True
    return name.startswith("Sampler") or name.startswith("Audio Clip")


def _target_restore(channel: int, before: dict) -> dict:
    previous = before.get("target_fx_track")
    if not isinstance(previous, int):
        raise RuntimeError("cannot build rollback: previous channel target is unknown")
    return {
        "command": protocol.CMD_CHANNEL_SET_TARGET,
        "params": {"channel": channel, "track": previous},
    }


def _steps_restore(channel: int, before: dict) -> dict:
    steps_list = []
    rel = before.get("release", [])
    mod = before.get("mod", [])
    pitch = before.get("pitch", [])
    for s in range(len(before.get("grid", []))):
        row = {
            "step": s,
            "value": before["grid"][s],
            "velocity": before["vel"][s],
            "pan": before["pan"][s],
            "shift": before["shift"][s],
            "repeat": before["rep"][s],
        }
        if s < len(rel) and rel[s] is not None:
            row["release"] = rel[s]
        if s < len(mod) and mod[s] is not None:
            row["mod"] = mod[s]
        if s < len(pitch) and pitch[s] is not None:
            row["pitch"] = pitch[s]
        steps_list.append(row)
    pattern = before.get("pattern")
    return {
        "command": protocol.CMD_CHANNEL_SET_STEPS,
        "params": {"channel": channel, "pattern": pattern, "steps": steps_list},
    }


def _needs_assignment(channel: dict, *, include_master: bool = True) -> bool:
    target = channel.get("target_fx_track")
    if not isinstance(target, int):
        return True
    return include_master and target == 0


def _is_default_mixer_name(index: int, name) -> bool:
    if index == 0:
        return False
    return (name or "") in ("", f"Insert {index}")


def _find_free_mixer_track(bridge, *, start_track: int = 1) -> int | None:
    try:
        res = bridge.call(protocol.CMD_MIXER_GET_FREE_TRACK, {"start": start_track})
        track = res.get("track")
        if isinstance(track, int) and track > 0:
            return track
    except Exception:
        pass

    # Fallback to manual scan by checking tracks directly (slower but bypasses bridge truncation limits)
    # We still need `targeted` and `incoming` to know which tracks are routed-to.
    routing = fetch_all_pages(bridge, protocol.CMD_MIXER_GET_ROUTING_ALL, "routing")
    channels = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")

    targeted = {
        c.get("target_mixer_track")
        for c in channels.get("channels", [])
        if isinstance(c.get("target_mixer_track"), int)
    }
    incoming: dict[int, list[int]] = {}
    for row in routing.get("routing", []):
        for route in row.get("routes_to", []):
            dst = route.get("dst")
            if isinstance(dst, int):
                incoming.setdefault(dst, []).append(row.get("i"))

    for track in range(start_track, 126):
        if track == 0 or track in targeted or incoming.get(track):
            continue
        try:
            name = bridge.call(protocol.CMD_MIXER_GET_TRACK, {"index": track}).get("name")
            if not _is_default_mixer_name(track, name):
                continue
            if bridge.call(protocol.CMD_PLUGIN_LIST, {"track": track}).get("slots"):
                continue
            return track
        except Exception:
            continue
    return None


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

    @mcp.tool(annotations={"title": "Get channel details", **_RO})
    def fl_get_channel_details(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
    ) -> dict:
        """Read full details for one channel, including type, color, and mixer target.

        Safety: Read-Only.
        """
        return get_bridge().call(protocol.CMD_CHANNEL_GET, {"index": channel})

    @mcp.tool(annotations={"title": "Detect channels needing mixer assignment", **_RO})
    def fl_detect_unassigned_channels(
        include_master: Annotated[
            bool,
            Field(description="Treat channels routed only to Master as assignment candidates."),
        ] = True,
    ) -> dict:
        """Find channels with no mixer target, or optionally channels still routed to Master.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        listed = fetch_all_pages(bridge, protocol.CMD_CHANNEL_LIST, "channels")
        candidates = []
        for item in listed.get("channels", []):
            detail = bridge.call(protocol.CMD_CHANNEL_GET, {"index": item.get("i", 0)})
            if _needs_assignment(detail, include_master=include_master):
                candidates.append(detail)
        return {"ok": True, "total": len(candidates), "channels": candidates}

    @mcp.tool(annotations={"title": "Set channel name", **_WR})
    def fl_set_channel_name(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        name: Annotated[str, Field(min_length=1, description="New channel name.")],
    ) -> dict:
        """Rename a channel. Snapshot + readback; rollback restores the prior name.

        Safety: Write-Safe with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="channel_set_name",
            scope=f"channel:{channel}",
            command=protocol.CMD_CHANNEL_SET_NAME,
            params={"channel": channel, "name": name},
            build_restore=lambda b: {
                "command": protocol.CMD_CHANNEL_SET_NAME,
                "params": {"channel": channel, "name": b["name"]},
            },
        )

    @mcp.tool(annotations={"title": "Set channel mixer target", **_WR})
    def fl_set_channel_mixer_track(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        mixer_track: Annotated[int, Field(ge=0, description="Target mixer track index.")],
    ) -> dict:
        """Route a channel to a mixer track. Rollback restores the previous target.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, mixer_track, purpose="channel mixer-target assignment")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="channel_set_target",
            scope=f"channel:{channel}",
            command=protocol.CMD_CHANNEL_SET_TARGET,
            params={"channel": channel, "track": mixer_track},
            verify=("target_fx_track", mixer_track),
            build_restore=lambda b: _target_restore(channel, b),
        )

    @mcp.tool(annotations={"title": "Assign channel to a free mixer track", **_WR})
    def fl_assign_channel_to_free_mixer_track(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        start_track: Annotated[int, Field(ge=1, description="First mixer track to consider.")] = 1,
    ) -> dict:
        """Find a default empty mixer track and route this channel to it.

        This does not rename or color the mixer track; it only changes the
        channel's mixer target so rollback remains one small restore.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        track = _find_free_mixer_track(bridge, start_track=start_track)
        if track is None:
            return no_free_mixer_track_response(bridge, start_track=start_track)
        result = safety.safe_write(
            bridge,
            tool="channel_assign_free_mixer_track",
            scope=f"channel:{channel}",
            command=protocol.CMD_CHANNEL_SET_TARGET,
            params={"channel": channel, "track": track},
            verify=("target_fx_track", track),
            build_restore=lambda b: _target_restore(channel, b),
        )
        return {"ok": True, "assigned_track": track, "result": result}

    @mcp.tool(annotations={"title": "Get channel step sequencer grid", **_RO})
    def fl_channel_get_grid(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        steps: Annotated[
            int,
            Field(ge=1, le=64, description="Number of steps to read."),
        ] = 64,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional pattern index. Defaults to current pattern."),
        ] = None,
    ) -> dict:
        """Read the step sequencer grid and parameters (velocity, pan, shift, repeat) for a channel.

        Safety: Read-Only.
        """
        params = {"channel": channel, "steps": steps}
        if pattern is not None:
            params["pattern"] = pattern
        return get_bridge().call(protocol.CMD_CHANNEL_GET_STEPS, params)

    @mcp.tool(annotations={"title": "Set step sequencer grid bit", **_WR})
    def fl_channel_set_grid_bit(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        step: Annotated[int, Field(ge=0, le=63, description="Zero-based step index.")],
        value: Annotated[bool, Field(description="Turn step on (True) or off (False).")],
        velocity: Annotated[
            float | None,
            Field(ge=0.0, le=1.0, description="Optional step velocity."),
        ] = None,
        pan: Annotated[
            float | None,
            Field(ge=-1.0, le=1.0, description="Optional step pan."),
        ] = None,
        shift: Annotated[
            float | None,
            Field(ge=0.0, le=1.0, description="Optional step shift/delay."),
        ] = None,
        repeat: Annotated[
            int | None,
            Field(ge=0, le=15, description="Optional step repeat count."),
        ] = None,
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional pattern index. Defaults to current pattern."),
        ] = None,
    ) -> dict:
        """Set or clear a single step sequencer step and its parameters.

        Safety: Write-Safe with Rollback.
        """
        params = {"step": step, "value": value}
        if velocity is not None:
            params["velocity"] = velocity
        if pan is not None:
            params["pan"] = pan
        if shift is not None:
            params["shift"] = shift
        if repeat is not None:
            params["repeat"] = repeat

        bridge = get_bridge()
        selected = bridge.call(protocol.CMD_PATTERN_SELECTED)
        pattern_index = int(pattern or selected["selected"])
        return safety.safe_write(
            bridge,
            tool="channel_set_grid_bit",
            scope=f"channel_steps:{channel}:{pattern_index}",
            command=protocol.CMD_CHANNEL_SET_STEPS,
            params={"channel": channel, "pattern": pattern_index, "steps": [params]},
            build_restore=lambda b: _steps_restore(channel, b),
            rollback_unit=f"step_grid_bit_ch{channel}_pat{pattern_index}",
        )

    @mcp.tool(annotations={"title": "Set one step sequencer parameter", **_WR})
    def fl_channel_set_step_param(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        step: Annotated[int, Field(ge=0, le=63, description="Zero-based step index.")],
        parameter: Annotated[
            str,
            Field(description="One of: velocity, pan, shift, repeat, release, mod, pitch."),
        ],
        value: Annotated[float, Field(description="Value for the selected parameter.")],
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional pattern index. Defaults to current pattern."),
        ] = None,
    ) -> dict:
        """Set one step parameter with rollback-safe snapshot/readback.

        Safety: Write-Safe with Rollback.
        """
        key = parameter.strip().lower()
        payload: dict[str, object] = {"step": step}
        if key in ("velocity", "vel"):
            payload["velocity"] = max(0.0, min(1.0, float(value)))
        elif key == "pan":
            payload["pan"] = max(-1.0, min(1.0, float(value)))
        elif key == "shift":
            payload["shift"] = max(0.0, min(1.0, float(value)))
        elif key == "repeat":
            payload["repeat"] = max(0, min(15, int(value)))
        elif key == "release":
            payload["release"] = max(0.0, min(1.0, float(value)))
        elif key == "mod":
            payload["mod"] = max(0.0, min(1.0, float(value)))
        elif key == "pitch":
            payload["pitch"] = int(value)
        else:
            raise ValueError(
                "parameter must be one of: velocity, pan, shift, repeat, release, mod, pitch"
            )

        bridge = get_bridge()
        selected = bridge.call(protocol.CMD_PATTERN_SELECTED)
        pattern_index = int(pattern or selected["selected"])
        return safety.safe_write(
            bridge,
            tool="channel_set_step_param",
            scope=f"channel_steps:{channel}:{pattern_index}",
            command=protocol.CMD_CHANNEL_SET_STEPS,
            params={"channel": channel, "pattern": pattern_index, "steps": [payload]},
            build_restore=lambda b: _steps_restore(channel, b),
            rollback_unit=f"step_param_ch{channel}_pat{pattern_index}",
        )

    @mcp.tool(annotations={"title": "Set step sequencer steps in batch", **_WR})
    def fl_channel_set_steps(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        steps: Annotated[
            list[dict],
            Field(description="Step dicts with step, value, velocity, pan, shift, repeat."),
        ],
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional pattern index. Defaults to current pattern."),
        ] = None,
    ) -> dict:
        """Set or clear multiple steps and parameters in a single batch.

        Safety: Write-Safe with Rollback.
        """
        validated_steps = []
        for s in steps:
            step_idx = s.get("step")
            if not isinstance(step_idx, int) or step_idx < 0 or step_idx > 63:
                raise ValueError("Each step dict must contain a valid 'step' index (0-63)")
            s_dict = {"step": step_idx}
            if "value" in s:
                s_dict["value"] = bool(s["value"])
            if "velocity" in s and s["velocity"] is not None:
                s_dict["velocity"] = max(0.0, min(1.0, float(s["velocity"])))
            if "pan" in s and s["pan"] is not None:
                s_dict["pan"] = max(-1.0, min(1.0, float(s["pan"])))
            if "shift" in s and s["shift"] is not None:
                s_dict["shift"] = max(0.0, min(1.0, float(s["shift"])))
            if "repeat" in s and s["repeat"] is not None:
                s_dict["repeat"] = max(0, min(15, int(s["repeat"])))
            if "release" in s and s["release"] is not None:
                s_dict["release"] = max(0.0, min(1.0, float(s["release"])))
            if "mod" in s and s["mod"] is not None:
                s_dict["mod"] = max(0.0, min(1.0, float(s["mod"])))
            if "pitch" in s and s["pitch"] is not None:
                s_dict["pitch"] = int(s["pitch"])
            validated_steps.append(s_dict)

        bridge = get_bridge()
        selected = bridge.call(protocol.CMD_PATTERN_SELECTED)
        pattern_index = int(pattern or selected["selected"])

        return safety.safe_write(
            bridge,
            tool="channel_set_steps",
            scope=f"channel_steps:{channel}:{pattern_index}",
            command=protocol.CMD_CHANNEL_SET_STEPS,
            params={"channel": channel, "pattern": pattern_index, "steps": validated_steps},
            build_restore=lambda b: _steps_restore(channel, b),
            rollback_unit=f"step_batch_ch{channel}_pat{pattern_index}",
        )

    @mcp.tool(annotations={"title": "Clear step sequencer grid", **_WR})
    def fl_channel_clear_grid(
        channel: Annotated[int, Field(ge=0, description="Channel-rack channel index.")],
        pattern: Annotated[
            int | None,
            Field(ge=1, description="Optional pattern index. Defaults to current pattern."),
        ] = None,
    ) -> dict:
        """Wipe all step sequencer steps for a channel in the current pattern.

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        selected = bridge.call(protocol.CMD_PATTERN_SELECTED)
        pattern_index = int(pattern or selected["selected"])
        current = bridge.call(
            protocol.CMD_CHANNEL_GET_STEPS,
            {"channel": channel, "pattern": pattern_index},
        )
        grid_len = len(current.get("grid", [])) or 64
        cleared_steps = [{"step": s, "value": False} for s in range(grid_len)]

        return safety.safe_write(
            bridge,
            tool="channel_clear_grid",
            scope=f"channel_steps:{channel}:{pattern_index}",
            command=protocol.CMD_CHANNEL_SET_STEPS,
            params={"channel": channel, "pattern": pattern_index, "steps": cleared_steps},
            build_restore=lambda b: _steps_restore(channel, b),
            rollback_unit=f"step_clear_ch{channel}_pat{pattern_index}",
        )

    # --- Phase 1: Channel Type & Audio Clip Intelligence ---

    @mcp.tool(annotations={"title": "Classify channel types", **_RO})
    def fl_classify_channels() -> dict:
        """Group all channels by their detected type (AudioClip, Sampler, GenPlug, etc).

        Safety: Read-Only.
        """
        bridge = get_bridge()
        chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")

        grouped = {}
        for c in chans.get("channels", []):
            ctype = c.get("type", {}).get("label", "unknown")
            grouped.setdefault(ctype, []).append(
                {
                    "channel": c.get("channel"),
                    "name": c.get("name"),
                    "target_mixer_track": c.get("target_mixer_track"),
                }
            )

        return {"summary": {k: len(v) for k, v in grouped.items()}, "groups": grouped}

    @mcp.tool(annotations={"title": "Inspect Audio Clips", **_RO})
    def fl_inspect_audio_clips() -> dict:
        """Find all Audio Clips and check if they are named, routed, colored, or too loud.

        Safety: Read-Only.
        Note: Cannot detect Stretch Mode or Normalize status due to API limits.
        """
        bridge = get_bridge()
        chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")

        audio_clips = []
        for c in chans.get("channels", []):
            if c.get("type", {}).get("label") == "audioclip":
                vol = c.get("vol", 0.78125)  # Default is around 78%
                target = c.get("target_mixer_track")

                issues = []
                if _looks_default_channel_name(c.get("name")):
                    issues.append("Unnamed")
                if not isinstance(target, int) or target == 0:
                    issues.append("Unrouted")
                if vol > 0.7:
                    issues.append(f"Loud (vol={round(vol, 2)})")

                audio_clips.append(
                    {
                        "channel": c.get("channel"),
                        "name": c.get("name"),
                        "target_mixer_track": target,
                        "volume": round(vol, 3),
                        "issues": issues,
                    }
                )

        return {"audio_clips": audio_clips, "count": len(audio_clips)}

    @mcp.tool(annotations={"title": "Plan Audio Clip Safe Defaults", **_RO})
    def fl_plan_audio_clip_safe_defaults() -> dict:
        """Generate a plan to apply safe defaults to all Audio Clips (lower volume, assign mixer track).

        Safety: Read-Only (Dry-run).
        """
        bridge = get_bridge()
        chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")

        plan = []
        for c in chans.get("channels", []):
            if c.get("type", {}).get("label") == "audioclip":
                actions = []
                # Target vol around 0.25 (-12dBish)
                if c.get("vol", 0.78) > 0.4:
                    actions.append({"action": "set_volume", "from": c.get("vol"), "to": 0.25})

                target = c.get("target_mixer_track")
                if not isinstance(target, int) or target == 0:
                    # In a real plan, we'd find a free track, but for now we just flag it
                    actions.append({"action": "route_to_free_mixer_track"})

                if actions:
                    plan.append(
                        {"channel": c.get("channel"), "name": c.get("name"), "actions": actions}
                    )

        return {
            "plan": plan,
            "manual_checklist": [
                "API LIMITATION: You must manually check if 'Normalize' is active on each clip.",
                "API LIMITATION: You must manually check if 'Stretch Mode' is set correctly (e.g. Stretch Pro) on each clip.",
            ],
        }

    @mcp.tool(annotations={"title": "Apply Audio Clip Safe Defaults", **_WR})
    def fl_apply_audio_clip_safe_defaults() -> dict:
        """Apply safe defaults to all Audio Clips (lower volume to 25%, assign to free mixer tracks).

        Safety: Write-Safe with Rollback.
        """
        bridge = get_bridge()
        chans = fetch_all_pages(bridge, protocol.CMD_CHANNEL_ROUTING_SUMMARY, "channels")

        writes = []
        assigned = []
        current_free_track = 1

        for c in chans.get("channels", []):
            if c.get("type", {}).get("label") == "audioclip":
                idx = c.get("channel")

                # 1. Lower volume if > 40%
                if c.get("vol", 0.78) > 0.4:
                    writes.append(
                        {
                            "snap_scope": f"channel:{idx}",
                            "command": protocol.CMD_CHANNEL_SET_VOLUME,
                            "params": {"channel": idx, "value": 0.25},
                            "restore": lambda b, ci=idx: {
                                "command": protocol.CMD_CHANNEL_SET_VOLUME,
                                "params": {"channel": ci, "value": b.get("vol", 0.78125)},
                            },
                        }
                    )

                # 2. Route if unrouted
                target = c.get("target_mixer_track")
                if not isinstance(target, int) or target == 0:
                    free_track = _find_free_mixer_track(bridge, start_track=current_free_track)
                    if free_track:
                        writes.append(
                            {
                                "snap_scope": f"channel:{idx}",
                                "command": protocol.CMD_CHANNEL_SET_TARGET,
                                "params": {"channel": idx, "track": free_track},
                                "restore": lambda b, ci=idx: _target_restore(ci, b),
                            }
                        )
                        assigned.append(f"Ch {idx} ({c.get('name')}) -> Mixer {free_track}")
                        current_free_track = free_track + 1

        if not writes:
            return {"status": "No audio clips needed safe defaults."}

        res = safety.safe_write_group(
            bridge,
            tool="apply_audio_clip_safe_defaults",
            scope="audio_clips",
            writes=writes,
            rollback_unit="audio_clip_safe_defaults",
        )
        res["manual_checklist"] = [
            "API LIMITATION: You must manually check if 'Normalize' is active on each clip.",
            "API LIMITATION: You must manually check if 'Stretch Mode' is set correctly (e.g. Stretch Pro) on each clip.",
        ]
        res["assignments"] = assigned
        return res
