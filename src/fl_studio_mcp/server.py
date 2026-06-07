"""FastMCP entry point for the FL Studio MCP server.

Run with::

    python -m fl_studio_mcp.server

or, after ``pip install -e .``, with::

    fl-studio-mcp

To see what MIDI ports the host OS exposes (useful when troubleshooting the
loopMIDI / IAC Driver setup)::

    fl-studio-mcp --list-ports
"""

from __future__ import annotations

import logging
import os
import sys

from fastmcp import FastMCP

from . import __version__
from .connection import list_ports
from .protocol import port_from_fl_name, port_to_fl_name
from .tools import arrange as arrange_tools
from .tools import audio as audio_tools
from .tools import batch as batch_tools
from .tools import bulk as bulk_tools
from .tools import chains as chains_tools
from .tools import channel as channel_domain_tools
from .tools import channels as channel_tools
from .tools import color as color_tools
from .tools import compose as compose_tools
from .tools import effect as effect_domain_tools
from .tools import effects as effects_tools
from .tools import export as export_tools
from .tools import knowledgebase as knowledgebase_tools
from .tools import mix_doctor as mix_doctor_tools
from .tools import mixer as mixer_tools
from .tools import mixer_core as mixer_core_tools
from .tools import mixing as mixing_tools
from .tools import pattern as pattern_domain_tools
from .tools import patterns_playlist as patterns_playlist_tools
from .tools import pianoroll as pianoroll_tools
from .tools import playlist as playlist_domain_tools
from .tools import plugin as plugin_tools
from .tools import plugin_domain as plugin_domain_tools
from .tools import presets as presets_tools
from .tools import project_doctor as project_doctor_tools
from .tools import project_organizer as project_organizer_tools
from .tools import resources as resource_defs
from .tools import routing as routing_tools
from .tools import transport as transport_tools

logger = logging.getLogger("fl_studio_mcp")

_LEGACY_LOW_LEVEL_TOOLS = {
    # Transport one-off aliases. Use fl_transport(action, params).
    "fl_ping",
    "fl_get_tempo",
    "fl_set_tempo",
    "fl_play",
    "fl_stop",
    "fl_toggle_play",
    "fl_record",
    "fl_get_play_state",
    "fl_get_song_position",
    "fl_set_song_position",
    "fl_get_time_signature",
    "fl_set_time_signature",
    # Mixer/channel core aliases. Use fl_mixer/fl_channel or retained safety tools.
    "fl_get_mixer_state",
    "fl_get_channel_state",
    "fl_set_mixer_volume",
    "fl_set_mixer_pan",
    "fl_set_mixer_mute",
    "fl_set_mixer_solo",
    "fl_set_mixer_name",
    "fl_set_channel_volume",
    "fl_set_channel_pan",
    "fl_set_channel_mute",
    "fl_set_channel_solo",
    "fl_mixer_list_tracks",
    "fl_mixer_get_track",
    "fl_mixer_set_volume",
    "fl_mixer_set_pan",
    "fl_mixer_set_mute",
    "fl_mixer_set_solo",
    "fl_mixer_select_track",
    "fl_mixer_get_route",
    "fl_mixer_set_route",
    "fl_mixer_set_stereo_separation",
    # Channel organizer aliases that are covered by fl_channel.
    "fl_get_channel_details",
    "fl_set_channel_name",
    "fl_set_channel_mixer_track",
    "fl_channel_get_grid",
    "fl_channel_set_grid_bit",
    "fl_channel_set_step_param",
    "fl_channel_set_steps",
    "fl_channel_clear_grid",
    "fl_classify_channels",
    # Routing one-off aliases covered by fl_mixer route actions.
    "fl_get_routing",
    "fl_set_route",
    # Pattern and playlist one-off aliases. Use fl_pattern/fl_playlist.
    "fl_pattern_list",
    "fl_pattern_get",
    "fl_pattern_get_length",
    "fl_pattern_select",
    "fl_pattern_rename",
    "fl_pattern_set_color",
    "fl_pattern_set_length",
    "fl_pattern_find_empty",
    "fl_playlist_list_tracks",
    "fl_playlist_get_track",
    "fl_playlist_set_mute",
    "fl_playlist_set_solo",
    "fl_playlist_set_name",
    "fl_playlist_set_color",
    "fl_playlist_select_track",
    # Effect slot and native EQ one-off aliases. Use fl_effect.
    "fl_effect_get_slot",
    "fl_effect_list_slots",
    "fl_effect_set_slot_mix",
    "fl_effect_get_track_slots_enabled",
    "fl_effect_set_track_slots_enabled",
    "fl_effect_set_slot_enabled",
    "fl_eq_get",
    "fl_eq_set_band",
    # Already-loaded plugin parameter aliases. Use fl_plugin.
    "fl_plugin_list",
    "fl_plugin_get_params",
    "fl_plugin_set_param",
    "fl_plugin_list_params",
    "fl_plugin_get_param",
    # Piano Roll one-off aliases. Use fl_piano_roll.
    "fl_write_piano_roll_notes",
    "fl_quantize_pattern",
    "fl_piano_write_notes",
    "fl_piano_write_chord",
    "fl_piano_clear",
    "fl_piano_quantize",
    "fl_piano_transpose",
    "fl_piano_duplicate",
    "fl_piano_velocity_ramp",
    "fl_piano_probe_return_channel",
    "fl_piano_add_marker",
    "fl_piano_add_time_signature_marker",
    "fl_piano_clear_markers",
    "fl_piano_get_notes",
}


SERVER_INSTRUCTIONS = """\
FL Studio MCP server -- control FL Studio from an AI assistant.

REQUIREMENTS
  1. FL Studio 20.7 or newer must be running.
  2. Two virtual MIDI ports must exist (one in each direction):
       - 'FLStudioMCP RX' (server -> FL)
       - 'FLStudioMCP TX' (FL -> server)
     Windows: create both in loopMIDI. macOS: enable two buses in IAC Driver
     (Audio MIDI Setup). Linux: use snd-virmidi.
  3. The FLStudioMCP controller script must be installed under
     Documents/Image-Line/FL Studio/Settings/Hardware/FLStudioMCP/
  4. In FL Studio: Options > MIDI Settings,
       - Enable 'FLStudioMCP RX' in the Input list, set Controller type to
         FLStudioMCP, give it a Port number (any value, e.g. 42).
       - Enable 'FLStudioMCP TX' in the Output list, set Port to the SAME
         number. This is how FL routes the script's outgoing SysEx back to
         the MCP server.
  5. Call fl_transport(action="ping") first to verify the bridge is healthy.

LIMITS YOU SHOULD KNOW ABOUT (these are FL API limitations, not server bugs)
  - Cannot load new VST/AU plugin instances. You can only control plugins
    that already exist in the project.
  - Cannot place, move, or delete playlist clips. Build or clone patterns,
    write notes into them, add markers, and place clips manually in FL Studio.
  - Tempo writes are sometimes ignored if FL is in a modal dialog.
  - Prefer consolidated domain tools such as fl_transport, fl_mixer,
    fl_channel, fl_pattern, fl_playlist, fl_effect, fl_plugin, fl_piano_roll,
    and fl_batch. Legacy low-level aliases are not registered in v1.2.

When the user asks for something outside these limits, explain the limit
clearly rather than retrying.
"""


def build_server() -> FastMCP:
    mcp = FastMCP(
        name="fl-studio-mcp",
        version=__version__,
        instructions=SERVER_INSTRUCTIONS,
    )
    transport_tools.register(mcp)
    mixer_tools.register(mcp)  # v1.2 mixer domain tool (additive shadow)
    channel_domain_tools.register(mcp)  # v1.2 channel domain tool (additive shadow)
    pattern_domain_tools.register(mcp)  # v1.2 pattern domain tool (additive shadow)
    playlist_domain_tools.register(mcp)  # v1.2 playlist domain tool (track metadata only)
    effect_domain_tools.register(mcp)  # v1.2 effect domain tool (slots + native EQ)
    plugin_domain_tools.register(mcp)  # v1.2 plugin domain tool (already-loaded plugins)
    batch_tools.register(mcp)  # v1.2 read-only operation batch tool
    mixer_core_tools.register(mcp)  # project/mixer/channel read+write + safety
    channel_tools.register(mcp)  # Channel organizer: details, names, mixer assignment
    pianoroll_tools.register(mcp)  # Phase 2: write notes into the piano roll
    plugin_tools.register(mcp)  # Phase 1B: plugin param read/write (name or index)
    effects_tools.register(mcp)  # Effect slot + native EQ pack
    mixing_tools.register(mcp)  # Slice B: high-level EQ mixing intents
    routing_tools.register(mcp)  # Routing/cleanup Slice 1: read-only
    bulk_tools.register(mcp)  # Bulk mute/solo: server-side group orchestration
    color_tools.register(mcp)  # Track/channel coloring: name/hex -> FL RGB, one rollback unit
    project_doctor_tools.register(mcp)  # Project health + export preflight
    project_organizer_tools.register(mcp)  # Phase 1: Project Organizer (naming, colors, structure)
    arrange_tools.register(mcp)  # Arrangement Slice 1: pattern create/clone + markers
    resource_defs.register(mcp)  # MCP resources: fl://status, fl://project, ...
    audio_tools.register(mcp)  # Integration 2/3: audio analysis (tempo/key)
    compose_tools.register(mcp)  # Raga/scale composer: write LLM notes via the bridge
    chains_tools.register(mcp)  # Genre chain setup: map recipes to existing plugins
    export_tools.register(mcp)  # MIDI export: arrangement spec -> type-1 .mid on disk
    presets_tools.register(mcp)  # Preset suggester: read preset names from disk
    mix_doctor_tools.register(mcp)  # Mix Review: diagnose whole mix + gated adjustments
    patterns_playlist_tools.register(mcp)  # Phase 3: Patterns & Playlist pack
    knowledgebase_tools.register(mcp)  # KB Tools
    for name in sorted(_LEGACY_LOW_LEVEL_TOOLS):
        mcp.local_provider.remove_tool(name)
    return mcp


def _print_ports() -> int:
    ports = list_ports()
    expected_out = port_to_fl_name()
    expected_in = port_from_fl_name()
    print("Expected port names (override via FLSTUDIO_MCP_PORT_TO_FL / _FROM_FL):")
    print(f"  server output (commands -> FL):  {expected_out!r}")
    print(f"  server input  (responses <- FL): {expected_in!r}")
    print()
    print("MIDI output ports visible to this Python process:")
    for name in ports["outputs"]:
        marker = "  -> " if expected_out.lower() in name.lower() else "     "
        print(marker + repr(name))
    print()
    print("MIDI input ports visible to this Python process:")
    for name in ports["inputs"]:
        marker = "  <- " if expected_in.lower() in name.lower() else "     "
        print(marker + repr(name))
    return 0


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("FLSTUDIO_MCP_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if "--list-ports" in sys.argv:
        sys.exit(_print_ports())

    logger.info(
        "fl-studio-mcp %s; ports: out=%r, in=%r",
        __version__,
        port_to_fl_name(),
        port_from_fl_name(),
    )
    server = build_server()

    # Transport selection: stdio (default, Cursor/Claude) or sse (ChatGPT).
    # --sse flag or FLSTUDIO_MCP_SERVER_TRANSPORT=sse switches to SSE/HTTP.
    transport = os.environ.get("FLSTUDIO_MCP_SERVER_TRANSPORT", "stdio").lower()
    if "--sse" in sys.argv:
        transport = "sse"

    if transport == "sse":
        sse_host = os.environ.get("FLSTUDIO_MCP_SSE_HOST", "127.0.0.1")
        sse_port = int(os.environ.get("FLSTUDIO_MCP_SSE_PORT", "8080"))
        # Allow --port N from CLI
        if "--port" in sys.argv:
            try:
                idx = sys.argv.index("--port")
                sse_port = int(sys.argv[idx + 1])
            except (IndexError, ValueError):
                pass
        logger.info(
            "Starting SSE transport on %s:%d (for ChatGPT / remote MCP clients)", sse_host, sse_port
        )
        server.run(transport="sse", host=sse_host, port=sse_port)
    else:
        server.run()  # stdio transport (Cursor, Claude Desktop, etc)


if __name__ == "__main__":
    main()
