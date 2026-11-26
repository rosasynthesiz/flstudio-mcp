"""Build a type-1 multi-track .mid from an arrangement spec (uses mido, a CORE
dependency -- no extra install). Bulk-arrangement path: Claude supplies the
whole arrangement, this writes ONE Standard MIDI File the user imports into FL.

Spec: tracks = [{"name", "channel"(0-15), "notes": [{"pitch", "start_bars",
"length_bars", "velocity"}]}]. Times are in BARS (like the note bridge);
velocity is 0..1 (0.787 ~= MIDI 100) or a raw 1..127 int. PURE except for the
final save in write_midi().
"""
from __future__ import annotations

import os


def _vel(v):
    v = float(v)
    out = int(round(v * 127)) if v <= 1.0 else int(round(v))
    return max(1, min(127, out))


def build_midi(tracks, bpm, ppq=480, beats_per_bar=4):
    """Spec -> mido.MidiFile (type 1). A conductor track holds tempo + time-sig;
    each spec track becomes one MIDI track. Absolute-tick events are sorted
    (note-offs before note-ons at a tie) then emitted as deltas."""
    import mido
    ticks_per_bar = int(ppq * beats_per_bar)
    mf = mido.MidiFile(type=1, ticks_per_beat=ppq)

    cond = mido.MidiTrack()
    mf.tracks.append(cond)
    cond.append(mido.MetaMessage("track_name", name="Tempo", time=0))
    cond.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(float(bpm)), time=0))
    cond.append(mido.MetaMessage("time_signature", numerator=int(beats_per_bar),
                                 denominator=4, time=0))
    cond.append(mido.MetaMessage("end_of_track", time=0))

    for t in tracks:
        tr = mido.MidiTrack()
        mf.tracks.append(tr)
        tr.append(mido.MetaMessage("track_name", name=str(t.get("name") or "Track")[:40], time=0))
        ch = int(t.get("channel", 0)) & 0x0F
        events = []                                   # (abs_tick, order, msg)
        for n in t.get("notes", []):
            pitch = max(0, min(127, int(n["pitch"])))
            vel = _vel(n.get("velocity", 0.787))
            st = max(0, int(round(float(n["start_bars"]) * ticks_per_bar)))
            dur = max(1, int(round(float(n["length_bars"]) * ticks_per_bar)))
            events.append((st, 1, mido.Message("note_on", note=pitch, velocity=vel, channel=ch)))
            events.append((st + dur, 0, mido.Message("note_off", note=pitch, velocity=0, channel=ch)))
        events.sort(key=lambda e: (e[0], e[1]))       # off before on at a tie
        prev = 0
        for abs_t, _order, msg in events:
            msg.time = abs_t - prev
            prev = abs_t
            tr.append(msg)
        tr.append(mido.MetaMessage("end_of_track", time=0))
    return mf


def write_midi(tracks, bpm, path, ppq=480, beats_per_bar=4):
    """Build + save the .mid to ``path`` (creating parent dirs). Returns the
    mido.MidiFile (for readback/inspection)."""
    mf = build_midi(tracks, bpm, ppq=ppq, beats_per_bar=beats_per_bar)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    mf.save(path)
    return mf
