"""Safe refusal regression for PR12's calibration primitive."""
import pytest

from fl_studio_mcp import safety
from fl_studio_mcp.music import calibration


def test_calibration_dry_run_refuses_before_any_bridge_call():
    class Bridge:
        def call(self, *_):
            pytest.fail('Dry-run calibration must not access or mutate the bridge')

    safety.set_dry_run(True)
    try:
        with pytest.raises(ValueError, match='dry-run'):
            calibration.sweep_param(Bridge(), 0, 0, 0, steps=3)
    finally:
        safety.set_dry_run(False)
