import json
import os
import sys
from pathlib import Path

import pytest

# Ensure src is in path to import tools
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp.tools.internal_eq import (
    _verify_normalized,
    set_internal_mixer_eq_frequency_hz,
    set_internal_mixer_eq_gain_db,
)

KB_ROOT = Path("knowledgebase")


def test_json_files_are_valid():
    """Verify that all JSON files in the knowledgebase are structurally valid."""
    json_files = []
    for root, _, files in os.walk(KB_ROOT):
        for file in files:
            if file.endswith(".json"):
                json_files.append(Path(root) / file)

    assert len(json_files) > 0, "No JSON files found in knowledgebase!"

    for jf in json_files:
        try:
            with open(jf, encoding="utf-8") as f:
                data = json.load(f)
            assert data is not None
        except Exception as e:
            pytest.fail(f"JSON validation failed for {jf}: {e}")


def test_verify_normalized():
    """Test that the normalized validator rejects out of bounds values."""
    assert _verify_normalized(0.0) == 0.0
    assert _verify_normalized(1.0) == 1.0
    assert _verify_normalized(0.5) == 0.5

    with pytest.raises(ValueError, match="out of bounds"):
        _verify_normalized(-0.1)

    with pytest.raises(ValueError, match="out of bounds"):
        _verify_normalized(1.1)


def test_safe_eq_gain_db_missing_mapping():
    """Test that set_internal_mixer_eq_gain_db safely aborts if the dB value isn't mapped."""
    res = set_internal_mixer_eq_gain_db(track=1, band="low", db=-99.9)
    assert "error" in res
    assert "DO NOT use linear interpolation" in res["error"]
    assert res.get("message") == "Manual runtime verification required to map this dB value."


def test_safe_eq_frequency_hz_missing_mapping():
    """Test that set_internal_mixer_eq_frequency_hz safely aborts if the Hz value isn't mapped."""
    res = set_internal_mixer_eq_frequency_hz(track=1, band="high", hz=12345.6)
    assert "error" in res
    assert "DO NOT use linear interpolation" in res["error"]
    assert res.get("message") == "Manual runtime verification required to map this Hz value."
