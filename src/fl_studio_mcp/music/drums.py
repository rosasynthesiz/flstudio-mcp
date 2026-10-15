"""Drums to MIDI: find every hit in a drum loop or stem and sort it into kick,
snare, clap, closed or open hi-hat by where its energy sits and how long it
rings. Heuristic, no model; librosa/numpy are imported lazily.
"""
from __future__ import annotations

# General MIDI drum notes
KICK, SNARE, CLAP, HIHAT, OPEN_HAT = 36, 38, 39, 42, 46
NAMES = {KICK: "kick", SNARE: "snare", CLAP: "clap", HIHAT: "closed hat", OPEN_HAT: "open hat"}


def classify(low, body, high, decay_ms):
    """Shares of energy below 150 Hz, below 1 kHz and above 5 kHz in the first
    60 ms, and the decay time. Returns a General MIDI drum note."""
    if high > 0.5:                                   # hats: mostly above 5 kHz
        return OPEN_HAT if decay_ms >= 150 else HIHAT
    if low > 0.45:                                   # kick: mostly sub/low
        return KICK
    return SNARE if body >= 0.15 else CLAP           # mid hit: a snare has a body


def _decay_ms(y, start, end, sr, limit=0.5):
    """Time from the hit's loudest moment until it falls 20 dB, measured only
    up to the next hit (``end``) so a following hit isn't taken for this one."""
    import numpy as np

    tail = y[start:min(end, start + int(limit * sr))]
    if not len(tail):
        return 0.0
    energy = np.convolve(tail ** 2, np.ones(220) / 220, "same")
    top = int(np.argmax(energy))
    below = np.where(energy[top:] < energy[top] * 0.01)[0]
    return float(below[0] if len(below) else len(energy) - top) / sr * 1000.0


def _attack(y, onset, floor, sr):
    """Refine a detected onset to the attack: the first moment, at most 60 ms
    earlier and never before ``floor`` (the previous hit), where the sound
    reaches half the peak of the next 30 ms."""
    import numpy as np

    lo = max(floor, onset - int(0.06 * sr))
    hi = min(len(y), onset + int(0.03 * sr))
    if hi - lo < 8:
        return onset
    rms = np.sqrt(np.convolve(y[lo:hi] ** 2, np.ones(64) / 64, "same"))
    above = np.where(rms >= 0.5 * rms.max())[0]
    return lo + int(above[0]) if len(above) else onset


def beat_offset(y, sr, bpm):
    """Seconds from the start of the audio to the first beat of the grid, from
    librosa's beat tracker (style-neutral: no assumption about what plays on
    the beat). 0.0 when no beats are found."""
    import librosa
    import numpy as np

    _tempo, beats = librosa.beat.beat_track(y=y, sr=sr, bpm=bpm, units="time", tightness=400)
    if len(beats) < 4:
        return 0.0
    beat = 60.0 / bpm
    phase = np.angle(np.mean(np.exp(2j * np.pi * (np.asarray(beats) / beat % 1.0))))
    return float(phase / (2 * np.pi) % 1.0 * beat)


def drum_notes(path, bpm, quantize=1 / 16.0, align=True):
    """Drum audio to notes {pitch, kind, time_bars, length_bars, velocity}.
    align: shift the grid so beats fall on whole beats (the audio rarely
    starts exactly on one)."""
    import librosa
    import numpy as np
    from scipy.signal import butter, sosfilt

    y, sr = librosa.load(path, sr=22050, mono=True)
    offset = beat_offset(y, sr, bpm) if align else 0.0
    pad = int(0.05 * sr)                       # lets a hit at 0.0 s be detected
    y = np.concatenate([np.zeros(pad), y])
    y_high = sosfilt(butter(4, 5000, "highpass", fs=sr, output="sos"), y)
    env = librosa.onset.onset_strength(y=y, sr=sr)
    # Detected onsets lag the attack a little; refine each one ourselves.
    # (librosa's backtracking moves a hit to the quietest point before it,
    # which can lie in the previous hit's tail: a clap after an open hat.)
    detected = librosa.onset.onset_detect(onset_envelope=env, sr=sr, units="samples")
    onsets, floor = [], 0
    for d in detected:
        a = _attack(y, int(d), floor, sr)
        onsets.append(a)
        floor = int(d)
    peak = float(env.max()) or 1.0
    barlen = 4.0 * 60.0 / bpm
    win = int(0.06 * sr)
    freqs = np.fft.rfftfreq(win, 1.0 / sr)
    notes, last = [], None                     # last kept hit: (start, rms, pitch)
    ends = list(onsets[1:]) + [len(y)]
    for start, end in zip(onsets, ends, strict=True):
        seg = y[start:start + win]
        if len(seg) < win:
            seg = np.pad(seg, (0, win - len(seg)))
        rms = float(np.sqrt(np.mean(seg ** 2)))
        # Only the NEW energy: what rings on from earlier hits (a kick tail
        # under a hi-hat) is subtracted using the window just before the hit.
        before = y[max(0, start - win):start]
        before = np.pad(before, (win - len(before), 0))
        spec = np.clip(np.abs(np.fft.rfft(seg * np.hanning(win))) ** 2
                       - np.abs(np.fft.rfft(before * np.hanning(win))) ** 2, 0, None)
        total = float(spec.sum()) or 1.0
        high = float(spec[freqs > 5000].sum()) / total
        pitch = classify(float(spec[freqs < 150].sum()) / total,
                         float(spec[freqs < 1000].sum()) / total, high,
                         _decay_ms(y_high if high > 0.5 else y, start, end, sr))
        # A much quieter hit of the same kind right after one is its tail
        # (e.g. a kick's pitch sweep), not a new hit.
        if (last is not None and pitch == last[2] and start - last[0] < 0.25 * sr
                and rms < 0.35 * last[1]):
            continue
        last = (start, rms, pitch)
        frame = int(librosa.samples_to_frames(start))
        t = (start - pad) / sr - offset
        if t < -0.5 * (quantize or 0.0625) * barlen:
            continue                               # pickup before the first grid beat
        t = max(0.0, t / barlen)
        if quantize:
            t = round(round(t / quantize) * quantize, 6)
        strength = float(env[min(frame, len(env) - 1)]) / peak
        notes.append({"pitch": pitch, "kind": NAMES[pitch], "time_bars": t,
                      "length_bars": quantize or 0.0625,
                      "velocity": round(min(1.0, 0.3 + 0.7 * strength), 3)})
    return notes


def to_steps(notes, bars=1, start_bar=0, steps_per_bar=16):
    """Notes -> {kind: [step indexes]} for the step sequencer, over ``bars``
    bars starting at ``start_bar`` (one step = 1/16 at the default)."""
    out = {}
    for n in notes:
        step = int(round((n["time_bars"] - start_bar) * steps_per_bar))
        if 0 <= step < bars * steps_per_bar:
            out.setdefault(n["kind"], set()).add(step)
    return {k: sorted(v) for k, v in out.items()}


def estimate_tempo(path):
    """Tempo of an audio file in BPM (beat tracker; halved above 180)."""
    import librosa
    import numpy as np

    y, sr = librosa.load(path, sr=22050, mono=True, duration=120)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo).ravel()[0])
    return bpm / 2.0 if bpm > 180.0 else bpm


def available() -> bool:
    try:
        import librosa  # noqa: F401
        import scipy  # noqa: F401
        return True
    except Exception:
        return False


def summary(notes):
    counts = {}
    for n in notes:
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1
    return counts
