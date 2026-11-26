"""Controller side of E-5: current-preset name read, undo handler, plugins probe.

The controller imports FL-only modules, so it is loaded against stubs once
(sys.modules saved/restored); the module keeps direct references afterwards.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_CONTROLLER_PATH = (Path(__file__).resolve().parents[1] / "fl_controller"
                    / "FLStudioMCP" / "device_FLStudioMCP.py")
_STUB_NAMES = ("channels", "device", "general", "midi", "mixer", "patterns",
               "playlist", "plugins", "transport", "ui", "arrangement", "utils")


def _load_controller():
    saved = {n: sys.modules.get(n) for n in _STUB_NAMES}
    stubs = {}
    for name in _STUB_NAMES:
        stubs[name] = types.ModuleType(name)
        sys.modules[name] = stubs[name]
    try:
        spec = importlib.util.spec_from_file_location(
            "flstudio_mcp_controller_e5", _CONTROLLER_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for name, prev in saved.items():
            if prev is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev
    return mod, stubs


_CONTROLLER, STUBS = _load_controller()


@pytest.fixture
def preset_calls():
    plugins = STUBS["plugins"]
    STUBS["midi"].GPN_GetCurrentPreset = 5
    plugins.getPresetCount = lambda _t, _s: 13
    plugins.getPluginName = lambda _t, _s: "Furi"
    seen = []

    def name(track, slot, flag, pidx):
        seen.append((track, slot, flag, pidx))
        return f"preset-{pidx}"

    plugins.getName = name
    yield seen
    if hasattr(STUBS["midi"], "GPN_GetCurrentPreset"):
        del STUBS["midi"].GPN_GetCurrentPreset


def test_current_preset_name_uses_gpn_constant(preset_calls):
    out = _CONTROLLER._h_plugin_preset({"track": 1, "slot": 0, "op": "info"})
    assert out["name_f6"] == "preset-5"
    assert (1, 0, 6, 5) in preset_calls
    assert (1, 0, 3, 0) in preset_calls


def test_current_preset_name_falls_back_to_zero(preset_calls):
    del STUBS["midi"].GPN_GetCurrentPreset
    out = _CONTROLLER._h_plugin_preset({"track": 1, "slot": 0})
    assert out["name_f6"] == "preset-0"


def test_undo_handler_calls_general_undo_up():
    called = []
    STUBS["general"].undoUp = lambda: called.append(True)
    out = _CONTROLLER._h_undo({})
    assert out == {"ok": True, "undid": True}
    assert called == [True]


def test_undo_handler_reports_failure():
    def boom():
        raise RuntimeError("sandbox")

    STUBS["general"].undoUp = boom
    out = _CONTROLLER._h_undo({})
    assert out["ok"] is False
    assert "undoUp: sandbox" in out["error"]


def test_api_probe_dir_lists_the_plugins_module():
    STUBS["plugins"].getPresetCount = lambda *_a: 0
    out = _CONTROLLER._h_api_probe({"op": "dir", "module": "plugins"})
    assert out["module"] == "plugins"
    assert "getPresetCount" in out["names"]


def test_handlers_register_undo():
    assert "undo" in _CONTROLLER._HANDLERS
    assert _CONTROLLER._HANDLERS["undo"] is _CONTROLLER._h_undo
