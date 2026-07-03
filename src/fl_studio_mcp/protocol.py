"""Shared protocol constants for the FL Studio MCP bridge.

v0.2: All-MIDI transport. The earlier file-queue design assumed the FL
controller script could write JSON files, but FL's controller-script Python
sandbox blocks every form of file write on at least some builds
(confirmed: FL 24+ MIDI scripting v40, Python 3.12.1). We pivoted to a
MIDI SysEx wire format that works on every FL version that supports MIDI
scripting (20.7+).

Wire format (bytes between SysEx F0 and F7):

    7D 4D 43 50 <dir> <id8> <base64_json>

    7D            non-commercial / private manufacturer ID
    4D 43 50      magic, ASCII "MCP" -- lets us ignore unrelated SysEx
    <dir>         0x01 = request, 0x02 = response, 0x03 = heartbeat
    <id8>         8 ASCII chars [a-z0-9], correlates request and response
    <base64_json> base64 of the UTF-8 JSON payload, fits in 7-bit MIDI bytes

The framing F0 ... F7 is added by the MIDI library (mido) on send and
stripped on receive -- protocol-side helpers work on the payload bytes only.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import secrets
import string

# Bump when the wire format changes incompatibly. Server and FL refuse to
# talk to a mismatched peer.
PROTOCOL_VERSION = 2

# How long the server waits for a heartbeat before declaring FL not running.
HEARTBEAT_STALE_SECONDS = 3.0

# Server-side timeout for any single command round trip.
DEFAULT_TIMEOUT_SECONDS = 5.0

# How often the FL controller emits a heartbeat SysEx.
HEARTBEAT_INTERVAL_SECONDS = 0.5


# ---------------------------------------------------------------------------
# Default MIDI port names
# ---------------------------------------------------------------------------
# These names must match what the user creates in loopMIDI (Windows) or in
# the IAC Driver (macOS Audio MIDI Setup). The names are case-insensitive
# and matched as substrings, so e.g. "FLStudioMCP RX 0" from Windows also
# matches "FLStudioMCP RX".

# Port that carries commands FROM the MCP server TO FL Studio.
# Server opens this as OUTPUT. FL opens this as INPUT.
DEFAULT_PORT_TO_FL = "FLStudioMCP RX"

# Port that carries responses + heartbeats FROM FL Studio TO the MCP server.
# Server opens this as INPUT. FL opens this as OUTPUT.
DEFAULT_PORT_FROM_FL = "FLStudioMCP TX"


def port_to_fl_name() -> str:
    return os.environ.get("FLSTUDIO_MCP_PORT_TO_FL", DEFAULT_PORT_TO_FL)


def port_from_fl_name() -> str:
    return os.environ.get("FLSTUDIO_MCP_PORT_FROM_FL", DEFAULT_PORT_FROM_FL)


# ---------------------------------------------------------------------------
# Command catalogue
# ---------------------------------------------------------------------------
# Unchanged from v0.1 so the existing tool layer keeps working. New commands
# get appended here AND in fl_controller/FLStudioMCP/device_FLStudioMCP.py.

# Transport
CMD_PING = "ping"
CMD_GET_TEMPO = "get_tempo"
CMD_SET_TEMPO = "set_tempo"
CMD_PLAY = "play"
CMD_STOP = "stop"
CMD_TOGGLE_PLAY = "toggle_play"
CMD_RECORD = "record"
CMD_GET_PLAY_STATE = "get_play_state"
CMD_GET_SONG_POS = "get_song_position"
CMD_SET_SONG_POS = "set_song_position"

# Project (Phase 1) -- aggregate read
CMD_GET_PROJECT_STATE = "get_project_state"

# Mixer (Phase 2)
CMD_MIXER_LIST_TRACKS = "mixer_list_tracks"
CMD_MIXER_GET_TRACK = "mixer_get_track"
CMD_MIXER_SET_VOLUME = "mixer_set_volume"
CMD_MIXER_SET_PAN = "mixer_set_pan"
CMD_MIXER_SET_MUTE = "mixer_set_mute"
CMD_MIXER_SET_SOLO = "mixer_set_solo"
CMD_MIXER_SET_NAME = "mixer_set_name"

# Channels (Phase 1)
CMD_CHANNEL_LIST = "channel_list"
CMD_CHANNEL_GET = "channel_get"
CMD_CHANNEL_SET_VOLUME = "channel_set_volume"
CMD_CHANNEL_SET_PAN = "channel_set_pan"
CMD_CHANNEL_SET_MUTE = "channel_set_mute"
CMD_CHANNEL_SET_SOLO = "channel_set_solo"
CMD_CHANNEL_SELECT = "channel_select"

# Patterns (Phase 3)
CMD_PATTERN_LIST = "pattern_list"
CMD_PATTERN_SELECT = "pattern_select"
CMD_PATTERN_RENAME = "pattern_rename"
CMD_PATTERN_GET_LENGTH = "pattern_get_length"

# Plugin params (Phase 1B)
CMD_PLUGIN_LIST = "plugin_list"            # list plugins on a mixer track's slots
CMD_PLUGIN_GET_PARAMS = "plugin_get_params"  # paginated param dump for one plugin
CMD_PLUGIN_LIST_PARAMS = "plugin_list_params"
CMD_PLUGIN_GET_PARAM = "plugin_get_param"
CMD_PLUGIN_SET_PARAM = "plugin_set_param"

# Routing / grouping / cleanup (read surface -- Slice 1)
CMD_MIXER_GET_ROUTING = "mixer_get_routing"            # one track's send destinations
CMD_MIXER_GET_ROUTING_ALL = "mixer_get_routing_all"    # paginated routing matrix
CMD_CHANNEL_ROUTING_SUMMARY = "channel_routing_summary"  # channel -> mixer links

# Routing writes (Slice 2)
CMD_MIXER_SET_ROUTE = "mixer_set_route"                # setRouteTo + afterRoutingChanged

# Level awareness (read) -- meter peaks, meaningful only during playback
CMD_MIXER_GET_PEAKS = "mixer_get_peaks"                # getTrackPeaks L/R/max

# Track / channel color (RGB int 0xRRGGBB). Set accepts r/g/b 0-255 (fresh) or
# an explicit "color" int (rollback re-sends the exact int FL gave us).
CMD_MIXER_SET_COLOR = "mixer_set_color"
CMD_MIXER_GET_COLOR = "mixer_get_color"
CMD_CHANNEL_SET_COLOR = "channel_set_color"
CMD_CHANNEL_GET_COLOR = "channel_get_color"

# Plugin presets (navigate/read) -- op: info | next | prev
CMD_PLUGIN_PRESET = "plugin_preset"                    # getPresetCount/next/prev/getName

# API introspection / arrangement probe -- op: dir | ppq | marker_add | undo
CMD_API_PROBE = "api_probe"

# Arrangement primitives (Slice 1) -- pattern create/clone + section markers
CMD_ARRANGE_NEW_PATTERN = "arrange_new_pattern"        # find empty + jumpTo + name
CMD_ARRANGE_CLONE_PATTERN = "arrange_clone_pattern"    # clonePattern + rename
CMD_ARRANGE_ADD_MARKER = "arrange_add_marker"          # addAutoTimeMarker at a bar

# Note-bridge hardening -- ensure the Piano roll is open before a note-write
CMD_ENSURE_PIANO_ROLL = "ensure_piano_roll"            # ui.showWindow(widPianoRoll)

# Playlist track control (Tier 1) -- names/mute/solo/color (1-based track index)
CMD_PLAYLIST_TRACK_LIST = "playlist_track_list"        # paginated: name/mute/solo/selected
CMD_PLAYLIST_GET_TRACK = "playlist_get_track"          # one track's state (for safe_write snapshot)
CMD_PLAYLIST_MUTE_TRACK = "playlist_mute_track"        # muteTrack (state-aware)
CMD_PLAYLIST_SOLO_TRACK = "playlist_solo_track"        # soloTrack (state-aware)
CMD_PLAYLIST_SET_NAME = "playlist_set_track_name"      # setTrackName
CMD_PLAYLIST_SET_COLOR = "playlist_set_track_color"    # setTrackColor

# Arrangement read (Tier 1) -- selection range + markers + current time
CMD_ARRANGE_GET_SELECTION = "arrange_get_selection"    # selectionStart/End/IsActive + currentTime
CMD_ARRANGE_GET_MARKERS = "arrange_get_markers"        # scan getMarkerName (capped)

# Channel step-sequencer grid (Tier 2) -- draw drum patterns without the piano roll
CMD_CHANNEL_GET_GRID = "channel_get_grid"              # getGridBit per step
CMD_CHANNEL_GET_GRID_BIT = "channel_get_grid_bit"      # one bit (for safe_write snapshot)
CMD_CHANNEL_SET_GRID_BIT = "channel_set_grid_bit"      # setGridBit(channel, step, value)
CMD_CHANNEL_CLEAR_GRID = "channel_clear_grid"          # setGridBit 0 across steps


# ---------------------------------------------------------------------------
# SysEx wire format
# ---------------------------------------------------------------------------

SYSEX_MANUFACTURER = 0x7D            # MIDI-spec reserved for private use
SYSEX_MAGIC = (0x4D, 0x43, 0x50)     # ASCII "MCP"

DIR_REQUEST = 0x01
DIR_RESPONSE = 0x02
DIR_HEARTBEAT = 0x03

REQUEST_ID_LEN = 8
REQUEST_ID_ALPHABET = string.ascii_lowercase + string.digits

# Total header length: 1 (manuf) + 3 (magic) + 1 (dir) + REQUEST_ID_LEN.
_HEADER_LEN = 1 + 3 + 1 + REQUEST_ID_LEN


def new_request_id() -> str:
    return "".join(secrets.choice(REQUEST_ID_ALPHABET) for _ in range(REQUEST_ID_LEN))


def encode_message(direction: int, request_id: str, payload: dict) -> bytes:
    """Build the SysEx payload bytes (everything between F0 and F7).

    The serializer (mido.Message('sysex', data=...)) will add the framing.
    """
    if direction not in (DIR_REQUEST, DIR_RESPONSE, DIR_HEARTBEAT):
        raise ValueError("Bad direction: %r" % direction)
    rid = request_id.encode("ascii")
    if len(rid) != REQUEST_ID_LEN or any(b > 0x7F for b in rid):
        raise ValueError("Bad request id: %r" % request_id)

    body_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    body_b64 = base64.b64encode(body_json.encode("ascii"))

    out = bytearray()
    out.append(SYSEX_MANUFACTURER)
    out.extend(SYSEX_MAGIC)
    out.append(direction & 0x7F)
    out.extend(rid)
    out.extend(body_b64)
    return bytes(out)


def decode_message(data) -> tuple[int, str, dict] | None:
    """Decode a SysEx payload. Returns None if not one of ours.

    ``data`` is the bytes between F0 and F7 (mido strips the framing).
    Accepts bytes, bytearray, or any iterable of ints in [0, 127].
    """
    buf = bytes(data)
    if len(buf) < _HEADER_LEN:
        return None
    if buf[0] != SYSEX_MANUFACTURER:
        return None
    if tuple(buf[1:4]) != SYSEX_MAGIC:
        return None
    direction = buf[4]
    rid = buf[5 : 5 + REQUEST_ID_LEN].decode("ascii", errors="replace")
    body = buf[_HEADER_LEN:]
    try:
        body_json = base64.b64decode(body, validate=True).decode("utf-8")
        payload = json.loads(body_json)
    except Exception:
        return None
    return direction, rid, payload


# ---------------------------------------------------------------------------
# Request / response envelope shapes
# ---------------------------------------------------------------------------

def make_request(command: str, params: dict | None = None) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "cmd": command,
        "params": params or {},
    }


def make_response_ok(data) -> dict:
    return {"v": PROTOCOL_VERSION, "ok": True, "data": data}


def make_response_err(error: str, *, code: str = "error") -> dict:
    return {"v": PROTOCOL_VERSION, "ok": False, "error": error, "code": code}


def system_label() -> str:
    """Short OS label, useful in heartbeats and logs."""
    return "%s %s" % (platform.system(), platform.release())
