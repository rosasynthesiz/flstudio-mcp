"""Run with CONTROLLER_PATH pointing at the isolated controller under review."""
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest


@pytest.mark.parametrize('visible', [False, True, None])
def test_select_only_retargets_visible_piano_roll(monkeypatch, visible):
    names = ('channels device general midi mixer patterns playlist plugins transport ui arrangement utils').split()
    stubs = {name: types.ModuleType(name) for name in names}
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    calls = []
    channels, ui = stubs['channels'], stubs['ui']
    channels.channelCount = lambda: 2
    channels.selectOneChannel = lambda index: calls.append(('select', index))
    channels.getChannelName = lambda index: 'B'
    channels.channelNumber = lambda: 1
    stubs['midi'].widPianoRoll = 4
    if visible is not None:
        ui.getVisible = lambda wid: visible
    ui.hideWindow = lambda wid: calls.append(('hide', wid))
    ui.showWindow = lambda wid: calls.append(('show', wid))
    ui.setFocused = lambda wid: calls.append(('focus', wid))
    path = os.environ.get('CONTROLLER_PATH', str(Path(__file__).resolve().parents[1]
                          / 'fl_controller/FLStudioMCP/device_FLStudioMCP.py'))
    spec = importlib.util.spec_from_file_location('visibility_review', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module._h_channel_select({'channel': 1})
    assert result['ok']
    assert result['piano_roll_retargeted'] is (visible is True)
    assert calls == ([('select', 1), ('hide', 4), ('show', 4), ('focus', 4)]
                     if visible is True else [('select', 1)])
