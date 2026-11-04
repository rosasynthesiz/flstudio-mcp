"""Repair only the affected plugin parameter-name source, not ordinary text."""
from types import SimpleNamespace
import sys

import pytest


@pytest.mark.parametrize("command,params", [
    ("plugin_get_params", {"track": 0, "slot": 9, "start": 0}),
    ("plugin_get_param", {"track": 0, "slot": 9, "param": 0}),
    ("plugin_set_param", {"track": 0, "slot": 9, "param": 0, "value": 0.5}),
])
@pytest.mark.parametrize("source,expected", [
    ("杈撳叆澧炵泭", "输入增益"), ("鐢靛钩鍖归厤", "电平匹配"),
    ("鏃佽矾", "旁路"), ("杈撳嚭澧炵泭", "输出增益"),
    ("输入增益", "输入增益"), ("Emphasis", "Emphasis"), ("", ""),
    ("湿", "湿"), ("L路", "L路"),
])
def test_plugin_parameter_names_are_consistent(controller, monkeypatch, command, params,
                                               source, expected):
    monkeypatch.setattr(sys, "platform", "win32")
    controller.plugins = SimpleNamespace(
        isValid=lambda t, s: True, getParamCount=lambda t, s: 1,
        getPluginName=lambda t, s: "Emphasizer", getParamName=lambda i, t, s: source,
        getParamValue=lambda i, t, s: 0.5, getParamValueString=lambda i, t, s: "关闭",
        setParamValue=lambda v, i, t, s: None,
    )
    reply = controller._dispatch(command, params)
    if command == "plugin_get_params":
        if source == "":
            assert reply["params"] == []
            return
        reply = reply["params"][0]
    assert reply["name"] == expected
    assert reply["s"] == "关闭", "Do not re-decode correct display strings"


@pytest.mark.parametrize("platform,plugin", [
    ("win32", "Other Plugin"), ("darwin", "Emphasizer"), ("linux", "Emphasizer"),
])
def test_known_repair_is_limited_to_verified_plugin_and_platform(controller, monkeypatch,
                                                               platform, plugin):
    monkeypatch.setattr(sys, "platform", platform)
    controller.plugins = SimpleNamespace(
        isValid=lambda t, s: True, getPluginName=lambda t, s: plugin,
        getParamName=lambda i, t, s: "杈撳叆澧炵泭", getParamValue=lambda i, t, s: 0.5,
        getParamValueString=lambda i, t, s: "0 dB",
    )
    result = controller._dispatch("plugin_get_param", {"track": 0, "slot": 9, "param": 0})
    assert result["name"] == "杈撳叆澧炵泭"
