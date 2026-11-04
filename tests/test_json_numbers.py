"""Catch signed zero at the controller, MIDI, and actual daemon TCP boundaries."""
import json
import math
import socket
import threading
from types import SimpleNamespace

import pytest

from fl_studio_mcp import daemon, protocol


def assert_lossless_numbers(value):
    if isinstance(value, float):
        assert math.isfinite(value), value
        if value == 0.0:
            assert math.copysign(1, value) == 1, "negative zero cannot round-trip through JS JSON"
    elif isinstance(value, dict):
        for child in value.values():
            assert_lossless_numbers(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            assert_lossless_numbers(child)


@pytest.mark.parametrize("norm,expected", [(0.7999999523162842, 0.0), (-0.0, -120.0),
                                         (0.7965, -0.04)])
def test_volume_output_canonicalizes_only_zero(controller, norm, expected):
    result = controller._vol_out(norm)
    assert result["vol_db"] == expected
    assert_lossless_numbers(result)


@pytest.mark.parametrize("command,params", [
    ("mixer_get_track", {"index": 0}), ("mixer_list_tracks", {"start": 0}),
    ("channel_get", {"index": 0}), ("channel_list", {"start": 0}),
])
def test_volume_commands_return_canonical_numbers(controller, command, params):
    controller.mixer = SimpleNamespace(
        trackCount=lambda: 18, getTrackName=lambda i: "主" if i == 0 else "插入 " + str(i),
        getTrackPan=lambda i: -0.00001, getTrackVolume=lambda i: 0.7999999523162842,
        isTrackMuted=lambda i: False, isTrackSolo=lambda i: False,
    )
    controller.channels = SimpleNamespace(
        channelCount=lambda: 5, getChannelName=lambda i: "Kick", getChannelPan=lambda i: -0.00001,
        getChannelVolume=lambda i: 0.7999999523162842,
        isChannelMuted=lambda i: False, isChannelSolo=lambda i: False,
    )
    result = controller._dispatch(command, params)
    assert_lossless_numbers(result)


@pytest.mark.parametrize("encoder", ["shared", "controller"])
def test_wire_serialization_canonicalizes_nested_zero(controller, encoder):
    payload = {"data": {"pan": -0.0, "values": [-0.0, (-0.0, -0.04)], "name": "-0.0"}}
    encode = protocol.encode_message if encoder == "shared" else controller._encode_message
    wire = encode(protocol.DIR_RESPONSE, "12345678", payload)
    decoded = protocol.decode_message(wire)[2]
    assert_lossless_numbers(decoded)
    assert decoded["data"]["values"][1][1] == -0.04
    assert decoded["data"]["name"] == "-0.0", "Do not replace text that resembles a number"


@pytest.mark.parametrize("encoder", ["shared", "controller"])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_wire_rejects_nonfinite_data(controller, encoder, number):
    encode = protocol.encode_message if encoder == "shared" else controller._encode_message
    with pytest.raises(ValueError):
        encode(protocol.DIR_RESPONSE, "12345678", {"v": number})


def daemon_roundtrip(monkeypatch, data):
    class Bridge:
        calls = 0

        def call(self, command, params, timeout=None):
            self.calls += 1
            return data

    bridge = Bridge()
    monkeypatch.setattr(daemon, "_bridge", bridge)
    with daemon._Server(("127.0.0.1", 0), daemon._Handler) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            with socket.create_connection(server.server_address, timeout=2) as connection:
                connection.sendall(b'{"op":"call","cmd":"mixer_get_track","params":{"index":0}}\n')
                line = connection.makefile("rb").readline()
            return json.loads(line), bridge.calls
        finally:
            server.shutdown()
            thread.join()


def test_daemon_canonicalizes_old_controller_replies(monkeypatch):
    result, count = daemon_roundtrip(monkeypatch, {"vol_db": -0.0, "pan": -0.0, "trim": -0.04})
    assert result["ok"] is True
    assert result["data"]["trim"] == -0.04
    assert_lossless_numbers(result)
    assert count == 1


def test_daemon_reports_invalid_result_without_replaying_command(monkeypatch):
    result, count = daemon_roundtrip(monkeypatch, {"v": float("nan")})
    assert result["ok"] is False
    assert result["code"] == "invalid_result"
    assert "inspect" in result["error"].lower()
    assert count == 1
