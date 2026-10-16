# name=FLStudioMCP
# url=https://github.com/rosasynthesiz/flstudio-mcp
# receiveFrom=
# supportedDevices=
"""FLStudioMCP controller script -- v0.2 MIDI-only transport.

Lives at:
    Documents/Image-Line/FL Studio/Settings/Hardware/FLStudioMCP/device_FLStudioMCP.py

v0.1 tried to use a file-based JSON queue. That doesn't work: FL's
controller-script Python sandbox blocks every form of file write (open(),
os.open, os.makedirs all raise SystemError or TypeError with no useful
message). This v0.2 rewrite uses MIDI SysEx for both directions.

To activate in FL:
  1. Create two loopMIDI ports (Windows) or two IAC Driver buses (macOS):
        FLStudioMCP RX   -- the MCP server's OUTPUT, FL's INPUT
        FLStudioMCP TX   -- FL's OUTPUT,           the MCP server's INPUT
  2. Options > MIDI Settings:
        Input  list -> enable "FLStudioMCP RX", Controller type = FLStudioMCP,
                       Port = some number (e.g. 42).
        Output list -> enable "FLStudioMCP TX", Port = SAME number (42).
  3. The matching port number is how FL's `device.midiOutSysex(...)` routes
     to the right output. Without it, our responses go nowhere.

Wire format: see src/fl_studio_mcp/protocol.py.

Dependencies inside FL Studio:
  - json, base64, binascii (all available -- _json, _codecs, binascii are
    in FL's built-in module list)
  - NO socket, NO requests, NO pip packages, NO file I/O
"""

import base64
import json
import math
import time

# FL Studio's built-in API modules. These are NOT importable outside FL.
import channels
import device
import general
import midi
import mixer
import patterns
import playlist
import plugins
import transport
import ui

# Arrangement module exists on FL 20.99+/21+. Import defensively so the script
# still loads on builds that lack it.
try:
    import arrangement
except Exception:
    arrangement = None

# utils.RGBToColor builds a color int in FL's native byte order; prefer it for
# coloring so we don't have to assume RGB-vs-BGR. Optional -- fall back if absent.
try:
    import utils
except Exception:
    utils = None


# ---------------------------------------------------------------------------
# Protocol constants -- MUST stay in sync with src/fl_studio_mcp/protocol.py
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = 2

SYSEX_MANUFACTURER = 0x7D
SYSEX_MAGIC = (0x4D, 0x43, 0x50)   # ASCII "MCP"

DIR_REQUEST = 0x01
DIR_RESPONSE = 0x02
DIR_HEARTBEAT = 0x03

REQUEST_ID_LEN = 8
_HEADER_LEN = 1 + 3 + 1 + REQUEST_ID_LEN

HEARTBEAT_INTERVAL = 0.5  # seconds between heartbeats


# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_last_heartbeat = 0.0
_fl_version = "unknown"

# `device.midiOutSysex` is what we want; some old builds expose
# `midiOutSysEx` (capital E). Resolve at OnInit.
_send_sysex_fn = None


# ---------------------------------------------------------------------------
# FL Studio lifecycle callbacks
# ---------------------------------------------------------------------------

def OnInit():
    global _fl_version, _send_sysex_fn
    try:
        _fl_version = ui.getVersion()
    except Exception:
        _fl_version = "unknown"

    # Resolve the SysEx-out function name across FL builds.
    _send_sysex_fn = getattr(device, "midiOutSysex", None)
    if _send_sysex_fn is None:
        _send_sysex_fn = getattr(device, "midiOutSysEx", None)

    print("[FLStudioMCP] Ready. FL " + str(_fl_version)
          + ", protocol v" + str(PROTOCOL_VERSION) + ".")
    if _send_sysex_fn is None:
        print("[FLStudioMCP] WARNING: device.midiOutSysex not available -- "
              "responses cannot be sent back to the MCP server.")
    # Send a heartbeat immediately so the server doesn't have to wait.
    _emit_heartbeat()
    return


def OnDeInit():
    print("[FLStudioMCP] Shutting down.")
    return


def OnIdle():
    """Called by FL frequently. Used here ONLY for heartbeat emission."""
    global _last_heartbeat
    now = time.time()
    if now - _last_heartbeat >= HEARTBEAT_INTERVAL:
        _emit_heartbeat()
        _last_heartbeat = now


def _handle_request_sysex(event, source):
    """Decode + dispatch an incoming SysEx request from the MCP server.

    Returns True if the SysEx carried our magic bytes and was a request (so
    the caller can mark event.handled). Non-SysEx MIDI and SysEx without our
    magic are ignored so we coexist with other devices on the same input port.

    FL builds differ in which callback delivers incoming SysEx: some use
    OnMidiMsg, FL 21+/scripting-v40 uses OnSysEx. Both delegate here.
    """
    sysex = getattr(event, "sysex", None)
    if sysex is None:
        return False

    raw = bytes(sysex)
    # Strip F0/F7 framing if FL gave it to us. Some builds include both
    # markers, some only F0, some neither -- be tolerant.
    if len(raw) >= 1 and raw[0] == 0xF0:
        raw = raw[1:]
    if len(raw) >= 1 and raw[-1] == 0xF7:
        raw = raw[:-1]

    decoded = _decode_message(raw)
    if decoded is None:
        # Not ours -- let FL keep processing as it would normally.
        return False

    direction, request_id, request = decoded
    if direction != DIR_REQUEST:
        # Not for us (could be a stray response heard back on the input).
        return False

    command = request.get("cmd", "")
    params = request.get("params") or {}

    try:
        result = _dispatch(command, params)
        payload = {"v": PROTOCOL_VERSION, "ok": True, "data": result}
    except _ClientError as e:
        payload = {"v": PROTOCOL_VERSION, "ok": False, "error": str(e), "code": e.code}
    except Exception as e:
        payload = {
            "v": PROTOCOL_VERSION,
            "ok": False,
            "error": "%s: %s" % (type(e).__name__, e),
            "code": "internal_error",
        }

    _send_message(DIR_RESPONSE, request_id, payload)
    return True


def OnMidiMsg(event):
    """Some FL builds deliver incoming SysEx through this callback."""
    event.handled = _handle_request_sysex(event, "OnMidiMsg")


def OnSysEx(event):
    """FL 21+ / MIDI scripting v40 delivers incoming SysEx here."""
    event.handled = _handle_request_sysex(event, "OnSysEx")


def OnRefresh(flags):
    return


# ---------------------------------------------------------------------------
# SysEx encode / decode -- mirrors src/fl_studio_mcp/protocol.py
# ---------------------------------------------------------------------------

def _encode_message(direction, request_id, payload):
    # Returns the SysEx bytes WITHOUT F0/F7 framing (caller adds them).
    rid = request_id.encode("ascii")
    if len(rid) != REQUEST_ID_LEN:
        rid = (rid + b"00000000")[:REQUEST_ID_LEN]
    body_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    body_b64 = base64.b64encode(body_json.encode("ascii"))
    out = bytearray()
    out.append(SYSEX_MANUFACTURER)
    out.append(SYSEX_MAGIC[0])
    out.append(SYSEX_MAGIC[1])
    out.append(SYSEX_MAGIC[2])
    out.append(direction & 0x7F)
    out.extend(rid)
    out.extend(body_b64)
    return bytes(out)


def _decode_message(data):
    if len(data) < _HEADER_LEN:
        return None
    if data[0] != SYSEX_MANUFACTURER:
        return None
    if data[1] != SYSEX_MAGIC[0] or data[2] != SYSEX_MAGIC[1] or data[3] != SYSEX_MAGIC[2]:
        return None
    direction = data[4]
    try:
        request_id = data[5:5 + REQUEST_ID_LEN].decode("ascii", errors="replace")
    except Exception:
        return None
    body = data[_HEADER_LEN:]
    try:
        body_json = base64.b64decode(bytes(body)).decode("utf-8")
        payload = json.loads(body_json)
    except Exception:
        return None
    return direction, request_id, payload


def _send_message(direction, request_id, payload):
    if _send_sysex_fn is None:
        return
    body = _encode_message(direction, request_id, payload)
    framed = bytes([0xF0]) + body + bytes([0xF7])
    try:
        _send_sysex_fn(framed)
    except Exception as e:
        print("[FLStudioMCP] midiOutSysex failed: %s" % e)


def _emit_heartbeat():
    _send_message(
        DIR_HEARTBEAT,
        "00000000",
        {
            "v": PROTOCOL_VERSION,
            "fl_version": _fl_version,
            "ts": time.time(),
        },
    )


# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

class _ClientError(Exception):
    """Raised by handlers for bad input. Mapped to ok=false with code=client."""
    def __init__(self, message, code="client"):
        Exception.__init__(self, message)
        self.code = code


def _dispatch(command, params):
    handler = _HANDLERS.get(command)
    if handler is None:
        raise _ClientError("Unknown command: %s" % command, code="unknown_command")
    return handler(params)


# -- transport handlers ------------------------------------------------------

def _h_ping(params):
    return {
        "fl_version": _fl_version,
        "protocol_version": PROTOCOL_VERSION,
        "build": "probe-v16",   # reload marker -- bump to verify reloads take
        "ts": time.time(),
    }


def _tempo_scale():
    # FL stores tempo as BPM * 1000 internally. Adjust here if a future FL
    # build changes the scale -- the raw value is exposed in get_tempo so the
    # ratio is observable.
    return 1000.0


def _h_get_tempo(params):
    raw = mixer.getCurrentTempo()
    return {"bpm": raw / _tempo_scale(), "raw": raw}


def _h_set_tempo(params):
    bpm = float(params.get("bpm", 0))
    if bpm < 10.0 or bpm > 999.0:
        raise _ClientError("bpm out of range (10-999)")
    flags = midi.REC_UpdateValue | midi.REC_UpdateControl
    general.processRECEvent(midi.REC_Tempo, int(bpm * _tempo_scale()), flags)
    return {"bpm": mixer.getCurrentTempo() / _tempo_scale()}


def _is_playing():
    try:
        return bool(transport.isPlaying())
    except Exception:
        return False


def _is_recording():
    try:
        return bool(transport.isRecording())
    except Exception:
        return False


def _h_play(params):
    if not _is_playing():
        transport.start()
    return {"playing": True, "recording": _is_recording()}


def _h_stop(params):
    if _is_playing():
        transport.stop()
    return {"playing": False, "recording": _is_recording()}


def _h_toggle_play(params):
    transport.start()
    return {"playing": _is_playing(), "recording": _is_recording()}


def _h_record(params):
    transport.record()
    return {"playing": _is_playing(), "recording": _is_recording()}


def _h_get_play_state(params):
    return {"playing": _is_playing(), "recording": _is_recording()}


_SONGLENGTH_MS = 0
_SONGLENGTH_ABSTICKS = 2


def _h_get_song_pos(params):
    ms = transport.getSongPos(_SONGLENGTH_MS)
    ticks = transport.getSongPos(_SONGLENGTH_ABSTICKS)
    bpm = mixer.getCurrentTempo() / _tempo_scale()
    beats = (ms / 1000.0) * (bpm / 60.0)
    return {
        "position_ms": ms,
        "position_ticks": ticks,
        "position_beats": beats,
        "bpm": bpm,
    }


def _h_set_song_pos(params):
    if "ms" in params:
        transport.setSongPos(float(params["ms"]), _SONGLENGTH_MS)
    elif "beats" in params:
        bpm = mixer.getCurrentTempo() / _tempo_scale()
        if bpm <= 0:
            bpm = 120.0
        ms = float(params["beats"]) * 60000.0 / bpm
        transport.setSongPos(ms, _SONGLENGTH_MS)
    elif "ticks" in params:
        transport.setSongPos(int(params["ticks"]), _SONGLENGTH_ABSTICKS)
    else:
        raise _ClientError("Provide one of: ms, beats, ticks")
    return _h_get_song_pos({})


# -- Phase 1: project / mixer / channel read surface -------------------------
# SysEx payloads >~1.5 KB are dropped (probe: 1000 B OK, 2000 B lost). LIST
# reads paginate by PAYLOAD BUDGET (not a fixed count) and truncate names, so a
# page never exceeds the safe size no matter how long the names are. Full
# untruncated names stay available via the single-item gets.

_LIST_BUDGET = 600   # max bytes of 'data' JSON/page -> ~843 B wire (< safe 1000)
_NAME_CAP = 24       # name length in LIST responses only


def _truncate_name(name):
    name = name or ""
    return (name[:_NAME_CAP], True) if len(name) > _NAME_CAP else (name, False)


def _paginate(total, start, entry_fn, key):
    start = max(0, min(int(start), total))
    out, i = [], start
    while i < total:
        out.append(entry_fn(i))
        i += 1
        nxt = i if i < total else None
        size = len(json.dumps({"total": total, "start": start, "next_start": nxt, key: out},
                              separators=(",", ":")))
        if size > _LIST_BUDGET and len(out) > 1:
            out.pop()           # this entry overflowed the page -> next page
            i -= 1
            break
    return {"total": total, "start": start,
            "next_start": (i if i < total else None), key: out}


def _fits(env):
    """True when a response envelope's compact JSON stays inside _LIST_BUDGET.

    Budgets the COMPLETE serialized response, not one field: ASCII escaping
    expands every non-ASCII char to six bytes, so a 40-char Tamil caption is
    240 B alone and per-field caps (`[:40]`, `[:60]`) do not keep a page
    under the SysEx budget. Callers measure the whole envelope they are
    about to return -- including any exception strings.
    """
    return len(json.dumps(env, separators=(",", ":"))) <= _LIST_BUDGET


def _h_get_project_state(params):
    try:
        pat_num = patterns.patternNumber()
    except Exception:
        pat_num = -1
    return {
        "fl_version": _fl_version,
        "tempo_bpm": mixer.getCurrentTempo() / _tempo_scale(),
        "playing": _is_playing(),
        "recording": _is_recording(),
        "pattern_number": pat_num,
        "pattern_count": patterns.patternCount(),
        "channel_count": channels.channelCount(),
        "mixer_track_count": mixer.trackCount(),
    }


def _mixer_track_dict(i):
    return {
        "i": i,
        "name": mixer.getTrackName(i),
        "pan": round(mixer.getTrackPan(i), 4),
        "mute": bool(mixer.isTrackMuted(i)),
        "solo": bool(mixer.isTrackSolo(i)),
        "color": _color_out(_safe_track_color(i)),
        **_vol_out(mixer.getTrackVolume(i)),
    }


def _mixer_list_entry(i):
    name, cut = _truncate_name(mixer.getTrackName(i))
    e = {"i": i, "name": name, "pan": round(mixer.getTrackPan(i), 4),
         "mute": bool(mixer.isTrackMuted(i)), "solo": bool(mixer.isTrackSolo(i)),
         **_vol_out(mixer.getTrackVolume(i))}
    if cut:
        e["trunc"] = True
    return e


def _h_mixer_list_tracks(params):
    return _paginate(mixer.trackCount(), params.get("start", 0), _mixer_list_entry, "tracks")


def _h_mixer_get_track(params):
    return _mixer_track_dict(int(params.get("index", 0)))


def _channel_dict(i):
    try:
        tgt = channels.getTargetFxTrack(i)
    except Exception:
        tgt = None
    return {
        "i": i,
        "name": channels.getChannelName(i),
        "pan": round(channels.getChannelPan(i), 4),
        "mute": bool(channels.isChannelMuted(i)),
        "solo": bool(channels.isChannelSolo(i)),
        "target_fx_track": tgt,
        "color": _color_out(_safe_channel_color(i)),
        **_vol_out(channels.getChannelVolume(i)),
    }


def _channel_list_entry(i):
    name, cut = _truncate_name(channels.getChannelName(i))
    e = {"i": i, "name": name, "pan": round(channels.getChannelPan(i), 4),
         "mute": bool(channels.isChannelMuted(i)),
         "solo": bool(channels.isChannelSolo(i)),
         **_vol_out(channels.getChannelVolume(i))}
    if cut:
        e["trunc"] = True
    return e


def _h_channel_list(params):
    return _paginate(channels.channelCount(), params.get("start", 0), _channel_list_entry, "channels")


def _h_channel_get(params):
    return _channel_dict(int(params.get("index", 0)))


# -- Phase 1A write surface --------------------------------------------------
# Volume: FL normalized 0.8 == unity (0 dB), NOT 1.0. Convert with that anchor
# and ALWAYS read back the value FL actually accepted (FL clamps).

_UNITY = 0.8


def _db_to_norm(db):
    return max(0.0, min(1.0, _UNITY * (10.0 ** (db / 20.0))))


def _norm_to_db(norm):
    return -120.0 if norm <= 0.0 else 20.0 * math.log10(norm / _UNITY)


def _vol_out(norm):
    # Unified volume representation used by EVERY volume-bearing response
    # (reads + writes, mixer + channel): normalized 0..1 and dB (0.8 = unity).
    return {"vol_norm": round(norm, 4), "vol_db": round(_norm_to_db(norm), 2)}


def _resolve_vol(p):
    v = float(p["value"])
    return _db_to_norm(v) if p.get("unit") == "db" else max(0.0, min(1.0, v))


def _clamp_pan(v):
    return max(-1.0, min(1.0, float(v)))   # FL pan range is -1..+1


def _h_mixer_set_volume(p):
    t = int(p["track"])
    mixer.setTrackVolume(t, _resolve_vol(p))
    out = {"track": t}
    out.update(_vol_out(mixer.getTrackVolume(t)))
    return out


def _h_mixer_set_pan(p):
    t = int(p["track"])
    mixer.setTrackPan(t, _clamp_pan(p["value"]))
    return {"track": t, "pan": round(mixer.getTrackPan(t), 4)}


def _h_mixer_set_mute(p):
    # FL coalesces multiple mute ops per script-tick and the explicit-value
    # form muteTrack(t,1) does not mute on this build -- so set state with a
    # single bare toggle (one per SysEx = one tick).
    t = int(p["track"])
    if bool(mixer.isTrackMuted(t)) != bool(p["state"]):
        mixer.muteTrack(t)
    return {"track": t, "mute": bool(mixer.isTrackMuted(t))}


def _h_mixer_set_solo(p):
    t = int(p["track"])
    if bool(mixer.isTrackSolo(t)) != bool(p["state"]):
        mixer.soloTrack(t)
    return {"track": t, "solo": bool(mixer.isTrackSolo(t))}


def _h_mixer_set_name(p):
    t = int(p["track"])
    mixer.setTrackName(t, str(p["name"]))
    return {"track": t, "name": mixer.getTrackName(t)}


def _h_channel_set_volume(p):
    c = int(p["channel"])
    channels.setChannelVolume(c, _resolve_vol(p))
    out = {"channel": c}
    out.update(_vol_out(channels.getChannelVolume(c)))
    return out


def _h_channel_set_pan(p):
    c = int(p["channel"])
    channels.setChannelPan(c, _clamp_pan(p["value"]))
    return {"channel": c, "pan": round(channels.getChannelPan(c), 4)}


def _h_channel_set_mute(p):
    c = int(p["channel"])
    if bool(channels.isChannelMuted(c)) != bool(p["state"]):
        channels.muteChannel(c)
    return {"channel": c, "mute": bool(channels.isChannelMuted(c))}


def _h_channel_set_solo(p):
    c = int(p["channel"])
    if bool(channels.isChannelSolo(c)) != bool(p["state"]):
        channels.soloChannel(c)
    return {"channel": c, "solo": bool(channels.isChannelSolo(c))}


# -- Track / channel color ---------------------------------------------------
# Thin: the server maps a color name/hex to r,g,b and we just apply it. We
# prefer utils.RGBToColor so FL builds the int in its own byte order; rollback
# instead sends the exact "color" int we read back (order-agnostic).

def _rgb_to_int(r, g, b):
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    if utils is not None and hasattr(utils, "RGBToColor"):
        try:
            return int(utils.RGBToColor(r, g, b)) & 0xFFFFFF
        except Exception:
            pass
    return (r << 16) | (g << 8) | b


def _color_out(color):
    c = int(color) & 0xFFFFFF
    return {"int": c, "hex": "#%06X" % c,
            "r": (c >> 16) & 0xFF, "g": (c >> 8) & 0xFF, "b": c & 0xFF}


def _resolve_color(p):
    if p.get("color") is not None:           # explicit int (rollback path)
        return int(p["color"]) & 0xFFFFFF
    return _rgb_to_int(p.get("r", 0), p.get("g", 0), p.get("b", 0))


def _safe_track_color(i):
    try:
        return int(mixer.getTrackColor(i)) & 0xFFFFFF
    except Exception:
        return 0


def _safe_channel_color(i):
    try:
        return int(channels.getChannelColor(i)) & 0xFFFFFF
    except Exception:
        return 0


def _h_mixer_get_color(p):
    t = int(p["track"])
    return {"track": t, "color": _color_out(_safe_track_color(t))}


def _h_mixer_set_color(p):
    t = int(p["track"])
    mixer.setTrackColor(t, _resolve_color(p))
    return {"track": t, "color": _color_out(_safe_track_color(t))}


def _h_channel_get_color(p):
    c = int(p["channel"])
    return {"channel": c, "color": _color_out(_safe_channel_color(c))}


def _h_channel_set_color(p):
    c = int(p["channel"])
    channels.setChannelColor(c, _resolve_color(p))
    return {"channel": c, "color": _color_out(_safe_channel_color(c))}


# -- Phase 1B: plugin parameters --------------------------------------------
# plugins API arg order (IL-Group): getPluginName(index, slot),
# getParamCount(index, slot), getParamName(paramIndex, index, slot),
# getParamValue(paramIndex, index, slot), setParamValue(value, paramIndex,
# index, slot). For a mixer-track effect, index=mixer track, slot>=0.

def _h_plugin_list(p):
    track = int(p["track"])
    slots = []
    for s in range(10):              # 10 mixer effect slots
        try:
            if plugins.isValid(track, s):
                slots.append({"slot": s, "name": plugins.getPluginName(track, s)})
        except Exception:
            pass
    return {"track": track, "slots": slots}


def _h_plugin_get_params(p):
    track = int(p["track"])
    slot = int(p["slot"])
    if not plugins.isValid(track, slot):
        raise _ClientError("no plugin at track %d slot %d" % (track, slot))
    total = plugins.getParamCount(track, slot)
    start = max(0, int(p.get("start", 0)))
    out = []
    i = start
    scanned = 0
    while i < total and scanned < 150:        # cap scan/page (bounds VST 4240 cost)
        nm = plugins.getParamName(i, track, slot)
        cur = i
        i += 1
        scanned += 1
        if nm:                                 # skip empty-name slots (unused VST)
            out.append({
                "i": cur,
                "name": nm[:30],
                "v": round(plugins.getParamValue(cur, track, slot), 4),
                "s": (plugins.getParamValueString(cur, track, slot) or "")[:16],
            })
            if len(json.dumps(out, separators=(",", ":"))) > 480:
                break
    return {
        "track": track, "slot": slot, "plugin": plugins.getPluginName(track, slot),
        "total": total, "start": start,
        "next_start": (i if i < total else None), "params": out,
    }


def _h_plugin_get_param(p):
    track = int(p["track"])
    slot = int(p["slot"])
    idx = int(p["param"])
    if not plugins.isValid(track, slot):
        raise _ClientError("no plugin at track %d slot %d" % (track, slot))
    return {
        "track": track, "slot": slot, "param": idx,
        "name": plugins.getParamName(idx, track, slot),
        "v": round(plugins.getParamValue(idx, track, slot), 4),
        "s": (plugins.getParamValueString(idx, track, slot) or ""),
    }


def _h_plugin_set_param(p):
    track = int(p["track"])
    slot = int(p["slot"])
    idx = int(p["param"])
    val = float(p["value"])
    if not plugins.isValid(track, slot):
        raise _ClientError("no plugin at track %d slot %d" % (track, slot))
    plugins.setParamValue(val, idx, track, slot)
    return {
        "track": track, "slot": slot, "param": idx,
        "name": plugins.getParamName(idx, track, slot),
        "v": round(plugins.getParamValue(idx, track, slot), 4),
        "s": (plugins.getParamValueString(idx, track, slot) or ""),
    }


# -- Routing / grouping / cleanup READ surface (Slice 1, read-only) ----------

def _route_level(src, dst):
    fn = getattr(mixer, "getRouteSendLevel", None)
    if fn is None:
        return None
    try:
        return round(fn(src, dst), 4)
    except Exception:
        return None


def _route_targets(src):
    n = mixer.trackCount()
    out = []
    for dst in range(n):
        if dst == src:
            continue
        try:
            active = mixer.getRouteSendActive(src, dst)
        except Exception:
            active = 0
        if active:
            e = {"dst": dst, "dst_name": mixer.getTrackName(dst)}
            lvl = _route_level(src, dst)
            if lvl is not None:
                e["level"] = lvl
            out.append(e)
    return out


def _h_mixer_get_routing(p):
    t = int(p.get("track", 0))
    return {"track": t, "name": mixer.getTrackName(t), "routes_to": _route_targets(t)}


def _routing_entry(i):
    name, cut = _truncate_name(mixer.getTrackName(i))
    e = {"i": i, "name": name, "routes_to": _route_targets(i)}
    if cut:
        e["trunc"] = True
    return e


def _h_mixer_get_routing_all(p):
    return _paginate(mixer.trackCount(), p.get("start", 0), _routing_entry, "routing")


def _channel_route_entry(i):
    try:
        tgt = channels.getTargetFxTrack(i)
    except Exception:
        tgt = None
    cname, cut = _truncate_name(channels.getChannelName(i))
    valid = isinstance(tgt, int) and 0 <= tgt < mixer.trackCount()
    e = {"channel": i, "name": cname, "target_mixer_track": tgt,
         "target_name": (mixer.getTrackName(tgt) if valid else None)}
    if cut:
        e["trunc"] = True
    return e


def _h_channel_routing_summary(p):
    return _paginate(channels.channelCount(), p.get("start", 0), _channel_route_entry, "channels")


# -- Routing WRITE surface (Slice 2) -----------------------------------------

def _h_mixer_set_route(p):
    """Enable/disable a send from src -> dst. Thin: one setRouteTo + the
    required afterRoutingChanged(), then read back the active state."""
    src = int(p["src"])
    dst = int(p["dst"])
    on = bool(p.get("enabled", True))
    mixer.setRouteTo(src, dst, 1 if on else 0)
    mixer.afterRoutingChanged()
    return {"src": src, "dst": dst,
            "enabled": bool(mixer.getRouteSendActive(src, dst))}


# -- Level awareness READ surface (peaks; meaningful only while playing) -----

def _h_mixer_get_peaks(p):
    """Meter peaks for a mixer track. mode 0=L, 1=R, 2=max(LR). Linear values
    (1.0 ~ 0 dBFS, can exceed 1). Near-zero when transport is stopped."""
    track = int(p["track"])
    out = {"track": track}
    for mode, key in ((0, "peak_l"), (1, "peak_r"), (2, "peak_max")):
        try:
            out[key] = round(float(mixer.getTrackPeaks(track, mode)), 6)
        except Exception:
            out[key] = None
    return out


# -- Plugin preset navigate/read (op: info | next | prev) --------------------

def _h_plugin_preset(p):
    """Navigate/read a plugin's presets. For a channel generator pass slot=-1.
    op 'next'/'prev' step the preset first, then everything reports the CURRENT
    state: preset_count + candidate current-preset names (getName flags 3/6 +
    getPluginName). Wrapped defensively -- a walled-off plugin just yields
    count 0/1 and unchanging names."""
    track = int(p["track"])
    slot = int(p.get("slot", -1))
    op = p.get("op", "info")
    out = {"track": track, "slot": slot, "op": op}
    if op == "next":
        try:
            plugins.nextPreset(track, slot)
        except Exception as e:
            out["nav_error"] = "nextPreset: %s" % e
    elif op == "prev":
        try:
            plugins.prevPreset(track, slot)
        except Exception as e:
            out["nav_error"] = "prevPreset: %s" % e
    try:
        out["preset_count"] = plugins.getPresetCount(track, slot)
    except Exception as e:
        out["preset_count"] = None
        out["count_error"] = str(e)
    try:
        out["plugin_name"] = plugins.getPluginName(track, slot)
    except Exception:
        out["plugin_name"] = None
    for flag, key in ((3, "name_f3"), (6, "name_f6")):
        try:
            out[key] = plugins.getName(track, slot, flag, 0)
        except Exception:
            out[key] = None
    return out


# -- API introspection / arrangement probe -----------------------------------

def _h_api_probe(p):
    """op:
      dir    -> {module, names}: public names of one FL module (per-module to
                stay under the SysEx size limit). Paginated via start/next_start.
      ppq    -> {ppq, pattern_count, pattern_number}
      step   -> READ-ONLY Channel Rack step-grid + focus/status introspection:
                grid bits of one channel (channels.getGridBit /
                isGridBitAssigned), ui.getStepEditMode, focus + hint and
                piano-roll visibility. No writes.
                Budget-limited: the COMPLETE response is measured against
                _LIST_BUDGET (ASCII-escaped caption/hint/exception strings
                included), variable strings are trimmed until the envelope
                fits, then grid bits are appended while it still fits --
                at most 16 per call, windowed by start/next_start.
      pat    -> READ-ONLY pattern metadata: getPatternName/getPatternLength/
                getPatternColor/isPatternSelected for one index, plus
                patternCount/patternNumber/patternMax/findFirstNextEmptyPat.
                No jump, no rename, no create.
      jump   -> READ-ONLY patterns.jumpToPattern bounds probe: jumps to
                `index`, reports patternNumber, then restores the pattern
                that was ACTUALLY selected at entry (captured before the
                jump, restored in a finally -- never a caller-supplied
                target; `back` is accepted but ignored). Creates no
                patterns (verified 0/999/1000 all leave patternCount
                unchanged).
      marker_add -> arrangement.addAutoTimeMarker(time, name)
      undo   -> general.undoUp() (best-effort, to remove a test marker)
    """
    op = p.get("op", "dir")
    if op == "dir":
        mods = {"playlist": playlist, "arrangement": arrangement, "patterns": patterns,
                "general": general, "transport": transport, "ui": ui, "midi": midi,
                "mixer": mixer, "channels": channels}
        mod = mods.get(p.get("module", "playlist"))
        if mod is None:
            return {"module": p.get("module"), "error": "module not available"}
        names = [n for n in dir(mod) if not n.startswith("_")]
        start = max(0, int(p.get("start", 0)))      # budget-paginate (dir is large)
        module_key = p.get("module", "playlist")
        out, i = [], start
        while i < len(names):
            out.append(names[i])
            i += 1
            # Budget: measure the FULL returned envelope
            # {module,total,start,next_start,names} like _paginate() -- names-only
            # under-measured by the envelope bytes and first pages shipped
            # 652-658 B (contract: data <= 600 B).
            size = len(json.dumps(
                {"module": module_key, "total": len(names), "start": start,
                 "next_start": (i if i < len(names) else None), "names": out},
                separators=(",", ":")))
            if size > _LIST_BUDGET and len(out) > 1:
                out.pop()
                i -= 1
                break
        return {"module": module_key, "total": len(names),
                "start": start, "next_start": (i if i < len(names) else None), "names": out}
    if op == "step":
        # READ-ONLY probe: no setters, no UI commands, nothing to undo.
        # Budget: the COMPLETE serialized response must fit _LIST_BUDGET, not
        # just a grid window -- ASCII escaping expands each non-ASCII char to
        # six bytes, so a wide caption + hint + exception strings measured
        # 964 B in review (the transport silently drops oversized pages).
        # Build the fixed focus/hint block first, trim its variable strings
        # until the whole envelope fits with room for one grid bit, then
        # append bits while it still fits (<=16 per call, start/next_start).
        ch = int(p.get("channel", 0))
        steps = max(1, min(64, int(p.get("steps", 16))))     # hard read cap
        start = max(0, min(steps - 1, int(p.get("start", 0))))
        end = min(steps, start + 16)                          # 16 per page
        base = {"channel": ch, "steps": steps, "start": start}
        probes = (
            ("step_edit_mode", lambda: ui.getStepEditMode()),
            ("piano_roll_focused", lambda: ui.getFocused(getattr(midi, "widPianoRoll", -1))),
            ("focused_form_id", lambda: ui.getFocusedFormID()),
            ("focused_caption", lambda: (ui.getFocusedFormCaption() or "")[:40]),
            ("hint", lambda: (ui.getHintMsg() or "")[:60]),
            ("piano_roll_visible", lambda: ui.getVisible(getattr(midi, "widPianoRoll", -1))),
            ("step_mode_has_setter", lambda: hasattr(ui, "setStepEditMode")),
            ("run_script_api", lambda: hasattr(ui, "runScript")),
        )
        for key, fn in probes:
            try:
                base[key] = fn()
            except Exception as e:
                base[key] = f"err: {type(e).__name__}: {e}"

        def _page(bits, assigned, nxt, err):
            d = dict(base, grid_bits=bits, grid_assigned=assigned,
                     next_start=nxt)
            if err:
                d["grid_error"] = err
            return d

        # Trim the longest variable string (caption, hint, exception text --
        # measured AFTER json escaping) until the envelope fits with room for
        # the first bit, worst-case encoding: a page that can never grow
        # would stall start/next_start pagination.
        probe_nxt = (start + 1) if start + 1 < steps else None
        while not _fits(_page([1], [False], probe_nxt, None)):
            keys = [k for k, v in base.items() if isinstance(v, str) and v]
            if not keys:
                break
            k = max(keys, key=lambda key: len(str(base[key])))
            base[k] = str(base[k])[: len(str(base[k])) // 2]

        bits, assigned, err = [], [], None
        for i in range(start, end):
            try:
                bit = 1 if channels.getGridBit(ch, i) else 0
            except Exception as e:
                err = f"err: {type(e).__name__}: {e}"
                # Error text is budgeted too, but never trimmed below the
                # stable "err: " prefix so callers can still detect it.
                while len(err) > 11 and not _fits(_page(bits, assigned, None, err)):
                    err = err[: len(err) // 2]
                break
            try:
                a = bool(channels.isGridBitAssigned(ch, i))
            except Exception:
                a = None
            nxt = start + len(bits) + 1
            nxt = nxt if nxt < steps else None
            if not _fits(_page(bits + [bit], assigned + [a], nxt, err)):
                break                             # page full -> resume here
            bits.append(bit)
            assigned.append(a)
        if err is not None:
            return _page(bits, assigned, None, err)
        nxt = start + len(bits)
        return _page(bits, assigned, (nxt if nxt < steps else None), None)
    if op == "pat":
        # READ-ONLY pattern metadata. No jump/rename/create.
        idx = int(p.get("index", 1))
        out = {"index": idx}
        if idx < 1:
            # patterns.* indexes are 1-based; FL 26 crashes on jumpToPattern
            # (<0), so never hand a non-positive index to any patterns.* call.
            out["index_error"] = f"rejected index {idx}: pattern indexes are >= 1"
            return out
        probes = (
            ("name", lambda: patterns.getPatternName(idx)),
            ("length", lambda: patterns.getPatternLength(idx)),
            ("color", lambda: patterns.getPatternColor(idx)),
            ("selected", lambda: patterns.isPatternSelected(idx)),
            ("count", lambda: patterns.patternCount()),
            ("number", lambda: patterns.patternNumber()),
            ("max", lambda: patterns.patternMax()),
            ("next_empty", lambda: patterns.findFirstNextEmptyPat()),
            ("has_set_name", lambda: hasattr(patterns, "setPatternName")),
            ("has_set_length", lambda: hasattr(patterns, "setPatternLength")),
        )
        for key, fn in probes:
            try:
                out[key] = fn()
            except Exception as e:
                out[key] = f"err: {type(e).__name__}: {e}"
        return out
    if op == "jump":
        # READ-ONLY probe of patterns.jumpToPattern bounds. Jumps to `index`,
        # reports the resulting patternNumber, then restores the pattern that
        # was ACTUALLY selected at entry -- captured before the jump and
        # restored in a finally, so an exception mid-probe can never leave a
        # different pattern selected. A caller-supplied `back` is ignored
        # (review: back=9 left pattern 9 selected when the project started on
        # 7). Answers: what does FL do when you jump past patternMax / to 0?
        idx = int(p.get("index", 1))
        out = {"tried": idx}
        # GUARD: FL 26.1.7 crashes (EAccessViolation, main thread; the bridge
        # sees a timeout) on patterns.jumpToPattern(<0) -- reproduced on
        # Producer Edition v26.1.7 [build 5419]. Never hand FL a negative
        # index; reject it here instead.
        if idx < 1:
            out["jump_error"] = (f"rejected index {idx}: jumpToPattern needs >= 1 "
                                 "(FL crashes on <0)")
            return out
        try:
            initial = int(patterns.patternNumber())
        except Exception as e:
            out["jump_error"] = f"cannot read initial pattern: {type(e).__name__}: {e}"
            return out
        out["start"] = initial
        if "back" in p:
            out["back_ignored"] = ("restore target is the pattern selected "
                                   "at entry, not `back`")
        try:
            patterns.jumpToPattern(idx)
            out["after_jump_number"] = patterns.patternNumber()
        except Exception as e:
            out["jump_error"] = f"{type(e).__name__}: {e}"
        finally:
            try:
                if initial >= 1:
                    patterns.jumpToPattern(initial)
                    out["restored_number"] = patterns.patternNumber()
                else:
                    out["restore_error"] = (f"initial patternNumber {initial} "
                                            "is not a valid jump target")
            except Exception as e:
                out["restore_error"] = f"{type(e).__name__}: {e}"
        return out
    if op == "ppq":
        out = {}
        for key, fn in (("ppq", lambda: general.getRecPPQ()),
                        ("pattern_count", lambda: patterns.patternCount()),
                        ("pattern_number", lambda: patterns.patternNumber())):
            try:
                out[key] = fn()
            except Exception as e:
                out[key + "_error"] = str(e)
        return out
    if op == "marker_add":
        if arrangement is None:
            return {"ok": False, "error": "arrangement module not available"}
        t = int(p["time"])
        name = p.get("name", "TEST")
        try:
            arrangement.addAutoTimeMarker(t, name)
            return {"ok": True, "added": name, "time": t}
        except Exception as e:
            return {"ok": False, "error": "addAutoTimeMarker: %s" % e}
    if op == "undo":
        try:
            general.undoUp()
            return {"ok": True, "undid": True}
        except Exception as e:
            return {"ok": False, "error": "undoUp: %s" % e}
    return {"error": "unknown op: %s" % op}


# -- Arrangement primitives (Slice 1): pattern create/clone + markers --------

def _h_pattern_list(p):
    """Budget-paginated pattern list: {pattern (1-based), name}. Thin read."""
    def entry(i):
        pn = i + 1                       # FL patterns are 1-based
        name, cut = _truncate_name(patterns.getPatternName(pn))
        e = {"pattern": pn, "name": name}
        if cut:
            e["trunc"] = True
        return e
    return _paginate(patterns.patternCount(), p.get("start", 0), entry, "patterns")


def _h_arrange_new_pattern(p):
    """Find the next empty pattern (or count+1), select it, name it. Selecting
    it is what lets the note bridge write INTO this pattern next."""
    name = p.get("name", "PATTERN")
    try:
        idx = patterns.findFirstNextEmptyPat()
    except Exception:
        idx = -1
    if not isinstance(idx, int) or idx < 1:
        idx = patterns.patternCount() + 1
    patterns.jumpToPattern(idx)
    try:
        patterns.setPatternName(idx, name)
    except Exception as e:
        return {"ok": False, "error": "setPatternName: %s" % e, "index": idx}
    return {"ok": True, "index": idx, "name": patterns.getPatternName(idx),
            "count": patterns.patternCount(), "selected": patterns.patternNumber()}


def _h_arrange_clone_pattern(p):
    """Clone a pattern (copies its notes) and rename the clone. Reports
    count before/after + the clone's selected index so we can see what FL did."""
    src = int(p["src"])
    # GUARD: FL 26.1.7 crashes (EAccessViolation) on jumpToPattern(<0).
    # The MCP tool layer validates src >= 1, but raw RPC commands bypass it.
    if src < 1:
        return {"ok": False, "error": f"rejected src {src}: pattern index must be >= 1 "
                "(FL crashes on jumpToPattern(<0))"}
    new_name = p.get("new_name", "CLONE")
    patterns.jumpToPattern(src)
    before = patterns.patternCount()
    try:
        patterns.clonePattern(src)
    except Exception:
        try:
            patterns.clonePattern()
        except Exception as e:
            return {"ok": False, "error": "clonePattern: %s" % e}
    new_idx = patterns.patternNumber()
    after = patterns.patternCount()
    try:
        patterns.setPatternName(new_idx, new_name)
    except Exception as e:
        return {"ok": False, "error": "setPatternName: %s" % e, "new_index": new_idx}
    return {"ok": True, "src": src, "new_index": new_idx,
            "new_name": patterns.getPatternName(new_idx),
            "count_before": before, "count_after": after}


def _h_ensure_piano_roll(p):
    """Open/focus the Piano roll from the controller (ui.showWindow), so the
    Ctrl+Alt+Y note-bridge trigger has a piano roll to act on -- no manual open.
    Defensive: reports the widget constant + visibility so we can confirm."""
    wid = getattr(midi, "widPianoRoll", None)
    out = {"wid_pianoroll": wid}
    try:
        if wid is not None and hasattr(ui, "getVisible"):
            out["visible_before"] = bool(ui.getVisible(wid))
    except Exception:
        out["visible_before"] = None
    if wid is None or not hasattr(ui, "showWindow"):
        out["ok"] = False
        out["error"] = "ui.showWindow / midi.widPianoRoll unavailable"
        return out
    try:
        ui.showWindow(wid)
        if hasattr(ui, "setFocused"):
            ui.setFocused(wid)   # Ctrl+Alt+Y only fires when the Piano roll is the active panel
        out["ok"] = True
        out["method"] = "ui.showWindow(widPianoRoll)"
    except Exception as e:
        out["ok"] = False
        out["error"] = "showWindow: %s" % e
    return out


def _h_channel_select(p):
    """Make one channel the active selection. The Piano roll follows the
    selected channel, so this retargets the note bridge to write into it."""
    idx = int(p["channel"])
    try:
        channels.selectOneChannel(idx)
    except Exception as e:
        return {"ok": False, "error": "selectOneChannel: %s" % e}
    # selectOneChannel alone does not retarget an already-open Piano roll;
    # reopening it does (verified FL 26.1.4).
    wid = getattr(midi, "widPianoRoll", None)
    reopened = False
    if wid is not None and hasattr(ui, "showWindow"):
        try:
            if hasattr(ui, "hideWindow"):
                ui.hideWindow(wid)
            ui.showWindow(wid)
            if hasattr(ui, "setFocused"):
                ui.setFocused(wid)
            reopened = True
        except Exception:
            reopened = False
    return {"ok": True, "channel": idx, "name": channels.getChannelName(idx),
            "selected": channels.channelNumber(), "piano_roll_retargeted": reopened}


def _h_arrange_add_marker(p):
    if arrangement is None:
        return {"ok": False, "error": "arrangement module not available"}
    bar = int(p["bar"])
    name = p.get("name", "MARK")
    ppb = None
    try:
        ppb = general.getRecPPB()
    except Exception:
        ppb = None
    if not isinstance(ppb, (int, float)) or ppb <= 0:
        try:
            ppb = 4 * general.getRecPPQ()
        except Exception:
            ppb = 384
    t = int((bar - 1) * ppb)            # bar 1 -> tick 0
    try:
        arrangement.addAutoTimeMarker(t, name)
        return {"ok": True, "bar": bar, "name": name, "time": t, "ppb": ppb}
    except Exception as e:
        return {"ok": False, "error": "addAutoTimeMarker: %s" % e}


_HANDLERS = {
    "ping": _h_ping,
    "get_tempo": _h_get_tempo,
    "set_tempo": _h_set_tempo,
    "play": _h_play,
    "stop": _h_stop,
    "toggle_play": _h_toggle_play,
    "record": _h_record,
    "get_play_state": _h_get_play_state,
    "get_song_position": _h_get_song_pos,
    "set_song_position": _h_set_song_pos,
    "get_project_state": _h_get_project_state,
    "mixer_list_tracks": _h_mixer_list_tracks,
    "mixer_get_track": _h_mixer_get_track,
    "channel_list": _h_channel_list,
    "channel_get": _h_channel_get,
    "mixer_set_volume": _h_mixer_set_volume,
    "mixer_set_pan": _h_mixer_set_pan,
    "mixer_set_mute": _h_mixer_set_mute,
    "mixer_set_solo": _h_mixer_set_solo,
    "mixer_set_name": _h_mixer_set_name,
    "channel_set_volume": _h_channel_set_volume,
    "channel_set_pan": _h_channel_set_pan,
    "channel_set_mute": _h_channel_set_mute,
    "channel_set_solo": _h_channel_set_solo,
    "plugin_list": _h_plugin_list,
    "plugin_get_params": _h_plugin_get_params,
    "plugin_get_param": _h_plugin_get_param,
    "plugin_set_param": _h_plugin_set_param,
    "mixer_get_routing": _h_mixer_get_routing,
    "mixer_get_routing_all": _h_mixer_get_routing_all,
    "channel_routing_summary": _h_channel_routing_summary,
    "mixer_set_route": _h_mixer_set_route,
    "mixer_get_peaks": _h_mixer_get_peaks,
    "mixer_set_color": _h_mixer_set_color,
    "mixer_get_color": _h_mixer_get_color,
    "channel_set_color": _h_channel_set_color,
    "channel_get_color": _h_channel_get_color,
    "plugin_preset": _h_plugin_preset,
    "api_probe": _h_api_probe,
    "arrange_new_pattern": _h_arrange_new_pattern,
    "arrange_clone_pattern": _h_arrange_clone_pattern,
    "arrange_add_marker": _h_arrange_add_marker,
    "channel_select": _h_channel_select,
    "ensure_piano_roll": _h_ensure_piano_roll,
    "pattern_list": _h_pattern_list,
}
