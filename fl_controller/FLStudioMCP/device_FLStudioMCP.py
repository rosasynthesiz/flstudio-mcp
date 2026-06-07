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
import contextlib
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
SYSEX_MAGIC = (0x4D, 0x43, 0x50)  # ASCII "MCP"

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

    print(
        "[FLStudioMCP] Ready. FL " + str(_fl_version) + ", protocol v" + str(PROTOCOL_VERSION) + "."
    )
    if _send_sysex_fn is None:
        print(
            "[FLStudioMCP] WARNING: device.midiOutSysex not available -- "
            "responses cannot be sent back to the MCP server."
        )
    # Enable track metering
    with contextlib.suppress(Exception):
        device.setHasMeters()
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
            "error": f"{type(e).__name__}: {e}",
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
        request_id = data[5 : 5 + REQUEST_ID_LEN].decode("ascii", errors="replace")
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
        print(f"[FLStudioMCP] midiOutSysex failed: {e}")


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
        raise _ClientError(f"Unknown command: {command}", code="unknown_command")
    return handler(params)


# -- transport handlers ------------------------------------------------------


def _h_ping(params):
    return {
        "fl_version": _fl_version,
        "protocol_version": PROTOCOL_VERSION,
        "build": "channels-v39",  # reload marker -- bump to verify reloads take
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


def _h_general_undo(params):
    try:
        general.undoUp()
        return {"ok": True, "undid": True}
    except Exception as e:
        return {"ok": False, "error": f"undoUp: {e}"}


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

_LIST_BUDGET = 600  # max bytes of 'data' JSON/page -> ~843 B wire (< safe 1000)
_NAME_CAP = 24  # name length in LIST responses only


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
        size = len(
            json.dumps(
                {"total": total, "start": start, "next_start": nxt, key: out}, separators=(",", ":")
            )
        )
        if size > _LIST_BUDGET and len(out) > 1:
            out.pop()  # this entry overflowed the page -> next page
            i -= 1
            break
    return {"total": total, "start": start, "next_start": (i if i < total else None), key: out}


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
    dock = -1
    try:
        if hasattr(mixer, "getTrackDockSide"):
            dock = int(mixer.getTrackDockSide(i))
    except Exception:
        pass
    sep = 0.0
    try:
        if hasattr(mixer, "getTrackStereoSep"):
            sep = round(float(mixer.getTrackStereoSep(i)), 4)
    except Exception:
        pass
    return {
        "i": i,
        "name": mixer.getTrackName(i),
        "pan": round(mixer.getTrackPan(i), 4),
        "mute": bool(mixer.isTrackMuted(i)),
        "solo": bool(mixer.isTrackSolo(i)),
        "color": _color_out(_safe_track_color(i)),
        "dock_side": dock,
        "stereo_sep": sep,
        **_mixer_vol_out(i, mixer.getTrackVolume(i)),
    }


def _mixer_list_entry(i):
    name, cut = _truncate_name(mixer.getTrackName(i))
    sep = 0.0
    try:
        if hasattr(mixer, "getTrackStereoSep"):
            sep = round(float(mixer.getTrackStereoSep(i)), 4)
    except Exception:
        pass
    e = {
        "i": i,
        "name": name,
        "pan": round(mixer.getTrackPan(i), 4),
        "mute": bool(mixer.isTrackMuted(i)),
        "solo": bool(mixer.isTrackSolo(i)),
        "stereo_sep": sep,
        **_mixer_vol_out(i, mixer.getTrackVolume(i)),
    }
    if cut:
        e["trunc"] = True
    return e


def _h_mixer_list_tracks(params):
    return _paginate(mixer.trackCount(), params.get("start", 0), _mixer_list_entry, "tracks")


def _h_mixer_get_track(params):
    return _mixer_track_dict(int(params.get("index", 0)))


def _channel_type(i):
    try:
        code = int(channels.getChannelType(i))
    except Exception:
        return {"code": None, "label": None}
    names = (
        "CT_Sampler",
        "CT_Hybrid",
        "CT_GenPlug",
        "CT_AudioClip",
        "CT_AutoClip",
        "CT_Layer",
        "CT_Envelope",
        "CT_MIDIOut",
    )
    for name in names:
        if hasattr(midi, name):
            try:
                if code == int(getattr(midi, name)):
                    return {"code": code, "label": name[3:].lower()}
            except Exception:
                pass
    return {"code": code, "label": "unknown"}


def _safe_channel_pitch(i):
    try:
        return channels.getChannelPitch(i)
    except Exception:
        return None


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
        "type": _channel_type(i),
        "pitch": _safe_channel_pitch(i),
        **_vol_out(channels.getChannelVolume(i)),
    }


def _channel_list_entry(i):
    name, cut = _truncate_name(channels.getChannelName(i))
    e = {
        "i": i,
        "name": name,
        "pan": round(channels.getChannelPan(i), 4),
        "mute": bool(channels.isChannelMuted(i)),
        "solo": bool(channels.isChannelSolo(i)),
        **_vol_out(channels.getChannelVolume(i)),
    }
    if cut:
        e["trunc"] = True
    return e


def _h_channel_list(params):
    return _paginate(
        channels.channelCount(), params.get("start", 0), _channel_list_entry, "channels"
    )


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


# Mixer-specific fader calibration data (empirically swept)
MIXER_CALIBRATION = [
    (0.0000, float("-inf")),
    (0.0100, -50.3347),
    (0.0200, -44.1829),
    (0.0300, -40.5293),
    (0.0400, -37.8981),
    (0.0500, -35.8268),
    (0.0600, -34.1094),
    (0.0700, -32.6361),
    (0.0800, -31.3412),
    (0.0900, -30.1825),
    (0.1000, -29.1310),
    (0.1100, -28.1661),
    (0.1200, -27.2727),
    (0.1300, -26.4392),
    (0.1400, -25.6566),
    (0.1500, -24.9177),
    (0.1600, -24.2169),
    (0.1700, -23.5495),
    (0.1800, -22.9115),
    (0.1900, -22.2998),
    (0.2000, -21.7114),
    (0.2100, -21.1442),
    (0.2200, -20.5961),
    (0.2300, -20.0653),
    (0.2400, -19.5503),
    (0.2500, -19.0498),
    (0.2600, -18.5625),
    (0.2700, -18.0875),
    (0.2800, -17.6237),
    (0.2900, -17.1704),
    (0.3000, -16.7269),
    (0.3100, -16.2923),
    (0.3200, -15.8662),
    (0.3300, -15.4479),
    (0.3400, -15.0370),
    (0.3500, -14.6330),
    (0.3600, -14.2355),
    (0.3700, -13.8441),
    (0.3800, -13.4584),
    (0.3900, -13.0781),
    (0.4000, -12.7029),
    (0.4100, -12.3325),
    (0.4200, -11.9667),
    (0.4300, -11.6052),
    (0.4400, -11.2479),
    (0.4500, -10.8944),
    (0.4600, -10.5446),
    (0.4700, -10.1983),
    (0.4800, -9.8554),
    (0.4900, -9.5156),
    (0.5000, -9.1789),
    (0.5100, -8.8451),
    (0.5200, -8.5140),
    (0.5300, -8.1856),
    (0.5400, -7.8597),
    (0.5500, -7.5361),
    (0.5600, -7.2149),
    (0.5700, -6.8959),
    (0.5800, -6.5790),
    (0.5900, -6.2642),
    (0.6000, -5.9512),
    (0.6100, -5.6401),
    (0.6200, -5.3308),
    (0.6300, -5.0232),
    (0.6400, -4.7172),
    (0.6500, -4.4129),
    (0.6600, -4.1100),
    (0.6700, -3.8086),
    (0.6800, -3.5085),
    (0.6900, -3.2099),
    (0.7000, -2.9125),
    (0.7100, -2.6163),
    (0.7200, -2.3214),
    (0.7300, -2.0276),
    (0.7400, -1.7349),
    (0.7500, -1.4433),
    (0.7600, -1.1527),
    (0.7700, -0.8632),
    (0.7800, -0.5745),
    (0.7900, -0.2868),
    (0.8000, 0.0000),
    (0.8100, 0.2860),
    (0.8200, 0.5711),
    (0.8300, 0.8554),
    (0.8400, 1.1390),
    (0.8500, 1.4218),
    (0.8600, 1.7039),
    (0.8700, 1.9853),
    (0.8800, 2.2660),
    (0.8900, 2.5461),
    (0.9000, 2.8256),
    (0.9100, 3.1044),
    (0.9200, 3.3827),
    (0.9300, 3.6604),
    (0.9400, 3.9376),
    (0.9500, 4.2142),
    (0.9600, 4.4903),
    (0.9700, 4.7659),
    (0.9800, 5.0411),
    (0.9900, 5.3158),
    (1.0000, 5.5900),
]


def _mixer_db_to_norm(db):
    if db <= -50.3347:
        if db <= -100.0:
            return 0.0
        y0, x0 = -60.0, 0.0
        y1, x1 = -50.3347, 0.01
        if db <= y0:
            return 0.0
        return x0 + (db - y0) * (x1 - x0) / (y1 - y0)
    if db >= 5.5900:
        return 1.0
    for i in range(1, len(MIXER_CALIBRATION) - 1):
        x0, y0 = MIXER_CALIBRATION[i]
        x1, y1 = MIXER_CALIBRATION[i + 1]
        if y0 <= db <= y1:
            return x0 + (db - y0) * (x1 - x0) / (y1 - y0)
    return 1.0


def _mixer_vol_out(i, norm):
    try:
        db = mixer.getTrackVolume(i, 1)
    except Exception:
        db = _norm_to_db(norm)
    return {"vol_norm": round(norm, 4), "vol_db": round(db, 2)}


def _resolve_vol(p):
    v = float(p["value"])
    return _db_to_norm(v) if p.get("unit") == "db" else max(0.0, min(1.0, v))


def _clamp_pan(v):
    return max(-1.0, min(1.0, float(v)))  # FL pan range is -1..+1


def _h_mixer_set_volume(p):
    t = int(p["track"])
    val = float(p["value"])
    norm_val = _mixer_db_to_norm(val) if p.get("unit") == "db" else max(0.0, min(1.0, val))
    mixer.setTrackVolume(t, norm_val)
    out = {"track": t}
    out.update(_mixer_vol_out(t, mixer.getTrackVolume(t)))
    return out


def _h_mixer_set_pan(p):
    t = int(p["track"])
    mixer.setTrackPan(t, _clamp_pan(p["value"]))
    return {"track": t, "pan": round(mixer.getTrackPan(t), 4)}


def _h_mixer_set_stereo_sep(p):
    t = int(p["track"])
    val = max(-1.0, min(1.0, float(p["value"])))
    if hasattr(mixer, "setTrackStereoSep"):
        mixer.setTrackStereoSep(t, val)

    current = 0.0
    if hasattr(mixer, "getTrackStereoSep"):
        current = round(mixer.getTrackStereoSep(t), 4)
    return {"track": t, "stereo_sep": current}


def _h_mixer_get_stereo_sep(p):
    t = int(p["track"])
    current = 0.0
    if hasattr(mixer, "getTrackStereoSep"):
        current = round(mixer.getTrackStereoSep(t), 4)
    return {"track": t, "stereo_sep": current}


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


def _h_channel_set_name(p):
    c = int(p["channel"])
    channels.setChannelName(c, str(p["name"]))
    return {"channel": c, "name": channels.getChannelName(c)}


def _h_channel_set_target(p):
    c = int(p["channel"])
    track = int(p["track"])
    channels.setTargetFxTrack(c, track)
    try:
        target = channels.getTargetFxTrack(c)
    except Exception:
        target = track
    return {"channel": c, "target_fx_track": target}


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
    return {
        "int": c,
        "hex": f"#{c:06X}",
        "r": (c >> 16) & 0xFF,
        "g": (c >> 8) & 0xFF,
        "b": c & 0xFF,
    }


def _resolve_color(p):
    if p.get("color") is not None:  # explicit int (rollback path)
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
    for s in range(10):  # 10 mixer effect slots
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
        raise _ClientError(f"no plugin at track {track} slot {slot}")
    total = plugins.getParamCount(track, slot)
    start = max(0, int(p.get("start", 0)))
    out = []
    i = start
    scanned = 0
    while i < total and scanned < 150:  # cap scan/page (bounds VST 4240 cost)
        nm = plugins.getParamName(i, track, slot)
        cur = i
        i += 1
        scanned += 1
        # Always include to see all indices
        out.append(
            {
                "i": cur,
                "name": nm[:30] if nm else "EMPTY",
                "v": round(plugins.getParamValue(cur, track, slot), 4),
                "s": (plugins.getParamValueString(cur, track, slot) or "")[:16],
            }
        )
        if len(json.dumps(out, separators=(",", ":"))) > 480:
            break
    return {
        "track": track,
        "slot": slot,
        "plugin": plugins.getPluginName(track, slot),
        "total": total,
        "start": start,
        "next_start": (i if i < total else None),
        "params": out,
    }


def _h_plugin_get_param(p):
    track = int(p["track"])
    slot = int(p["slot"])
    idx = int(p["param"])
    if not plugins.isValid(track, slot):
        raise _ClientError(f"no plugin at track {track} slot {slot}")
    return {
        "track": track,
        "slot": slot,
        "param": idx,
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
        raise _ClientError(f"no plugin at track {track} slot {slot}")
    plugins.setParamValue(val, idx, track, slot)
    return {
        "track": track,
        "slot": slot,
        "param": idx,
        "name": plugins.getParamName(idx, track, slot),
        "v": round(plugins.getParamValue(idx, track, slot), 4),
        "s": (plugins.getParamValueString(idx, track, slot) or ""),
    }


# -- Routing / grouping / cleanup READ surface (Slice 1, read-only) ----------


def _route_level(src, dst):
    fn = getattr(mixer, "getRouteToLevel", None) or getattr(mixer, "getRouteSendLevel", None)
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
    e = {
        "channel": i,
        "name": cname,
        "target_mixer_track": tgt,
        "target_name": (mixer.getTrackName(tgt) if valid else None),
        "type": _channel_type(i),
        **_vol_out(channels.getChannelVolume(i)),
    }
    if cut:
        e["trunc"] = True
    return e


def _h_mixer_get_free_track(p):
    start = int(p.get("start", 1))
    try:
        t = mixer.getFreeTrack()
        if t >= start:
            return {"track": int(t)}
    except Exception:
        pass

    # Fallback manual scan if getFreeTrack is unavailable or returned a lower track
    start = int(p.get("start", 1))
    for i in range(start, mixer.trackCount()):
        if i == 0:
            continue
        name = mixer.getTrackName(i)
        if not (name.startswith("Insert ") or name.startswith("Track ")):
            continue
        try:
            if plugins.getPluginCount(i) > 0:
                continue
        except Exception:
            pass
        return {"track": i}
    return {"track": None}


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
    return {"src": src, "dst": dst, "enabled": bool(mixer.getRouteSendActive(src, dst))}


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


def _h_mixer_get_all_peaks(p):
    """Batch read all peaks for tracks 0-125."""
    peaks = []
    for t in range(126):
        try:
            peaks.append(round(float(mixer.getTrackPeaks(t, 2)), 6))
        except Exception:
            peaks.append(0.0)
    return {"peaks": peaks}


def _h_mixer_selected(params):
    return {"track": mixer.trackNumber()}


def _h_mixer_select_track(params):
    track = int(params["track"])
    mixer.setTrackNumber(track)
    return {"track": track}


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
            out["nav_error"] = f"nextPreset: {e}"
    elif op == "prev":
        try:
            plugins.prevPreset(track, slot)
        except Exception as e:
            out["nav_error"] = f"prevPreset: {e}"
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


def _h_plugin_get_preset_name(p):
    p["op"] = "info"
    return _h_plugin_preset(p)


# -- API introspection / arrangement probe -----------------------------------


def _h_api_probe(p):
    """op:
    dir    -> {module, names}: public names of one FL module (per-module to
              stay under the SysEx size limit).
    ppq    -> {ppq, pattern_count, pattern_number}
    marker_add -> arrangement.addAutoTimeMarker(time, name)
    undo   -> general.undoUp() (best-effort, to remove a test marker)
    """
    op = p.get("op", "dir")
    if op == "dir":
        mods = {
            "playlist": playlist,
            "arrangement": arrangement,
            "patterns": patterns,
            "general": general,
            "transport": transport,
            "ui": ui,
            "midi": midi,
            "mixer": mixer,
            "channels": channels,
        }
        mod = mods.get(p.get("module", "playlist"))
        if mod is None:
            return {"module": p.get("module"), "error": "module not available"}
        names = [n for n in dir(mod) if not n.startswith("_")]
        start = max(0, int(p.get("start", 0)))  # budget-paginate (dir is large)
        out, i = [], start
        while i < len(names):
            out.append(names[i])
            i += 1
            if len(json.dumps(out, separators=(",", ":"))) > 600 and len(out) > 1:
                out.pop()
                i -= 1
                break
        return {
            "module": p.get("module", "playlist"),
            "total": len(names),
            "start": start,
            "next_start": (i if i < len(names) else None),
            "names": out,
        }
    if op == "ppq":
        out = {}
        for key, fn in (
            ("ppq", lambda: general.getRecPPQ()),
            ("pattern_count", lambda: patterns.patternCount()),
            ("pattern_number", lambda: patterns.patternNumber()),
        ):
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
            return {"ok": False, "error": f"addAutoTimeMarker: {e}"}
    if op == "undo":
        try:
            general.undoUp()
            return {"ok": True, "undid": True}
        except Exception as e:
            return {"ok": False, "error": f"undoUp: {e}"}
    if op == "volume_sweep":
        track = int(p.get("track", 1))
        start = int(p.get("start", 0))
        count = int(p.get("count", 25))
        orig_vol = mixer.getTrackVolume(track, 0)
        sweep_results = []
        for i in range(start, start + count):
            if i > 100:
                break
            val = i / 100.0
            mixer.setTrackVolume(track, val)
            db_val = mixer.getTrackVolume(track, 1)
            sweep_results.append((round(val, 4), round(db_val, 4)))
        mixer.setTrackVolume(track, orig_vol)
        return {"sweep": sweep_results}
    return {"error": f"unknown op: {op}"}


# -- Arrangement primitives (Slice 1): pattern create/clone + markers --------


def _h_pattern_list(p):
    """Budget-paginated pattern list with name, color, and length."""

    def entry(i):
        pn = i + 1  # FL patterns are 1-based
        name, cut = _truncate_name(patterns.getPatternName(pn))
        try:
            length = patterns.getPatternLength(pn)
        except Exception:
            length = 16
        e = {
            "pattern": pn,
            "index": pn,
            "name": name,
            "color": _color_out(_safe_pattern_color(pn)),
            "length": length or 16,
        }
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
        return {"ok": False, "error": f"setPatternName: {e}", "index": idx}
    return {
        "ok": True,
        "index": idx,
        "name": patterns.getPatternName(idx),
        "count": patterns.patternCount(),
        "selected": patterns.patternNumber(),
    }


def _h_arrange_clone_pattern(p):
    """Clone a pattern (copies its notes) and rename the clone. Reports
    count before/after + the clone's selected index so we can see what FL did."""
    src = int(p["src"])
    new_name = p.get("new_name", "CLONE")
    patterns.jumpToPattern(src)
    before = patterns.patternCount()
    try:
        patterns.clonePattern(src)
    except Exception:
        try:
            patterns.clonePattern()
        except Exception as e:
            return {"ok": False, "error": f"clonePattern: {e}"}
    new_idx = patterns.patternNumber()
    after = patterns.patternCount()
    try:
        patterns.setPatternName(new_idx, new_name)
    except Exception as e:
        return {"ok": False, "error": f"setPatternName: {e}", "new_index": new_idx}
    return {
        "ok": True,
        "src": src,
        "new_index": new_idx,
        "new_name": patterns.getPatternName(new_idx),
        "count_before": before,
        "count_after": after,
    }


def _h_ensure_piano_roll(p):
    """Open/focus the Piano roll, optionally retargeted to a channel/pattern."""
    wid = getattr(midi, "widPianoRoll", None)
    out = {"wid_pianoroll": wid}
    pattern = p.get("pattern")
    channel = p.get("channel")

    try:
        if wid is not None and hasattr(ui, "getVisible"):
            out["visible_before"] = bool(ui.getVisible(wid))
    except Exception:
        out["visible_before"] = None

    if pattern is not None:
        try:
            patterns.jumpToPattern(int(pattern))
            out["pattern"] = patterns.patternNumber()
        except Exception as e:
            out["pattern_error"] = f"jumpToPattern: {e}"

    if channel is not None and hasattr(ui, "openEventEditor"):
        ch = int(channel)
        try:
            try:
                channels.selectOneChannel(ch, True)
            except TypeError:
                channels.selectOneChannel(ch)
            event_id = channels.getRecEventId(ch) + getattr(midi, "REC_Chan_PianoRoll", 0)
            editor = getattr(midi, "EE_PR", 1)
            visible = False
            try:
                if wid is not None and hasattr(ui, "getVisible"):
                    visible = bool(ui.getVisible(wid))
            except Exception:
                visible = False
            ui.openEventEditor(event_id, editor, 0 if visible else 1)
            if wid is not None and hasattr(ui, "setFocused"):
                with contextlib.suppress(Exception):
                    ui.setFocused(wid)
            out.update(
                {
                    "ok": True,
                    "channel": ch,
                    "event_id": event_id,
                    "method": "ui.openEventEditor(piano_roll)",
                    "retargeted": True,
                }
            )
            return out
        except Exception as e:
            out["retarget_error"] = f"openEventEditor: {e}"

    if wid is None or not hasattr(ui, "showWindow"):
        out["ok"] = False
        out["error"] = "ui.showWindow / midi.widPianoRoll unavailable"
        return out
    try:
        ui.showWindow(wid)
        out["ok"] = True
        out["method"] = "ui.showWindow(widPianoRoll)"
        out["retargeted"] = False
    except Exception as e:
        out["ok"] = False
        out["error"] = f"showWindow: {e}"
    return out


def _h_channel_select(p):
    """Make one channel the active selection. The Piano roll follows the
    selected channel, so this retargets the note bridge to write into it."""
    idx = int(p["channel"])
    try:
        channels.selectOneChannel(idx)
    except Exception as e:
        return {"ok": False, "error": f"selectOneChannel: {e}"}
    return {
        "ok": True,
        "channel": idx,
        "name": channels.getChannelName(idx),
        "selected": channels.channelNumber(),
    }


def _h_channel_selected(p):
    idx = channels.channelNumber()
    return {"selected": idx, "name": channels.getChannelName(idx)}


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
    t = int((bar - 1) * ppb)  # bar 1 -> tick 0
    try:
        arrangement.addAutoTimeMarker(t, name)
        return {"ok": True, "bar": bar, "name": name, "time": t, "ppb": ppb}
    except Exception as e:
        return {"ok": False, "error": f"addAutoTimeMarker: {e}"}


def _safe_pattern_color(i):
    try:
        return int(patterns.getPatternColor(i)) & 0xFFFFFF
    except Exception:
        return 0


def _safe_playlist_track_color(i):
    try:
        return int(playlist.getTrackColor(i)) & 0xFFFFFF
    except Exception:
        return 0


def _h_channel_get_steps(p):
    idx = int(p["channel"])
    steps = int(p.get("steps", 64))
    target_pattern = p.get("pattern")
    previous_pattern = None
    if target_pattern is not None:
        target_pattern = int(target_pattern)
        previous_pattern = patterns.patternNumber()
        if target_pattern < 1 or target_pattern > patterns.patternCount():
            raise _ClientError("pattern index out of range")
        if previous_pattern != target_pattern:
            patterns.jumpToPattern(target_pattern)
    grid, vel, pan, shift, rep = [], [], [], [], []
    rel, modx, pitch = [], [], []
    p_release = getattr(midi, "pRelease", None)
    p_modx = getattr(midi, "pModX", None)
    p_pitch = getattr(midi, "pPitch", None) or getattr(midi, "pFinePitch", None)
    try:
        for s in range(steps):
            try:
                g = bool(channels.getGridBit(idx, s))
            except Exception:
                g = False
            grid.append(g)

            try:
                raw_v = channels.getStepParam(idx, s, midi.pVelocity, 0, 0)
                v = round(float(raw_v) / 127.0, 4)
            except Exception:
                v = 0.8
            vel.append(v)

            try:
                raw_pan = channels.getStepParam(idx, s, midi.pPan, 0, 0)
                pn = round(float(raw_pan) / 64.0 - 1.0, 4)
            except Exception:
                pn = 0.0
            pan.append(pn)

            try:
                raw_shift = channels.getStepParam(idx, s, midi.pShift, 0, 0)
                sh = round(float(raw_shift) / 240.0, 4)
            except Exception:
                sh = 0.0
            shift.append(sh)

            try:
                rp = int(channels.getStepParam(idx, s, midi.pRepeat, 0, 0))
            except Exception:
                rp = 0
            rep.append(rp)

            if p_release is not None:
                try:
                    raw_rel = channels.getStepParam(idx, s, p_release, 0, 0)
                    rel.append(round(float(raw_rel) / 127.0, 4))
                except Exception:
                    rel.append(0.0)
            else:
                rel.append(None)

            if p_modx is not None:
                try:
                    raw_modx = channels.getStepParam(idx, s, p_modx, 0, 0)
                    modx.append(round(float(raw_modx) / 255.0, 4))
                except Exception:
                    modx.append(0.0)
            else:
                modx.append(None)

            if p_pitch is not None:
                try:
                    raw_pitch = channels.getStepParam(idx, s, p_pitch, 0, 0)
                    pitch.append(int(raw_pitch))
                except Exception:
                    pitch.append(0)
            else:
                pitch.append(None)

        return {
            "channel": idx,
            "pattern": patterns.patternNumber(),
            "grid": grid,
            "vel": vel,
            "pan": pan,
            "shift": shift,
            "rep": rep,
            "release": rel,
            "mod": modx,
            "pitch": pitch,
            "capabilities": {
                "release": bool(p_release is not None),
                "mod": bool(p_modx is not None),
                "pitch": bool(p_pitch is not None),
            },
        }
    finally:
        if previous_pattern is not None and previous_pattern != patterns.patternNumber():
            patterns.jumpToPattern(previous_pattern)


def _h_pattern_get(p):
    idx = int(p["index"])
    if idx < 1 or idx > patterns.patternCount():
        raise _ClientError("pattern index out of range")
    try:
        length = patterns.getPatternLength(idx)
    except Exception:
        length = 16
    return {
        "index": idx,
        "name": patterns.getPatternName(idx),
        "color": _color_out(_safe_pattern_color(idx)),
        "length": length or 16,
    }


def _h_pattern_selected(p):
    return {"selected": patterns.patternNumber()}


def _h_playlist_get_track(p):
    idx = int(p["index"])
    if idx < 1 or idx > playlist.trackCount():
        raise _ClientError("playlist track index out of range")
    return {
        "index": idx,
        "name": playlist.getTrackName(idx) or "",
        "color": _color_out(_safe_playlist_track_color(idx)),
        "mute": bool(playlist.isTrackMuted(idx)),
        "solo": bool(playlist.isTrackSolo(idx)),
        "selected": bool(playlist.isTrackSelected(idx)),
    }


def _h_pattern_select(p):
    idx = int(p["index"])
    if idx < 1 or idx > patterns.patternCount():
        raise _ClientError("pattern index out of range")
    patterns.jumpToPattern(idx)
    return {"selected": patterns.patternNumber()}


def _h_pattern_rename(p):
    idx = int(p["index"])
    name = str(p["name"])
    if idx < 1 or idx > patterns.patternCount():
        raise _ClientError("pattern index out of range")
    patterns.setPatternName(idx, name)
    return {"index": idx, "name": patterns.getPatternName(idx)}


def _h_pattern_get_length(p):
    idx = int(p["index"])
    if idx < 1 or idx > patterns.patternCount():
        raise _ClientError("pattern index out of range")
    beats = patterns.getPatternLength(idx)
    return {"index": idx, "beats": beats, "steps": beats * 4}


def _h_pattern_set_color(p):
    idx = int(p["index"])
    if idx < 1 or idx > patterns.patternCount():
        raise _ClientError("pattern index out of range")
    color_val = _resolve_color(p)
    patterns.setPatternColor(idx, color_val)
    return _h_pattern_get({"index": idx})


def _h_pattern_set_length(p):
    idx = int(p["index"])
    beats = float(p["beats"])
    if idx < 1 or idx > patterns.patternCount():
        raise _ClientError("pattern index out of range")
    if beats <= 0:
        raise _ClientError("beats must be > 0")
    if not hasattr(patterns, "setPatternLength"):
        raise _ClientError("pattern length write API unavailable on this FL build")
    patterns.setPatternLength(idx, beats)
    return _h_pattern_get_length({"index": idx})


def _h_pattern_find_empty(p):
    try:
        idx = int(patterns.findFirstNextEmptyPat())
    except Exception:
        idx = -1
    if idx < 1:
        idx = int(patterns.patternCount()) + 1
    return {"index": idx, "pattern_count": int(patterns.patternCount())}


def _h_playlist_list_tracks(p):
    def entry(i):
        track_num = i + 1  # 1-based playlist tracks
        return {
            "index": track_num,
            "name": playlist.getTrackName(track_num) or "",
            "color": _color_out(_safe_playlist_track_color(track_num)),
            "mute": bool(playlist.isTrackMuted(track_num)),
            "solo": bool(playlist.isTrackSolo(track_num)),
            "selected": bool(playlist.isTrackSelected(track_num)),
        }

    return _paginate(playlist.trackCount(), p.get("start", 0), entry, "tracks")


def _h_playlist_set_mute(p):
    idx = int(p["index"])
    state = bool(p["state"])
    if idx < 1 or idx > playlist.trackCount():
        raise _ClientError("playlist track index out of range")
    playlist.muteTrack(idx, 1 if state else 0)
    return {"index": idx, "mute": bool(playlist.isTrackMuted(idx))}


def _h_playlist_set_solo(p):
    idx = int(p["index"])
    state = bool(p["state"])
    if idx < 1 or idx > playlist.trackCount():
        raise _ClientError("playlist track index out of range")
    playlist.soloTrack(idx, 1 if state else 0)
    return {"index": idx, "solo": bool(playlist.isTrackSolo(idx))}


def _h_playlist_set_name(p):
    idx = int(p["index"])
    name = str(p["name"])
    if idx < 1 or idx > playlist.trackCount():
        raise _ClientError("playlist track index out of range")
    playlist.setTrackName(idx, name)
    return {"index": idx, "name": playlist.getTrackName(idx)}


def _h_playlist_set_color(p):
    idx = int(p["index"])
    if idx < 1 or idx > playlist.trackCount():
        raise _ClientError("playlist track index out of range")
    color_val = _resolve_color(p)
    playlist.setTrackColor(idx, color_val)
    return {"index": idx, "color": _color_out(_safe_playlist_track_color(idx))}


def _h_playlist_select_track(p):
    idx = int(p["index"])
    state = bool(p.get("state", True))
    if idx < 1 or idx > playlist.trackCount():
        raise _ClientError("playlist track index out of range")
    playlist.selectTrack(idx, 1 if state else 0)
    return {"index": idx, "selected": bool(playlist.isTrackSelected(idx))}


def _h_mixer_get_slot(p):
    track = int(p["track"])
    slot = int(p["slot"])
    valid = bool(plugins.isValid(track, slot))
    name = plugins.getPluginName(track, slot) if valid else ""
    mix = round(mixer.getPluginMixLevel(track, slot), 4)
    mute_fn = getattr(plugins, "getPluginMuteState", None)
    enabled = True
    if mute_fn is not None:
        with contextlib.suppress(Exception):
            enabled = not bool(mute_fn(track, slot))
    return {
        "track": track,
        "slot": slot,
        "valid": valid,
        "name": name,
        "mix": mix,
        "enabled": enabled,
    }


def _h_mixer_set_slot_mix(p):
    track = int(p["track"])
    slot = int(p["slot"])
    mix = max(0.0, min(1.0, float(p["mix"])))
    mixer.setPluginMixLevel(track, slot, mix)
    return _h_mixer_get_slot({"track": track, "slot": slot})


def _h_mixer_get_track_slots(p):
    track = int(p["track"])
    enabled = True
    if hasattr(mixer, "isTrackSlotsEnabled"):
        try:
            enabled = bool(mixer.isTrackSlotsEnabled(track))
        except Exception:
            enabled = True
    return {"track": track, "enabled": enabled}


def _h_mixer_set_track_slots(p):
    track = int(p["track"])
    enabled = bool(p["enabled"])
    if not hasattr(mixer, "enableTrackSlots"):
        raise _ClientError("track slot enable API unavailable")
    mixer.enableTrackSlots(track, 1 if enabled else 0)
    return _h_mixer_get_track_slots({"track": track})


def _h_mixer_set_slot_enabled(p):
    track = int(p["track"])
    slot = int(p["slot"])
    enabled = bool(p["enabled"])
    mute_fn = getattr(plugins, "setPluginMuteState", None)
    if mute_fn is None:
        raise _ClientError("slot mute API unavailable")
    mute_fn(track, slot, 0 if enabled else 1)
    return _h_mixer_get_slot({"track": track, "slot": slot})


def _h_mixer_get_eq(p):
    track = int(p["track"])
    mode = int(p.get("mode", 0))
    bands = []
    for b in range(3):
        try:
            gain = round(mixer.getEqGain(track, b, mode), 4)
        except TypeError:
            # Fallback if FL Studio version does not support mode
            gain = round(mixer.getEqGain(track, b), 4)

        try:
            frequency = round(mixer.getEqFrequency(track, b, mode), 4)
        except TypeError:
            frequency = round(mixer.getEqFrequency(track, b), 4)

        bands.append(
            {
                "band": b,
                "gain": gain,
                "frequency": frequency,
                "bandwidth": round(mixer.getEqBandwidth(track, b), 4)
                if hasattr(mixer, "getEqBandwidth")
                else 1.0,
                "type": _get_eq_type(track, b),
            }
        )
    return {"track": track, "mode": mode, "bands": bands}


def _get_eq_type(track, band):
    eq_type_base = getattr(midi, "REC_Mixer_EQ_Type", None)
    if eq_type_base is None:
        return 0
    try:
        plugin_id = mixer.getTrackPluginId(track, 0)
        val = mixer.getEventValue(eq_type_base + band + plugin_id)
        return int(val)
    except Exception:
        return 0


def _h_mixer_set_eq(p):
    track = int(p["track"])
    band = int(p["band"])
    if band < 0 or band > 2:
        raise _ClientError("band out of range (0-2)")
    plugin_id = mixer.getTrackPluginId(track, 0)
    flags = midi.REC_Control | midi.REC_UpdateControl | midi.REC_UpdateValue
    if "gain" in p:
        mixer.setEqGain(track, band, float(p["gain"]))
    if "frequency" in p:
        mixer.setEqFrequency(track, band, float(p["frequency"]))
    if "bandwidth" in p and hasattr(mixer, "setEqBandwidth"):
        mixer.setEqBandwidth(track, band, float(p["bandwidth"]))
    if "type" in p:
        type_val = int(p["type"])
        eq_type_base = getattr(midi, "REC_Mixer_EQ_Type", None)
        if eq_type_base is not None:
            general.processRECEvent(eq_type_base + band + plugin_id, type_val, flags)
    return _h_mixer_get_eq({"track": track})


def _eq_probe_flags(mode):
    base = {
        "control": midi.REC_Control | midi.REC_UpdateControl | midi.REC_UpdateValue,
        "update": midi.REC_UpdateControl | midi.REC_UpdateValue,
        "midi": midi.REC_UpdateControl | midi.REC_UpdateValue,
    }.get(str(mode), midi.REC_Control | midi.REC_UpdateControl | midi.REC_UpdateValue)
    if str(mode) == "midi":
        from_midi = getattr(midi, "REC_FromMIDI", None)
        if from_midi is not None:
            base |= from_midi
    for name in ("REC_SetChanged", "REC_SetTouched"):
        val = getattr(midi, name, None)
        if val is not None:
            base |= val
    return base


def _h_mixer_probe_eq_type(p):
    """Constrained internal probe for native mixer EQ type REC event writes."""
    track = int(p["track"])
    band = int(p["band"])
    if band < 0 or band > 2:
        raise _ClientError("band out of range (0-2)")
    eq_type_base = getattr(midi, "REC_Mixer_EQ_Type", None)
    if eq_type_base is None:
        raise _ClientError("native EQ type REC event unavailable")
    plugin_id = mixer.getTrackPluginId(track, 0)
    event_id = eq_type_base + band + plugin_id
    value = p.get("value", 0)
    flags = _eq_probe_flags(p.get("flags", "control"))
    general.processRECEvent(event_id, value, flags)
    out = _h_mixer_get_eq({"track": track})
    out["probe"] = {
        "event_id": event_id,
        "value": value,
        "flags": flags,
        "flags_mode": p.get("flags", "control"),
    }
    return out


def _h_mixer_format_event_value(p):
    """Format an integer REC event value into its UI string (e.g. dB or Hz)."""
    event_id = int(p["event_id"])
    value = int(p["value"])
    try:
        s = mixer.getEventIDValueString(event_id, value)
        return {"string": s, "event_id": event_id, "value": value}
    except Exception as e:
        return {"error": str(e)}


def _h_mixer_probe_eq_gain(p):
    """Probe: write EQ gain via processRECEvent (REC_Mixer_EQ_Gain).

    Params: track, band (0-2), value (0.0-1.0 normalised), flags (optional).
    Returns the EQ readback + probe metadata so the caller can compare.
    This is the processRECEvent alternative to mixer.setEqGain.
    """
    track = int(p["track"])
    band = int(p["band"])
    if band < 0 or band > 2:
        raise _ClientError("band out of range (0-2)")
    gain_base = getattr(midi, "REC_Mixer_EQ_Gain", None)
    if gain_base is None:
        raise _ClientError("REC_Mixer_EQ_Gain constant unavailable in this FL build")
    plugin_id = mixer.getTrackPluginId(track, 0)
    event_id = gain_base + band + plugin_id
    # Convert 0.0-1.0 normalised to the integer range FL expects for REC events
    value_norm = float(p.get("value", 0.5))
    # FL REC events use 0-65536 range for normalised parameters
    value_int = int(round(value_norm * 65536))
    flags = _eq_probe_flags(p.get("flags", "control"))
    general.processRECEvent(event_id, value_int, flags)
    out = _h_mixer_get_eq({"track": track})
    out["probe"] = {
        "method": "processRECEvent",
        "event_id": event_id,
        "value_norm": value_norm,
        "value_int": value_int,
        "flags": flags,
        "flags_mode": p.get("flags", "control"),
        "gain_base": gain_base,
        "plugin_id": plugin_id,
    }
    return out


def _h_mixer_probe_eq_freq(p):
    """Probe: write EQ frequency via processRECEvent (REC_Mixer_EQ_Freq)."""
    track = int(p["track"])
    band = int(p["band"])
    if band < 0 or band > 2:
        raise _ClientError("band out of range (0-2)")
    freq_base = getattr(midi, "REC_Mixer_EQ_Freq", None)
    if freq_base is None:
        raise _ClientError("REC_Mixer_EQ_Freq constant unavailable in this FL build")
    plugin_id = mixer.getTrackPluginId(track, 0)
    event_id = freq_base + band + plugin_id
    value_norm = float(p.get("value", 0.5))
    value_int = int(round(value_norm * 65536))
    flags = _eq_probe_flags(p.get("flags", "control"))
    general.processRECEvent(event_id, value_int, flags)
    out = _h_mixer_get_eq({"track": track})
    out["probe"] = {
        "method": "processRECEvent",
        "event_id": event_id,
        "value_norm": value_norm,
        "value_int": value_int,
        "flags": flags,
    }
    return out


def _h_mixer_probe_eq_q(p):
    """Probe: write EQ Q/bandwidth via processRECEvent (REC_Mixer_EQ_Q)."""
    track = int(p["track"])
    band = int(p["band"])
    if band < 0 or band > 2:
        raise _ClientError("band out of range (0-2)")
    q_base = getattr(midi, "REC_Mixer_EQ_Q", None)
    if q_base is None:
        raise _ClientError("REC_Mixer_EQ_Q constant unavailable in this FL build")
    plugin_id = mixer.getTrackPluginId(track, 0)
    event_id = q_base + band + plugin_id
    value_norm = float(p.get("value", 0.5))
    value_int = int(round(value_norm * 65536))
    flags = _eq_probe_flags(p.get("flags", "control"))
    general.processRECEvent(event_id, value_int, flags)
    out = _h_mixer_get_eq({"track": track})
    out["probe"] = {
        "method": "processRECEvent",
        "event_id": event_id,
        "value_norm": value_norm,
        "value_int": value_int,
        "flags": flags,
    }
    return out


def _h_get_time_sig(p):
    try:
        ppb = general.getRecPPB()
        ppq = general.getRecPPQ()
        if ppq > 0:
            num = ppb // ppq
            if num * ppq == ppb:
                return {"numerator": num, "denominator": 4}
            num8 = ppb // (ppq // 2)
            if num8 * (ppq // 2) == ppb:
                return {"numerator": num8, "denominator": 8}
        return {"numerator": 4, "denominator": 4}
    except Exception:
        return {"numerator": 4, "denominator": 4}


def _h_set_time_sig(p):
    num = int(p["numerator"])
    den = int(p["denominator"])
    if den not in (4, 8):
        raise _ClientError("time signature denominator must be 4 or 8 for safe readback")
    try:
        general.setNumerator(num)
        general.setDenominator(den)
    except Exception as e:
        raise _ClientError(f"failed to set time signature: {e}") from e
    return _h_get_time_sig({})


def _h_channel_set_steps(p):
    idx = int(p["channel"])
    steps_list = p.get("steps", [])
    target_pattern = int(p.get("pattern") or patterns.patternNumber())
    if target_pattern < 1 or target_pattern > patterns.patternCount():
        raise _ClientError("pattern index out of range")
    previous_pattern = patterns.patternNumber()
    if previous_pattern != target_pattern:
        patterns.jumpToPattern(target_pattern)
    pat_idx = max(0, target_pattern - 1)
    failures = []
    p_release = getattr(midi, "pRelease", None)
    p_modx = getattr(midi, "pModX", None)
    p_pitch = getattr(midi, "pPitch", None) or getattr(midi, "pFinePitch", None)
    try:
        for s_info in steps_list:
            step_idx = int(s_info["step"])
            if "value" in s_info:
                v = bool(s_info["value"])
                channels.setGridBit(idx, step_idx, 1 if v else 0)

            if "velocity" in s_info and s_info["velocity"] is not None:
                vel = max(0, min(127, int(float(s_info["velocity"]) * 127.0)))
                try:
                    channels.setStepParameterByIndex(
                        idx, pat_idx, step_idx, midi.pVelocity, vel, True
                    )
                except Exception as e:
                    failures.append({"step": step_idx, "param": "velocity", "error": str(e)})

            if "pan" in s_info and s_info["pan"] is not None:
                pan = max(0, min(128, int((float(s_info["pan"]) + 1.0) * 64.0)))
                try:
                    channels.setStepParameterByIndex(idx, pat_idx, step_idx, midi.pPan, pan, True)
                except Exception as e:
                    failures.append({"step": step_idx, "param": "pan", "error": str(e)})

            if "shift" in s_info and s_info["shift"] is not None:
                shift = max(0, min(240, int(float(s_info["shift"]) * 240.0)))
                try:
                    channels.setStepParameterByIndex(
                        idx, pat_idx, step_idx, midi.pShift, shift, True
                    )
                except Exception as e:
                    failures.append({"step": step_idx, "param": "shift", "error": str(e)})

            if "repeat" in s_info and s_info["repeat"] is not None:
                rep = max(0, min(15, int(s_info["repeat"])))
                try:
                    channels.setStepParameterByIndex(
                        idx, pat_idx, step_idx, midi.pRepeat, rep, True
                    )
                except Exception as e:
                    failures.append({"step": step_idx, "param": "repeat", "error": str(e)})

            if "release" in s_info and s_info["release"] is not None:
                if p_release is None:
                    failures.append({"step": step_idx, "param": "release", "error": "unsupported"})
                else:
                    release = max(0, min(127, int(float(s_info["release"]) * 127.0)))
                    try:
                        channels.setStepParameterByIndex(
                            idx, pat_idx, step_idx, p_release, release, True
                        )
                    except Exception as e:
                        failures.append({"step": step_idx, "param": "release", "error": str(e)})

            if "mod" in s_info and s_info["mod"] is not None:
                if p_modx is None:
                    failures.append({"step": step_idx, "param": "mod", "error": "unsupported"})
                else:
                    mod = max(0, min(255, int(float(s_info["mod"]) * 255.0)))
                    try:
                        channels.setStepParameterByIndex(idx, pat_idx, step_idx, p_modx, mod, True)
                    except Exception as e:
                        failures.append({"step": step_idx, "param": "mod", "error": str(e)})

            if "pitch" in s_info and s_info["pitch"] is not None:
                if p_pitch is None:
                    failures.append({"step": step_idx, "param": "pitch", "error": "unsupported"})
                else:
                    pitch = int(s_info["pitch"])
                    try:
                        channels.setStepParameterByIndex(
                            idx, pat_idx, step_idx, p_pitch, pitch, True
                        )
                    except Exception as e:
                        failures.append({"step": step_idx, "param": "pitch", "error": str(e)})

        with contextlib.suppress(Exception):
            channels.updateGraphEditor()
        out = _h_channel_get_steps({"channel": idx, "pattern": target_pattern})
        if failures:
            out["step_param_failures"] = failures
        return out
    finally:
        if previous_pattern != patterns.patternNumber():
            patterns.jumpToPattern(previous_pattern)


_HANDLERS = {
    "ping": _h_ping,
    "bridge_eval": lambda p: {"result": str(eval(p.get("expr", "")))},
    "get_tempo": _h_get_tempo,
    "set_tempo": _h_set_tempo,
    "general_undo": _h_general_undo,
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
    "mixer_selected": _h_mixer_selected,
    "mixer_select_track": _h_mixer_select_track,
    "channel_list": _h_channel_list,
    "channel_get": _h_channel_get,
    "mixer_set_volume": _h_mixer_set_volume,
    "mixer_set_pan": _h_mixer_set_pan,
    "mixer_set_stereo_sep": _h_mixer_set_stereo_sep,
    "mixer_get_stereo_sep": _h_mixer_get_stereo_sep,
    "mixer_set_mute": _h_mixer_set_mute,
    "mixer_set_solo": _h_mixer_set_solo,
    "mixer_set_name": _h_mixer_set_name,
    "channel_set_volume": _h_channel_set_volume,
    "channel_set_pan": _h_channel_set_pan,
    "channel_set_mute": _h_channel_set_mute,
    "channel_set_solo": _h_channel_set_solo,
    "channel_set_name": _h_channel_set_name,
    "channel_set_target": _h_channel_set_target,
    "plugin_list": _h_plugin_list,
    "plugin_get_params": _h_plugin_get_params,
    "plugin_get_param": _h_plugin_get_param,
    "plugin_set_param": _h_plugin_set_param,
    "mixer_get_routing": _h_mixer_get_routing,
    "mixer_get_routing_all": _h_mixer_get_routing_all,
    "mixer_get_free_track": _h_mixer_get_free_track,
    "channel_routing_summary": _h_channel_routing_summary,
    "mixer_set_route": _h_mixer_set_route,
    "mixer_get_peaks": _h_mixer_get_peaks,
    "mixer_get_all_peaks": _h_mixer_get_all_peaks,
    "mixer_set_color": _h_mixer_set_color,
    "mixer_get_color": _h_mixer_get_color,
    "channel_set_color": _h_channel_set_color,
    "channel_get_color": _h_channel_get_color,
    "plugin_preset": _h_plugin_preset,
    "plugin_get_preset_name": _h_plugin_get_preset_name,
    "api_probe": _h_api_probe,
    "arrange_new_pattern": _h_arrange_new_pattern,
    "arrange_clone_pattern": _h_arrange_clone_pattern,
    "arrange_add_marker": _h_arrange_add_marker,
    "channel_select": _h_channel_select,
    "channel_selected": _h_channel_selected,
    "ensure_piano_roll": _h_ensure_piano_roll,
    "pattern_list": _h_pattern_list,
    "pattern_select": _h_pattern_select,
    "pattern_rename": _h_pattern_rename,
    "pattern_get_length": _h_pattern_get_length,
    "pattern_set_color": _h_pattern_set_color,
    "pattern_set_length": _h_pattern_set_length,
    "pattern_find_empty": _h_pattern_find_empty,
    "channel_get_steps": _h_channel_get_steps,
    "pattern_get": _h_pattern_get,
    "pattern_selected": _h_pattern_selected,
    "playlist_get_track": _h_playlist_get_track,
    "playlist_list_tracks": _h_playlist_list_tracks,
    "playlist_set_mute": _h_playlist_set_mute,
    "playlist_set_solo": _h_playlist_set_solo,
    "playlist_set_name": _h_playlist_set_name,
    "playlist_set_color": _h_playlist_set_color,
    "playlist_select_track": _h_playlist_select_track,
    "mixer_get_slot": _h_mixer_get_slot,
    "mixer_set_slot_mix": _h_mixer_set_slot_mix,
    "mixer_get_track_slots": _h_mixer_get_track_slots,
    "mixer_set_track_slots": _h_mixer_set_track_slots,
    "mixer_set_slot_enabled": _h_mixer_set_slot_enabled,
    "mixer_get_eq": _h_mixer_get_eq,
    "mixer_set_eq": _h_mixer_set_eq,
    "mixer_probe_eq_type": _h_mixer_probe_eq_type,
    "mixer_probe_eq_gain": _h_mixer_probe_eq_gain,
    "mixer_probe_eq_freq": _h_mixer_probe_eq_freq,
    "mixer_probe_eq_q": _h_mixer_probe_eq_q,
    "mixer_format_event_value": _h_mixer_format_event_value,
    "get_time_sig": _h_get_time_sig,
    "set_time_sig": _h_set_time_sig,
    "channel_set_steps": _h_channel_set_steps,
}
