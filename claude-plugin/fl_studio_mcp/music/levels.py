"""Track-level measurement from mixer peaks, for level-aware intents.

Peaks (mixer.getTrackPeaks) are only meaningful while audio is PLAYING.
measure_track_level samples a short window and reports playing=False when
nothing registers (the silence guard), so callers can fall back gracefully.
"""
from __future__ import annotations

import math
import time

from .. import protocol

SILENCE = 1e-4          # linear peak below this over the whole window == no signal


def peak_to_db(peak):
    """Linear peak -> dBFS, or None for silence/zero (avoids -inf/log(0))."""
    if peak is None or peak <= 1e-6:
        return None
    return 20.0 * math.log10(peak)


def measure_track_level(bridge, track, samples=20, interval_ms=100):
    """Sample peak_max over a window. Returns:
        {track, playing, avg_db, peak_db, n_reads}
    playing=False (and avg/peak None) if every read is ~silence -- i.e. the
    transport is stopped or the track passes no audio.
    """
    vals = []
    for _ in range(max(1, int(samples))):
        v = bridge.call(protocol.CMD_MIXER_GET_PEAKS, {"track": track}).get("peak_max")
        if v is not None:
            vals.append(v)
        time.sleep(max(0.0, interval_ms / 1000.0))

    usable = [v for v in vals if v >= SILENCE]
    if not usable:
        return {"track": track, "playing": False,
                "avg_db": None, "peak_db": None, "n_reads": len(vals)}

    avg = sum(usable) / len(usable)
    return {"track": track, "playing": True,
            "avg_db": round(peak_to_db(avg), 2),
            "peak_db": round(peak_to_db(max(usable)), 2),
            "n_reads": len(vals)}


def measure_many(bridge, tracks, samples=15, interval_ms=100):
    """Sustained peak sampling for MANY tracks over ONE shared window.

    Round-robins reads (all tracks per tick, then sleep) so the whole window is
    shared -- N tracks cost ~one window, NOT samples*interval_ms per track.
    Reuses peak_to_db + the SILENCE guard. Per-read errors are swallowed (a
    track that errors just gets fewer reads). Returns::

        {track: {track, playing, avg_db, peak_db, peak_lin, n_reads}}
    """
    acc = {t: [] for t in tracks}
    for _ in range(max(1, int(samples))):
        for t in tracks:
            try:
                v = bridge.call(protocol.CMD_MIXER_GET_PEAKS, {"track": t}).get("peak_max")
            except Exception:
                v = None
            if v is not None:
                acc[t].append(v)
        time.sleep(max(0.0, interval_ms / 1000.0))

    out = {}
    for t, vals in acc.items():
        usable = [v for v in vals if v >= SILENCE]
        if usable:
            out[t] = {"track": t, "playing": True,
                      "avg_db": round(peak_to_db(sum(usable) / len(usable)), 2),
                      "peak_db": round(peak_to_db(max(usable)), 2),
                      "peak_lin": max(usable), "n_reads": len(vals)}
        else:
            out[t] = {"track": t, "playing": False, "avg_db": None,
                      "peak_db": None, "peak_lin": None, "n_reads": len(vals)}
    return out
