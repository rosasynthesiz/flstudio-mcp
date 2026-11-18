"""Calibration recovery fault injection; no DAW or MIDI endpoints."""
import json

import pytest

from fl_studio_mcp import safety
from fl_studio_mcp.music import calibration as cal


class GuardedPlugin:
    def __init__(self):
        self.token = 'original'
        self.values = {'original': .25, 'other': .8}
        self.writes = []
        self.switch = False
        self.disconnect = False
        self.checkpoint = None

    def call(self, command, params):
        if command == 'get_project_state':
            return {'project_token': self.token, 'project_loading': False}
        if params.get('_project_token') != self.token:
            raise RuntimeError('project changed')
        if self.disconnect:
            raise RuntimeError('disconnected')
        if command == 'plugin_get_param':
            return {'v': self.values[self.token], 's': f'{self.values[self.token] * 100} %'}
        assert command == 'plugin_set_param'
        if self.checkpoint:
            self.checkpoint()
        self.writes.append((self.token, params['value']))
        self.values[self.token] = params['value']
        if self.switch:
            self.switch = False
            self.token = 'other'
        return {'ok': True}


def test_recovery_persisted_before_dispatch_and_removed_after_restore(changelog):
    bridge = GuardedPlugin()
    def check():
        entries = [json.loads(line) for line in safety._PATH.read_text().splitlines()]
        assert entries[-1]['project_token'] == 'original'
        assert entries[-1]['restore']['params']['value'] == .25
    bridge.checkpoint = check
    result = cal.sweep_param(bridge, 0, -1, 0, steps=3)
    assert len(result['table']) == 3 and bridge.values['original'] == .25
    assert changelog.recent() == []


def test_project_switch_never_restores_into_new_project_and_recovery_survives_reload(
        changelog, monkeypatch):
    bridge = GuardedPlugin()
    bridge.switch = True
    with pytest.raises(RuntimeError, match='recovery retained'):
        cal.sweep_param(bridge, 0, -1, 0, steps=3)
    assert bridge.values['other'] == .8
    assert bridge.writes == [('original', 0)]
    reloaded = safety.ChangeLog()
    monkeypatch.setattr(safety, '_log', reloaded)
    assert not safety.rollback_last_change(bridge)['ok']
    assert len(reloaded.recent()) == 1
    bridge.token = 'original'
    assert safety.rollback_last_change(bridge)['ok']
    assert bridge.values['original'] == .25 and not reloaded.recent()


def test_failure_to_persist_prevents_sweep(changelog, monkeypatch):
    bridge = GuardedPlugin()
    def fail(entries):
        raise OSError('disk full')
    monkeypatch.setattr(changelog, '_commit', fail)
    with pytest.raises(OSError, match='disk full'):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert bridge.writes == []


def test_disconnect_retains_original_for_retry(changelog):
    bridge = GuardedPlugin()
    bridge.checkpoint = lambda: setattr(bridge, 'disconnect', True)
    with pytest.raises(RuntimeError, match='recovery retained'):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert changelog.recent()[0]['before']['v'] == .25
    bridge.checkpoint = None
    bridge.disconnect = False
    assert safety.rollback_last_change(bridge)['ok']
    assert bridge.values['original'] == .25


def test_old_controller_refused_without_writes(changelog):
    class Old(GuardedPlugin):
        def call(self, command, params):
            if command == 'get_project_state':
                return {}
            return super().call(command, params)
    bridge = Old()
    with pytest.raises(RuntimeError, match='identity unavailable'):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert not bridge.writes and not changelog.recent()


def test_pending_recovery_refuses_another_sweep(changelog):
    bridge = GuardedPlugin()
    # An unfinished change in THIS project and session blocks a new sweep...
    changelog.append({'incomplete': True, 'tool': 'prior-write', 'project_token': 'original'})
    with pytest.raises(RuntimeError, match='fl_rollback_last_change'):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert not bridge.writes and len(changelog.recent()) == 1


def test_stale_recovery_from_another_session_does_not_block(changelog):
    # ...but one left behind by another project or FL session never can.
    bridge = GuardedPlugin()
    changelog.append({'incomplete': True, 'tool': 'prior-write', 'project_token': 'gone'})
    cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert bridge.writes and len(changelog.recent()) == 1


def test_guard_survives_gap_between_calibration_and_final_write(changelog):
    bridge = GuardedPlugin()
    guarded = safety.guard_project(bridge)
    cal.sweep_param(guarded, 0, 0, 0, steps=3)
    bridge.token = 'other'
    with pytest.raises(RuntimeError, match='project changed'):
        safety.safe_write(guarded, tool='final', scope='plugin_param:0:0:0',
                          command='plugin_set_param', params={'value': .9},
                          build_restore=lambda before: {})
    assert bridge.values['other'] == .8


def test_successful_sweep_preserves_prior_undo(changelog):
    prior = {'tool': 'earlier', 'incomplete': False}
    changelog.append(prior)
    cal.sweep_param(GuardedPlugin(), 0, 0, 0, steps=3)
    assert changelog.recent() == [prior]


def test_interruption_still_restores_original(changelog):
    bridge = GuardedPlugin()
    def interrupt(guarded):
        guarded.call('plugin_set_param', {'track': 0, 'slot': 0, 'param': 0, 'value': .9})
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        safety.temporary_plugin_write(bridge, {'track': 0, 'slot': 0, 'param': 0}, interrupt)
    assert bridge.values['original'] == .25 and not changelog.recent()
