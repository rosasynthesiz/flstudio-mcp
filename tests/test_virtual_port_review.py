"""Pure backend contract tests; no OS MIDI port is created."""
from types import SimpleNamespace

import pytest

from fl_studio_mcp import connection as conn


@pytest.mark.parametrize('platform,setting,expected', [
    ('darwin', None, False), ('linux', None, False), ('darwin', 'auto', False),
    ('darwin', '1', True), ('linux', 'true', True), ('win32', '1', False),
    ('darwin', 'off', False), ('freebsd', '1', False),
    ('darwin', ' YES ', True), ('linux', 'on', True)])
def test_virtual_ports_are_explicitly_opt_in(monkeypatch, platform, setting, expected):
    monkeypatch.setattr(conn, 'sys', SimpleNamespace(platform=platform))
    if setting is None:
        monkeypatch.delenv('FLSTUDIO_MCP_VIRTUAL_PORTS', raising=False)
    else:
        monkeypatch.setenv('FLSTUDIO_MCP_VIRTUAL_PORTS', setting)
    assert conn._virtual_ports_enabled() is expected


class Port:
    closed = False

    def close(self):
        self.closed = True


class Backend:
    def __init__(self, partial=False, fail_input=False):
        self.partial, self.fail_input = partial, fail_input
        self.output, self.calls = Port(), []

    def get_output_names(self):
        return ['FLStudioMCP RX'] if self.partial else []

    def get_input_names(self):
        return []

    def open_output(self, name, **kwargs):
        self.calls.append(('output', name, kwargs))
        return self.output

    def open_input(self, name, **kwargs):
        self.calls.append(('input', name, kwargs))
        if self.fail_input:
            raise RuntimeError('input creation failed')
        return Port()


def backend(monkeypatch, **kwargs):
    fake = Backend(**kwargs)
    monkeypatch.setattr(conn, 'mido', fake)
    monkeypatch.setattr(conn, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setenv('FLSTUDIO_MCP_VIRTUAL_PORTS', '1')
    return fake


def test_partial_pair_does_not_create_duplicates(monkeypatch):
    fake = backend(monkeypatch, partial=True)
    bridge = conn.FLBridge()
    try:
        with pytest.raises(conn.FLPortMissing):
            bridge.open()
        assert fake.calls == []
    finally:
        bridge.close()


def test_failed_virtual_input_closes_created_output(monkeypatch):
    fake = backend(monkeypatch, fail_input=True)
    bridge = conn.FLBridge()
    with pytest.raises(conn.FLPortMissing):
        bridge.open()
    assert fake.output.closed
    assert bridge._out_port is None


def test_created_pair_is_cleaned_idempotently(monkeypatch):
    fake = backend(monkeypatch)
    bridge = conn.FLBridge()
    bridge.open()
    assert bridge._opened and bridge._virtual
    bridge.close()
    bridge.close()
    assert fake.output.closed and not bridge._opened and not bridge._virtual


def test_cleanup_attempts_both_ports_if_input_close_raises(monkeypatch):
    fake = backend(monkeypatch)
    bridge = conn.FLBridge()
    bridge.open()
    def fail_close():
        raise RuntimeError('input close failed')
    bridge._in_port.close = fail_close
    bridge.close()
    assert fake.output.closed
    assert bridge._in_port is None and bridge._out_port is None


def test_complete_named_pair_is_reused_without_virtual_creation(monkeypatch):
    fake = backend(monkeypatch)
    fake.get_output_names = lambda: ['FLStudioMCP RX']
    fake.get_input_names = lambda: ['FLStudioMCP TX']
    bridge = conn.FLBridge()
    bridge.open()
    try:
        assert not bridge._virtual
        assert all(not call[2].get('virtual') for call in fake.calls)
    finally:
        bridge.close()


def test_opposite_direction_virtual_pair_is_not_duplicated(monkeypatch):
    fake = backend(monkeypatch)
    fake.get_output_names = lambda: ['FLStudioMCP TX']
    fake.get_input_names = lambda: ['FLStudioMCP RX']
    bridge = conn.FLBridge()
    with pytest.raises(conn.FLPortMissing, match='opposite direction'):
        bridge.open()
    assert fake.calls == []


def test_failed_named_input_closes_output_and_allows_retry(monkeypatch):
    fake = backend(monkeypatch, fail_input=True)
    fake.get_output_names = lambda: ['FLStudioMCP RX']
    fake.get_input_names = lambda: ['FLStudioMCP TX']
    bridge = conn.FLBridge()
    with pytest.raises(RuntimeError, match='input creation failed'):
        bridge.open()
    assert fake.output.closed
    assert bridge._out_port is None and bridge._in_port is None
    assert not bridge._opened
    fake.fail_input = False
    fake.output = Port()
    try:
        bridge.open()
        assert bridge._opened and not bridge._virtual
    finally:
        bridge.close()


def test_open_twice_does_not_create_more_ports(monkeypatch):
    fake = backend(monkeypatch)
    bridge = conn.FLBridge()
    try:
        bridge.open()
        bridge.open()
        assert len(fake.calls) == 2
    finally:
        bridge.close()


@pytest.mark.parametrize('virtual', [False, True])
def test_output_open_failure_leaves_clean_state(monkeypatch, virtual):
    fake = backend(monkeypatch)
    if not virtual:
        fake.get_output_names = lambda: ['FLStudioMCP RX']
        fake.get_input_names = lambda: ['FLStudioMCP TX']
    def fail_output(*args, **kwargs):
        raise RuntimeError('output failed')
    fake.open_output = fail_output
    bridge = conn.FLBridge()
    with pytest.raises((conn.FLPortMissing, RuntimeError), match='output failed'):
        bridge.open()
    assert bridge._out_port is None and bridge._in_port is None
    assert not bridge._opened and not bridge._virtual


def test_close_discards_previous_session_heartbeat(monkeypatch):
    import time
    backend(monkeypatch)
    bridge = conn.FLBridge()
    bridge.open()
    bridge._last_heartbeat = time.monotonic()
    bridge._heartbeat_payload = {'old_session': True}
    assert bridge.is_alive()
    bridge.close()
    bridge.open()
    try:
        assert not bridge.is_alive()
        assert bridge._heartbeat_payload is None
    finally:
        bridge.close()
