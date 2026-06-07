#!/usr/bin/env python3
import json
from pathlib import Path


def main():
    root = Path("/Users/venkatesha/Documents/Projects/fl-studio-mcp-macos")
    scratch = root / "scratch"
    kb_fl_api = root / "knowledgebase" / "fl_api"

    # 1. Frequency Mapping from eq_formula_data.json
    eq_form_path = scratch / "eq_formula_data.json"
    if eq_form_path.exists():
        with open(eq_form_path) as f:
            eq_data = json.load(f)

        freq_mappings = []
        for point in eq_data.get("freq", []):
            try:
                hz_val = float(point["str"].replace("Hz", ""))
                freq_mappings.append(
                    {
                        "normalized": point["norm"],
                        "hz": hz_val,
                        "confidence": "measured_once",
                        "source": "scratch/find_eq_formula.py",
                    }
                )
            except:
                pass

        # Also add Gain mapping from test_eq_ch90_band0.py and flat EQ default
        gain_mappings = [
            {
                "normalized": 0.0,
                "db": -18.0,
                "confidence": "implementation_verified",
                "source": "scratch/test_eq_ch90_band0.py",
            },
            {
                "normalized": 0.5,
                "db": 0.0,
                "confidence": "implementation_verified",
                "source": "scratch/eq_diagnosis.json flat EQ default",
            },
            {
                "normalized": 1.0,
                "db": 18.0,
                "confidence": "hypothesis",
                "source": "extrapolated from max limit",
            },
        ]

        eq_calib_path = kb_fl_api / "mixer_eq_calibration.json"
        if eq_calib_path.exists():
            with open(eq_calib_path) as f:
                eq_calib = json.load(f)

            # Update Gain mapping
            gain_domain = next((d for d in eq_calib if d["domain"] == "eq_gain"), None)
            if gain_domain:
                gain_domain["mapping"] = gain_mappings

            # Add Freq domain
            freq_domain = {
                "domain": "eq_frequency",
                "parameter": "mixer.setEqFrequency",
                "api_setter": "mixer.setEqFrequency",
                "api_getter": "mixer.getEqFrequency",
                "value_type": "normalized_float",
                "valid_range": [0.0, 1.0],
                "confidence": "measured_once",
                "mapping": freq_mappings,
            }
            eq_calib.append(freq_domain)

            with open(eq_calib_path, "w") as f:
                json.dump(eq_calib, f, indent=2)
                print("Updated mixer_eq_calibration.json with Freq and Gain data.")

    # 2. Volume Mapping from fader_calibration.json
    fader_path = scratch / "fader_calibration.json"
    if fader_path.exists():
        with open(fader_path) as f:
            fader_data = json.load(f)

        vol_mappings = []
        for pair in fader_data:
            if pair[1] == "-Infinity":
                db_val = -float("inf")
            else:
                db_val = float(pair[1])
            vol_mappings.append(
                {
                    "normalized": pair[0],
                    "db": db_val,
                    "confidence": "implementation_verified",
                    "source": "scratch/fader_calibration.json",
                }
            )

        vol_calib = [
            {
                "domain": "mixer_volume",
                "parameter": "mixer.setTrackVolume",
                "api_setter": "mixer.setTrackVolume",
                "api_getter": "mixer.getTrackVolume",
                "value_type": "normalized_float",
                "valid_range": [0.0, 1.0],
                "confidence": "implementation_verified",
                "mapping": vol_mappings,
            }
        ]

        with open(kb_fl_api / "mixer_volume_calibration.json", "w") as f:
            json.dump(vol_calib, f, indent=2)
            print("Created mixer_volume_calibration.json")

        # Update mixer_volume_pan.md
        vol_pan_md = kb_fl_api / "mixer_volume_pan.md"
        vol_pan_md.write_text(
            "# Mixer Volume & Pan\\n\\nMixer volume has been fully calibrated. See `mixer_volume_calibration.json`.\\n0.8 normalized = 0.0 dB.\\n0.0 normalized = -Infinity dB.\\n1.0 normalized = +5.6 dB.\\n"
        )


if __name__ == "__main__":
    main()
