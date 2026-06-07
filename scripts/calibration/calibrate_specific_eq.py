#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fl_studio_mcp.connection import get_bridge


def format_event(bridge, event_id, norm_val):
    val_int = int(round(norm_val * 65536))
    r = bridge.call(
        "mixer_format_event_value", {"event_id": event_id, "value": val_int}, timeout=2.0
    )
    return r.get("string", "")


def find_exact_norm(bridge, event_id, target_str, is_gain=False):
    # Dense search for exact strings.
    # Since get_format_event can take some time, we do a coarse-to-fine search.
    # Gain: 0.5 = 0.0dB. < 0.5 is negative dB.
    # Freq: 0.0 = 10Hz, 1.0 = 16000Hz.

    print(f"Searching for {target_str}...")
    best_match = None
    best_diff = 999999

    steps = 1000
    for i in range(steps + 1):
        norm = i / steps
        s = format_event(bridge, event_id, norm)

        # Parse number from string for better comparison if exact match fails
        try:
            val = float(s.replace("dB", "").replace("Hz", "").strip())
            target_val = float(target_str.replace("dB", "").replace("Hz", "").strip())
            diff = abs(val - target_val)
            if diff < best_diff:
                best_diff = diff
                best_match = (norm, s, val)

            if diff == 0:
                print(f"EXACT MATCH for {target_str}: Norm = {norm:.4f}")
                return norm, s, val
        except:
            pass

    if best_match:
        print(f"Best match for {target_str}: Norm = {best_match[0]:.4f} -> {best_match[1]}")
        return best_match
    return None, None, None


def main():
    bridge = get_bridge()
    try:
        bridge.check_alive()
    except Exception:
        print("ERROR: FL Studio Bridge not reachable. Is FL Studio running?")
        return 1

    print("Bridge connected! Fetching Event IDs for EQ...")

    try:
        r = bridge.call(
            "mixer_probe_eq_gain", {"track": 1, "band": 0, "value": 0.5, "flags": "control"}
        )
        gain_event_id = r["probe"]["event_id"]

        r2 = bridge.call(
            "mixer_probe_eq_freq", {"track": 1, "band": 0, "value": 0.5, "flags": "control"}
        )
        freq_event_id = r2["probe"]["event_id"]
    except Exception as e:
        print(f"Error fetching Event IDs: {e}")
        return 1

    targets_gain = ["-3.0dB", "-6.0dB", "-12.0dB"]
    targets_freq = ["25Hz", "30Hz", "120Hz", "150Hz", "220Hz", "250Hz", "400Hz"]

    results = {"gain": [], "freq": []}

    for t in targets_gain:
        n, s, v = find_exact_norm(bridge, gain_event_id, t, is_gain=True)
        if n is not None:
            results["gain"].append(
                {
                    "normalized": round(n, 4),
                    "db": v,
                    "confidence": "measured_once",
                    "source": "live_calibration_script",
                }
            )

    for t in targets_freq:
        n, s, v = find_exact_norm(bridge, freq_event_id, t, is_gain=False)
        if n is not None:
            results["freq"].append(
                {
                    "normalized": round(n, 4),
                    "hz": v,
                    "confidence": "measured_once",
                    "source": "live_calibration_script",
                }
            )

    out_file = Path(__file__).parent / "specific_eq_calibration.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to {out_file}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
