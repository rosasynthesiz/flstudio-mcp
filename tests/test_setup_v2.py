"""v2 setup: one version, bundled controller, zero-click ports, doctor codes.

No FL Studio and no OS MIDI port is touched: MIDI is a fake backend and the FL
user-data folder is a temp folder through FL_SETTINGS.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from fl_studio_mcp import connection as conn
from fl_studio_mcp import paths, protocol, setup_cli

ROOT = Path(__file__).resolve().parents[1]


# -- one version, shipped controller ----------------------------------------

def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def test_controller_version_matches_package():
    assert setup_cli.controller_version(paths.bundled_controller()) == _pyproject_version()


def test_controller_declares_supported_devices():
    head = paths.bundled_controller().read_text(encoding="utf-8").splitlines()[:6]
    line = next(x for x in head if x.startswith("# supportedDevices="))
    names = line.split("=", 1)[1].split(",")
    assert names[0] == protocol.SHARED_PORT_NAME      # zero-click pairing on macOS
    assert protocol.DEFAULT_PORT_TO_FL in names       # auto-link for loopMIDI / IAC


def test_wheel_ships_the_controller():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "fl_studio_mcp/_controller/device_FLStudioMCP.py" in text


# -- setup: install the controller ------------------------------------------

@pytest.fixture
def fl_home(tmp_path, monkeypatch):
    settings = tmp_path / "FL Studio" / "Settings"
    (settings / "Hardware").mkdir(parents=True)
    monkeypatch.setenv("FL_SETTINGS", str(settings))
    return settings


def test_install_then_rerun_is_a_no_op(fl_home):
    first = setup_cli.install_controller()
    assert first["ok"] and first["action"] == "installed"
    target = Path(first["path"])
    assert target.read_bytes() == paths.bundled_controller().read_bytes()
    assert setup_cli.install_controller()["action"] == "already up to date"
    assert [p.name for p in target.parent.iterdir()] == ["device_FLStudioMCP.py"]


def test_install_keeps_a_different_old_copy(fl_home):
    target = paths.installed_controller()
    target.parent.mkdir(parents=True)
    target.write_text("# my edited controller\n", encoding="utf-8")
    result = setup_cli.install_controller()
    assert result["action"] == "updated"
    assert Path(result["backup"]).read_text(encoding="utf-8") == "# my edited controller\n"
    assert target.read_bytes() == paths.bundled_controller().read_bytes()


def test_install_refuses_without_fl_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("FL_SETTINGS", str(tmp_path / "nope"))
    result = setup_cli.install_controller()
    assert not result["ok"] and result["status"] == "USER_DATA_MISSING"
    assert not (tmp_path / "nope").exists()


# -- ports: one shared name, created by the server ---------------------------

class _Port:
    def close(self):
        pass


class _Backend:
    def __init__(self, outs=(), ins=()):
        self.outs, self.ins, self.calls = list(outs), list(ins), []

    def get_output_names(self):
        return self.outs

    def get_input_names(self):
        return self.ins

    def open_output(self, name, **kw):
        self.calls.append(("output", name, kw.get("virtual", False)))
        return _Port()

    def open_input(self, name, **kw):
        self.calls.append(("input", name, kw.get("virtual", False)))
        return _Port()

    @staticmethod
    def Message(kind, data=None):
        return SimpleNamespace(type=kind, data=data)


def _mac(monkeypatch, backend):
    monkeypatch.setattr(conn, "mido", backend)
    monkeypatch.setattr(conn, "sys", SimpleNamespace(platform="darwin"))
    for var in ("FLSTUDIO_MCP_VIRTUAL_PORTS", "FLSTUDIO_MCP_PORT_TO_FL",
                "FLSTUDIO_MCP_PORT_FROM_FL"):
        monkeypatch.delenv(var, raising=False)


def test_default_creates_one_shared_name(monkeypatch):
    fake = _Backend()
    _mac(monkeypatch, fake)
    bridge = conn.FLBridge()
    bridge.open()
    try:
        assert fake.calls == [("output", "FLStudioMCP", True), ("input", "FLStudioMCP", True)]
        assert bridge.port_to_fl == bridge.port_from_fl == "FLStudioMCP"
    finally:
        bridge.close()


def test_existing_pair_wins_over_virtual(monkeypatch):
    fake = _Backend(outs=["IAC Driver FLStudioMCP RX"], ins=["IAC Driver FLStudioMCP TX"])
    _mac(monkeypatch, fake)
    bridge = conn.FLBridge()
    bridge.open()
    try:
        assert all(not virtual for _, _, virtual in fake.calls)
        assert bridge.port_to_fl == "IAC Driver FLStudioMCP RX"
    finally:
        bridge.close()


def test_env_names_are_used_as_given(monkeypatch):
    fake = _Backend()
    _mac(monkeypatch, fake)
    monkeypatch.setenv("FLSTUDIO_MCP_PORT_TO_FL", "Mine In")
    monkeypatch.setenv("FLSTUDIO_MCP_PORT_FROM_FL", "Mine Out")
    bridge = conn.FLBridge()
    bridge.open()
    try:
        assert [c[1] for c in fake.calls] == ["Mine In", "Mine Out"]
    finally:
        bridge.close()


def test_second_owner_is_refused(monkeypatch):
    fake = _Backend(outs=["FLStudioMCP"], ins=["FLStudioMCP"])   # FL's view of an owner
    _mac(monkeypatch, fake)
    # The owner's ports show up to us mirrored; either side existing is enough.
    with pytest.raises(conn.FLBridgeBusy):
        conn.FLBridge().open()
    assert fake.calls == []


def test_windows_never_creates_ports(monkeypatch):
    fake = _Backend()
    monkeypatch.setattr(conn, "mido", fake)
    monkeypatch.setattr(conn, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.delenv("FLSTUDIO_MCP_VIRTUAL_PORTS", raising=False)
    with pytest.raises(conn.FLPortMissing, match="PORTS_MISSING"):
        conn.FLBridge().open()
    assert fake.calls == []


# -- transport: no daemon to start by hand -----------------------------------

@pytest.fixture
def clean_bridge(monkeypatch):
    monkeypatch.setattr(conn, "_bridge", None)
    monkeypatch.delenv("FLSTUDIO_MCP_TRANSPORT", raising=False)
    yield
    conn._bridge = None


def test_auto_joins_a_running_bridge(monkeypatch, clean_bridge):
    monkeypatch.setattr(conn, "_daemon_listening", lambda *a, **k: True)
    bridge = conn.get_bridge()
    assert isinstance(bridge, conn.TCPBridge) and bridge.auto


def test_auto_becomes_owner_and_shares(monkeypatch, clean_bridge):
    from fl_studio_mcp import daemon
    fake = _Backend()
    _mac(monkeypatch, fake)
    shared = []
    monkeypatch.setattr(conn, "_daemon_listening", lambda *a, **k: False)
    monkeypatch.setattr(daemon, "serve_in_background", lambda b, h, p: shared.append(b))
    bridge = conn.get_bridge()
    try:
        assert isinstance(bridge, conn.FLBridge) and shared == [bridge]
    finally:
        bridge.close()


def test_joiner_takes_over_when_owner_is_gone(monkeypatch, clean_bridge):
    from fl_studio_mcp import daemon
    fake = _Backend()
    _mac(monkeypatch, fake)
    monkeypatch.setattr(daemon, "serve_in_background", lambda b, h, p: None)
    listening = [True]
    monkeypatch.setattr(conn, "_daemon_listening", lambda *a, **k: listening[0])
    joined = conn.get_bridge()
    assert isinstance(joined, conn.TCPBridge)
    listening[0] = False                           # the owner exits
    successor = conn._take_over(joined)
    try:
        assert isinstance(successor, conn.FLBridge) and conn._bridge is successor
    finally:
        successor.close()


def test_old_tcp_setting_works_without_a_daemon(monkeypatch, clean_bridge):
    """Version 1 configs (and listings) set TRANSPORT=tcp; no daemon may be running."""
    from fl_studio_mcp import daemon
    fake = _Backend()
    _mac(monkeypatch, fake)
    monkeypatch.setenv("FLSTUDIO_MCP_TRANSPORT", "tcp")
    monkeypatch.setattr(conn, "_daemon_listening", lambda *a, **k: False)
    monkeypatch.setattr(daemon, "serve_in_background", lambda b, h, p: None)
    bridge = conn.get_bridge()
    try:
        assert isinstance(bridge, conn.FLBridge)
    finally:
        bridge.close()


def test_old_tcp_setting_still_uses_a_running_daemon(monkeypatch, clean_bridge):
    monkeypatch.setenv("FLSTUDIO_MCP_TRANSPORT", "tcp")
    monkeypatch.setattr(conn, "_daemon_listening", lambda *a, **k: True)
    assert isinstance(conn.get_bridge(), conn.TCPBridge)


def test_direct_never_shares_or_joins(monkeypatch, clean_bridge):
    from fl_studio_mcp import daemon
    fake = _Backend()
    _mac(monkeypatch, fake)
    shared = []
    monkeypatch.setenv("FLSTUDIO_MCP_TRANSPORT", "direct")
    monkeypatch.setattr(conn, "_daemon_listening", lambda *a, **k: True)
    monkeypatch.setattr(daemon, "serve_in_background", lambda b, h, p: shared.append(b))
    bridge = conn.get_bridge()
    try:
        assert isinstance(bridge, conn.FLBridge) and shared == []
    finally:
        bridge.close()


# -- doctor: a code and one next step ----------------------------------------

class _FakeLink:
    def __init__(self, alive=True, pong=None):
        self._alive, self._pong = alive, pong

    def is_alive(self):
        return self._alive

    def heartbeat_age(self):
        return 0.1 if self._alive else None

    def call(self, command, params=None, timeout=None):
        return self._pong


def _doctor(monkeypatch, link, running=True):
    monkeypatch.setattr(conn, "get_bridge", lambda: link)
    monkeypatch.setattr(setup_cli, "fl_is_running", lambda: running)
    monkeypatch.setattr(setup_cli, "find_fl_app", lambda: "/Applications/FL Studio.app")
    return setup_cli.diagnose(wait=0.0)


def _pong(version=None, proto=protocol.PROTOCOL_VERSION):
    return {"fl_version": "Fake FL", "protocol_version": proto,
            "controller_version": version or _pyproject_version()}


def test_ready_needs_ping_and_matching_controller(monkeypatch, fl_home):
    setup_cli.install_controller()
    report = _doctor(monkeypatch, _FakeLink(pong=_pong()))
    assert report["status"] == "READY" and report["fl_version"] == "Fake FL"


def test_old_controller_loaded_in_fl_is_a_mismatch(monkeypatch, fl_home):
    setup_cli.install_controller()
    report = _doctor(monkeypatch, _FakeLink(pong={"fl_version": "Fake FL",
                                                 "protocol_version": 2, "build": "probe-v16"}))
    assert report["status"] == "VERSION_MISMATCH"
    assert "fl-studio-mcp setup" in report["next"]


def test_missing_controller_explains_silence(monkeypatch, fl_home):
    report = _doctor(monkeypatch, _FakeLink(alive=False))
    assert report["status"] == "CONTROLLER_MISSING"


def test_fl_closed(monkeypatch, fl_home):
    setup_cli.install_controller()
    report = _doctor(monkeypatch, _FakeLink(alive=False), running=False)
    assert report["status"] == "FL_CLOSED"


def test_fl_open_but_silent(monkeypatch, fl_home):
    setup_cli.install_controller()
    report = _doctor(monkeypatch, _FakeLink(alive=False), running=True)
    assert report["status"] == "NO_HEARTBEAT" and "Restart FL Studio" in report["next"]


def test_working_link_is_not_vetoed_by_file_checks(monkeypatch, fl_home):
    report = _doctor(monkeypatch, _FakeLink(pong=_pong()))      # nothing installed on disk
    assert report["status"] == "READY"


def test_first_ping_may_be_lost_right_after_ports_appear(monkeypatch, fl_home):
    setup_cli.install_controller()

    class Flaky(_FakeLink):
        tries = 0

        def call(self, command, params=None, timeout=None):
            Flaky.tries += 1
            if Flaky.tries < 3:
                raise conn.FLTimeout("lost")
            return _pong()

    assert _doctor(monkeypatch, Flaky())["status"] == "READY"
    assert Flaky.tries == 3


def test_fl_busy_reports_ping_timeout(monkeypatch, fl_home):
    setup_cli.install_controller()

    class Busy(_FakeLink):
        def call(self, command, params=None, timeout=None):
            raise conn.FLTimeout("modal dialog")

    assert _doctor(monkeypatch, Busy())["status"] == "PING_TIMEOUT"


def test_every_status_has_a_next_step():
    assert all(text.strip() for text in setup_cli.STATUS_HELP.values())


# -- connect -----------------------------------------------------------------

def test_client_snippets_are_valid(monkeypatch):
    monkeypatch.setattr(setup_cli, "launch_command", lambda: ("uvx", ["fl-studio-mcp"]))
    snippets = setup_cli.client_snippets()
    entry = json.loads(snippets["claude-desktop"])["mcpServers"]["fl-studio"]
    assert entry == {"command": "uvx", "args": ["fl-studio-mcp"]}
    assert snippets["claude-code"] == "claude mcp add fl-studio -- uvx fl-studio-mcp"
    assert "FLSTUDIO_MCP_TRANSPORT" not in "".join(snippets.values())   # no env needed in v2


def _fake_env(monkeypatch, tmp_path, *dirs):
    bindir = tmp_path.joinpath(*dirs)
    bindir.mkdir(parents=True)
    name = "fl-studio-mcp.exe" if setup_cli.sys.platform == "win32" else "fl-studio-mcp"
    (bindir / name).write_text("")
    monkeypatch.setattr(setup_cli.sys, "executable", str(bindir / "python"))
    return bindir / name


def test_local_install_prints_its_own_path(monkeypatch, tmp_path):
    exe = _fake_env(monkeypatch, tmp_path, "my repo", ".venv", "bin")
    assert setup_cli.launch_command() == (str(exe), [])
    assert '"%s"' % exe in setup_cli.client_snippets()["claude-code"]   # path with a space


def test_uvx_dev_build_launches_from_git(monkeypatch, tmp_path):
    _fake_env(monkeypatch, tmp_path, ".cache", "uv", "archive-v0", "abc", "bin")
    monkeypatch.setattr(setup_cli, "__version__", "2.0.0.dev0")
    assert setup_cli.launch_command() == ("uvx", ["--from", setup_cli.GIT_SOURCE, "fl-studio-mcp"])


def test_uvx_release_launches_from_pypi(monkeypatch, tmp_path):
    _fake_env(monkeypatch, tmp_path, ".cache", "uv", "archive-v0", "abc", "bin")
    monkeypatch.setattr(setup_cli, "__version__", "2.0.0")
    assert setup_cli.launch_command() == ("uvx", ["fl-studio-mcp"])


def test_connect_rejects_unknown_client(capsys):
    assert setup_cli.run(["connect", "nope"]) == 2
    assert setup_cli.run(["connect", "codex"]) == 0
    assert "mcp_servers.fl-studio" in capsys.readouterr().out


# -- first command after the ports appear ------------------------------------

class _Wire:
    """A fake MIDI output that answers through the bridge's own callback."""

    def __init__(self, bridge, drop_first=0, error=None):
        self.bridge, self.drop, self.error, self.sent = bridge, drop_first, error, []

    def send(self, msg):
        _, request_id, payload = protocol.decode_message(msg.data)
        self.sent.append(payload["cmd"] if "cmd" in payload else payload.get("command"))
        if self.drop > 0:
            self.drop -= 1
            return
        body = ({"ok": False, "error": self.error} if self.error and self.sent[-1] != "ping"
                else {"ok": True, "data": {"pong": True}})
        reply = protocol.encode_message(protocol.DIR_RESPONSE, request_id, body)
        self.bridge._on_midi(SimpleNamespace(type="sysex", data=reply))

    def close(self):
        pass


def _wired(monkeypatch, **kw):
    fake = _Backend()
    _mac(monkeypatch, fake)
    bridge = conn.FLBridge()
    bridge.open()
    bridge._out_port = _Wire(bridge, **kw)
    bridge._last_heartbeat = conn.time.monotonic()
    return bridge


def test_first_command_waits_for_three_steady_pings(monkeypatch):
    bridge = _wired(monkeypatch)
    monkeypatch.setattr(conn.time, "sleep", lambda s: None)
    try:
        assert bridge.call("mixer_set_name", {"track": 1, "name": "x"}) == {"pong": True}
        assert bridge._out_port.sent == ["ping", "ping", "ping", "mixer_set_name"]
        bridge.call("get_tempo")
        assert bridge._out_port.sent.count("ping") == 3    # handshake happens once
    finally:
        bridge.close()


def test_one_early_answer_then_silence_is_not_trusted(monkeypatch):
    """FL answers one ping, drops the next two while attaching, then is steady."""
    bridge = _wired(monkeypatch)
    monkeypatch.setattr(conn.time, "sleep", lambda s: None)
    wire = bridge._out_port
    plan = iter([True, False, False, True, True, True, True, True])
    real_send = wire.send

    def send(msg):
        if next(plan, True):
            return real_send(msg)
        wire.sent.append("ping(lost)")

    wire.send = send
    monkeypatch.setattr(bridge, "_send", (lambda orig: lambda c, p, t: orig(c, p, 0.01))(bridge._send))
    try:
        bridge.call("mixer_set_name", {"track": 1, "name": "x"})
        sent = wire.sent
        assert sent.count("mixer_set_name") == 1 and sent[-1] == "mixer_set_name"
        assert sent[:6] == ["ping", "ping(lost)", "ping(lost)", "ping", "ping", "ping"]
    finally:
        bridge.close()


def test_modal_dialog_refusal_says_what_to_do(monkeypatch):
    bridge = _wired(monkeypatch, error="RuntimeError: Operation unsafe at current time")
    try:
        with pytest.raises(conn.FLCommandFailed, match="FL_BUSY") as info:
            bridge.call("set_tempo", {"bpm": 96})
        assert info.value.code == "fl_busy"
    finally:
        bridge.close()
