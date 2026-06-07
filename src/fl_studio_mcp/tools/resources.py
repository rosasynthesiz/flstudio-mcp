"""MCP resources -- read-only project context the LLM assistant can pull WITHOUT a tool call.

All reuse existing (budget-paginated) reads, so no new heavy controller loops.
Kept COMPACT: summaries + counts, capped, with a note pointing to the detail
tool when a list is large. Every resource degrades gracefully if the bridge is
down (returns an {error} dict instead of throwing) so an auto-pull never breaks.
"""

from __future__ import annotations

from fastmcp import FastMCP

from .. import protocol
from ..connection import fetch_all_pages, get_bridge

_CAPS = {
    "channels": 24,
    "tracks": 28,
    "patterns": 80,
}

_DOMAIN_TOOLS = {
    "fl_transport": [
        "ping",
        "get_tempo",
        "set_tempo",
        "get_play_state",
        "play",
        "stop",
        "toggle_play",
        "record",
        "get_song_position",
        "set_song_position",
        "get_time_signature",
        "set_time_signature",
    ],
    "fl_mixer": [
        "list",
        "get",
        "select",
        "get_route",
        "set_route",
        "set_volume",
        "set_pan",
        "set_mute",
        "set_solo",
        "set_stereo_separation",
    ],
    "fl_channel": [
        "list",
        "get",
        "get_selected",
        "get_steps",
        "classify",
        "select",
        "set_color",
        "set_mute",
        "set_mixer_target",
        "set_name",
        "set_pan",
        "set_solo",
        "set_steps",
        "set_volume",
    ],
    "fl_pattern": [
        "list",
        "get",
        "get_length",
        "get_selected",
        "find_empty",
        "select",
        "rename",
        "set_color",
        "set_length",
    ],
    "fl_playlist": [
        "list",
        "get",
        "select",
        "set_color",
        "set_mute",
        "set_name",
        "set_solo",
    ],
    "fl_effect": [
        "get_slot",
        "list_slots",
        "get_track_slots_enabled",
        "set_slot_enabled",
        "set_slot_mix",
        "set_track_slots_enabled",
        "get_eq",
        "set_eq_band",
    ],
    "fl_plugin": ["list", "list_params", "get_param", "set_param"],
    "fl_piano_roll": [
        "write_notes",
        "write_chord",
        "clear",
        "quantize",
        "transpose",
        "duplicate",
        "velocity_ramp",
        "markers",
        "readback_limits",
    ],
    "fl_batch": ["strict registry reads", "homogeneous persistent writes"],
}

_WORKFLOWS = [
    "project health/preflight",
    "mix review",
    "routing review",
    "project organizer",
    "audio analysis",
    "MIDI export",
    "Knowledgebase tools",
]

_SAFETY_RULES = [
    "Use Knowledgebase evidence before values, ranges, REC events, plugin params, or MIDI data.",
    "Prefer workflow/domain tools over legacy one-off aliases or raw FL API calls.",
    "No persistent FL write without snapshot, smallest write, readback, changelog, "
    "and rollback path.",
    "If API support, readback, or rollback is unclear, use read-only, dry-run, "
    "probe-only, or manual guidance.",
]

_STOP_RULES = [
    "Do not guess normalized values, dB/Hz mappings, track indexing, REC IDs, "
    "or plugin parameter indices.",
    "Do not edit MIDI/TCP ports unless the user explicitly asks for setup troubleshooting.",
    "Do not auto-load plugins, delete patterns/clips, edit playlist clips, render, "
    "save-as, or use raw escape hatches.",
    "Do not promise Stretch Pro, Normalize, native EQ type, Piano Roll readback, "
    "or other unsupported API behavior.",
]


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _summary(full, key, detail_tool):
    items = full.get(key) or []
    total = full.get("total", len(items))
    cap = _CAPS.get(key, 24)
    out = {"total": total, "shown": min(len(items), cap), key: items[:cap]}
    if len(items) > cap:
        out["truncated"] = True
        out["note"] = f"showing first {cap} of {total} -- call {detail_tool} for the rest"
    return out


def _bridge_summary() -> dict:
    b = get_bridge()
    wait = getattr(b, "wait_for_heartbeat", None)
    if callable(wait):
        wait(timeout=1.0)
    alive = b.is_alive()
    out = {
        "alive": alive,
        "heartbeat_age_seconds": b.heartbeat_age() if alive else None,
    }
    if alive:
        ps = b.call(protocol.CMD_GET_PROJECT_STATE)
        out.update(
            {
                "fl_version": ps.get("fl_version"),
                "tempo_bpm": ps.get("tempo_bpm"),
                "playing": ps.get("playing"),
            }
        )
    return out


def register(mcp: FastMCP) -> None:

    @mcp.resource("fl://agent-briefing")
    def agent_briefing() -> dict:
        """Compact safety-first orientation for FLStudioMCP agents."""

        return {
            "purpose": "Start here before choosing tools or touching FL Studio state.",
            "startup": [
                "Read this resource, then fl://status.",
                "Use current workflow/domain tools before broad reads.",
                "Search Knowledgebase with kb_search/kb_get before values, "
                "plugin params, REC events, or MIDI data.",
            ],
            "bridge": _safe(_bridge_summary),
            "domain_tools": _DOMAIN_TOOLS,
            "workflows": _WORKFLOWS,
            "token_strategy": [
                "Use rg, kb_search, and resources before large file reads.",
                "Use capped resources for orientation; call detail tools only for the active task.",
                "Use fl_batch for strict registry reads or safe homogeneous persistent writes.",
            ],
            "safety_rules": _SAFETY_RULES,
            "stop_rules": _STOP_RULES,
        }

    @mcp.resource("fl://status")
    def status() -> dict:
        """Bridge alive + a cheap transport/tempo snapshot."""
        return _safe(_bridge_summary)

    @mcp.resource("fl://project")
    def project() -> dict:
        """Tempo, transport, and channel/mixer/pattern counts."""
        return _safe(lambda: get_bridge().call(protocol.CMD_GET_PROJECT_STATE))

    @mcp.resource("fl://transport")
    def transport() -> dict:
        """Live transport: playing/recording, song position, tempo."""

        def _do():
            b = get_bridge()
            out = dict(b.call(protocol.CMD_GET_PLAY_STATE))
            out["song_position"] = b.call(protocol.CMD_GET_SONG_POS)
            out["tempo"] = b.call(protocol.CMD_GET_TEMPO)
            return out

        return _safe(_do)

    @mcp.resource("fl://channels")
    def channels() -> dict:
        """Channel-rack summary (name + vol/pan/mute/solo), capped."""
        return _safe(
            lambda: _summary(
                fetch_all_pages(get_bridge(), protocol.CMD_CHANNEL_LIST, "channels"),
                "channels",
                'fl_channel(action="list")',
            )
        )

    @mcp.resource("fl://mixer")
    def mixer() -> dict:
        """Mixer-track summary (name + vol/pan/mute/solo), capped."""
        return _safe(
            lambda: _summary(
                fetch_all_pages(get_bridge(), protocol.CMD_MIXER_LIST_TRACKS, "tracks"),
                "tracks",
                'fl_mixer(action="list")',
            )
        )

    @mcp.resource("fl://patterns")
    def patterns() -> dict:
        """Pattern list (1-based index + name), capped."""
        return _safe(
            lambda: _summary(
                fetch_all_pages(get_bridge(), protocol.CMD_PATTERN_LIST, "patterns"),
                "patterns",
                'fl_pattern(action="list")',
            )
        )
