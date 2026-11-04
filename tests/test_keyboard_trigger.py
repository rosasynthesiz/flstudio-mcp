"""Win32 key sequence contract without sending any real keyboard events."""
import ctypes
from types import SimpleNamespace

import pytest

from fl_studio_mcp import pyscript_trigger as trigger


@pytest.mark.parametrize('layout', ['English', 'Tamil'])
def test_uses_layout_independent_virtual_keys(monkeypatch, layout):
    events = []
    user32 = SimpleNamespace(
        MapVirtualKeyW=lambda vk, mode: vk + 100,
        keybd_event=lambda *event: events.append(event),
        VkKeyScanA=lambda *_: pytest.fail('Layout-sensitive lookup must not be used: ' + layout))
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=user32), raising=False)
    monkeypatch.setattr(trigger.time, 'sleep', lambda *_: None)
    trigger._send_ctrl_alt_y()
    assert events == [(vk, vk + 100, flags, 0) for flags, keys in
                      [(0, [0x11, 0x12, 0x59]), (2, [0x59, 0x12, 0x11])]
                      for vk in keys]


def test_modifiers_released_after_keydown_failure(monkeypatch):
    events = []

    def send(vk, scan, flags, extra):
        events.append((vk, flags))
        if vk == 0x59 and flags == 0:
            raise RuntimeError('injected send failure')

    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(
        MapVirtualKeyW=lambda *_: 0, keybd_event=send)), raising=False)
    monkeypatch.setattr(trigger.time, 'sleep', lambda *_: None)
    with pytest.raises(RuntimeError):
        trigger._send_ctrl_alt_y()
    assert events[-3:] == [(0x59, 2), (0x12, 2), (0x11, 2)]
