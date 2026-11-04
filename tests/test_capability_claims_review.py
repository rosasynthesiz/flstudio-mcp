"""Capability claims must agree with platform support without touching FL."""
from types import SimpleNamespace

import pytest

from fl_studio_mcp import capabilities, connection
from fl_studio_mcp.music import vst_params


def test_linux_does_not_claim_automated_note_trigger(monkeypatch):
    monkeypatch.setattr(capabilities, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(connection, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.delenv('FLSTUDIO_MCP_VIRTUAL_PORTS', raising=False)
    result = capabilities.describe_capabilities()
    assert result['note_bridge']['focus_automated'] is False
    assert 'unsupported' in result['note_bridge']['focus_method']
    assert not any('piano-roll note writing' in x for x in result['automated'])
    assert any('ALSA' in x for x in result['manual_steps'])
    assert not any('IAC Driver' in x for x in result['manual_steps'])


@pytest.mark.parametrize('params,tier', [([], 'empty'),
    ([{'name': 'Param 1', 's': '.5'}], 'opaque'),
    ([{'name': 'Cutoff', 's': ''}], 'partial'),
    ([{'name': 'Cutoff', 's': '200 Hz'}], 'full')])
def test_exposure_tier_degrades_explicitly(params, tier):
    assert vst_params.classify_param_exposure(params)['tier'] == tier
