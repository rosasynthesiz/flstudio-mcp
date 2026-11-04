"""Independent project-boundary and recovery fault tests; never touches FL/MIDI."""
import json

import pytest

from fl_studio_mcp import safety
from fl_studio_mcp.connection import TCPBridge, local_tcp_host
from fl_studio_mcp import daemon


class Bridge:
    def __init__(self):
        self.token, self.value, self.pattern = 'project-a', .2, 1
        self.fail, self.ignore, self.switch_on_write = False, False, False
        self.writes = []

    def call(self, command, params):
        if command == 'get_project_state':
            return {'project_token': self.token, 'project_loading': False}
        if params.get('_project_token') != self.token:
            raise RuntimeError('project changed')
        if params.get('_expected_pattern', self.pattern) != self.pattern:
            raise RuntimeError('pattern changed')
        if command == 'plugin_get_param':
            return {'v': self.value}
        assert command == 'plugin_set_param'
        if self.switch_on_write:
            self.token = 'project-b'
            raise RuntimeError('project changed before dispatch')
        self.writes.append(params['value'])
        if self.fail:
            raise RuntimeError('connection lost')
        if not self.ignore:
            self.value = params['value']
        return {'ok': True, 'v': params['value']}


def change(bridge):
    return safety.safe_write(bridge, tool='test', scope='plugin_param:0:0:0',
        command='plugin_set_param', params={'value': .8},
        build_restore=lambda b: {'command': 'plugin_set_param', 'params': {'value': b['v']}})


@pytest.fixture
def bridge(changelog):
    safety.set_dry_run(False)
    return Bridge()


@pytest.mark.parametrize('token', ['project-b', 'controller-reloaded'])
def test_project_change_refuses_undo_without_write(bridge, changelog, token):
    change(bridge)
    bridge.token = token
    result = safety.rollback_last_change(bridge)
    assert result['ok'] is False and result['undo_retained']
    assert bridge.writes == [.8] and len(changelog.recent()) == 1


@pytest.mark.parametrize('failure', ['fail', 'ignore'])
def test_failed_or_optimistic_restore_is_retained_and_retryable(bridge, changelog, failure):
    change(bridge)
    setattr(bridge, failure, True)
    assert safety.rollback_last_change(bridge)['ok'] is False
    assert len(changelog.recent()) == 1
    setattr(bridge, failure, False)
    assert safety.rollback_last_change(bridge)['ok'] is True
    assert bridge.value == .2 and changelog.recent() == []


def test_write_intent_is_durable_before_command(bridge, changelog, monkeypatch):
    original = bridge.call
    def call(command, params):
        if command == 'plugin_set_param':
            disk = [json.loads(x) for x in safety._PATH.read_text().splitlines()]
            assert disk[-1]['restore']['params']['value'] == .2
        return original(command, params)
    monkeypatch.setattr(bridge, 'call', call)
    change(bridge)


def test_persist_failure_refuses_before_write(bridge, changelog, monkeypatch):
    def fail(*_):
        raise OSError('disk full')
    monkeypatch.setattr(changelog, '_commit', fail)
    with pytest.raises(OSError):
        change(bridge)
    assert bridge.writes == []


def test_dispatch_time_project_change_retains_original(bridge, changelog):
    bridge.switch_on_write = True
    with pytest.raises(RuntimeError):
        change(bridge)
    assert bridge.value == .2 and changelog.recent()[0]['project_token'] == 'project-a'


def test_legacy_history_never_replayed(bridge, changelog):
    changelog.append({'tool': 'legacy', 'restore': {'command': 'plugin_set_param', 'params': {'value': 0}}})
    assert safety.rollback_last_change(bridge)['ok'] is False
    assert bridge.writes == [] and changelog.recent()


def test_old_controller_refuses_write(bridge, monkeypatch):
    monkeypatch.setattr(bridge, 'call', lambda *_: {})
    with pytest.raises(RuntimeError, match='identity unavailable'):
        change(bridge)


def test_controller_rejects_old_token_and_loading(controller):
    token = controller._project_token()
    controller._HANDLERS['sentinel'] = lambda p: pytest.fail('stale request reached mutation')
    controller.OnProjectLoad(0)
    assert controller._project_token() != token and controller._project_loading
    with pytest.raises(controller._ClientError):
        controller._dispatch('sentinel', {'_project_token': token})
    with pytest.raises(controller._ClientError):
        controller._dispatch('sentinel', {'_project_token': controller._project_token()})
    controller.OnProjectLoad(100)
    assert not controller._project_loading


def test_controller_refuses_wrong_pattern(controller, monkeypatch):
    monkeypatch.setattr(controller.patterns, 'patternNumber', lambda: 2, raising=False)
    with pytest.raises(controller._ClientError, match='pattern'):
        controller._dispatch('ping', {'_project_token': controller._project_token(), '_expected_pattern': 1})


@pytest.mark.parametrize('host', ['0.0.0.0', '192.168.1.2', '8.8.8.8', 'example.com', '::', '::1'])
def test_remote_daemon_address_refused(host):
    with pytest.raises(ValueError):
        TCPBridge(host=host)
    with pytest.raises(ValueError):
        local_tcp_host(host)


def test_daemon_host_validation_precedes_midi(monkeypatch):
    monkeypatch.setenv('FLSTUDIO_MCP_TCP_HOST', '0.0.0.0')
    monkeypatch.setattr(daemon, '_get_bridge', lambda: pytest.fail('opened MIDI'))
    with pytest.raises(ValueError):
        daemon.main()


def test_bad_request_has_no_bridge_access(monkeypatch):
    monkeypatch.setattr(daemon, '_get_bridge', lambda: pytest.fail('opened MIDI'))
    assert daemon._handle_request([])['ok'] is False

def test_other_process_log_changes_are_loaded_before_append(bridge, changelog):
    other = safety.ChangeLog()
    other.append({'tool': 'other-client', 'project_token': 'project-a'})
    change(bridge)
    assert [e['tool'] for e in changelog.recent()] == ['other-client', 'test']


def test_group_restore_failure_retains_full_recovery(bridge, changelog):
    writes = [dict(snap_scope='plugin_param:0:0:0', command='plugin_set_param',
                   params={'value': .8}, restore=lambda b: {
                       'command': 'plugin_set_param', 'params': {'value': b['v']}})]
    safety.safe_write_group(bridge, tool='group', scope='params', writes=writes)
    bridge.fail = True
    assert safety.rollback_last_change(bridge)['ok'] is False
    assert len(changelog.recent()[0]['restores']) == 1
    bridge.fail = False
    assert safety.rollback_last_change(bridge)['ok'] is True
    assert bridge.value == .2 and not changelog.recent()


def test_corrupt_log_refuses_new_mutation(bridge, changelog):
    safety._PATH.write_text('{truncated', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        change(bridge)
    assert not bridge.writes


def test_failed_project_load_stays_guarded(controller):
    controller.OnProjectLoad(101)
    assert controller._project_loading
    with pytest.raises(controller._ClientError):
        controller._dispatch('ping', {'_project_token': controller._project_token()})

def test_grouped_fields_on_same_scope_can_restore_and_retry(changelog):
    class MultiField:
        def __init__(self):
            self.state = {'mute': True, 'solo': True, 'name': 'original'}
            self.refuse_mute_restore = False
            self.writes = []

        def call(self, command, params):
            if command == 'get_project_state':
                return {'project_token': 'same-project', 'project_loading': False}
            if command == 'mixer_get_track':
                return dict(self.state)
            field = 'mute' if command == 'mixer_set_mute' else 'solo'
            self.writes.append((field, params['state']))
            if not (field == 'mute' and params['state'] and self.refuse_mute_restore):
                self.state[field] = params['state']
            return dict(self.state)

    bridge = MultiField()
    writes = [dict(snap_scope='mixer_track:1', command=f'mixer_set_{field}',
                   params={'track': 1, 'state': False},
                   restore=lambda before, f=field: {'command': f'mixer_set_{f}',
                       'params': {'track': 1, 'state': before[f]}}) for field in ('mute', 'solo')]
    safety.safe_write_group(bridge, tool='clear_mute_solo', scope='mixer', writes=writes)
    bridge.state['name'] = 'manual edit'
    bridge.refuse_mute_restore = True
    result = safety.rollback_last_change(bridge)
    assert result['ok'] is False and result['undo_retained']
    assert bridge.state == {'mute': False, 'solo': True, 'name': 'manual edit'}
    assert bridge.writes[-2:] == [('solo', True), ('mute', True)]
    assert len(changelog.recent()[0]['restores']) == 2
    bridge.refuse_mute_restore = False
    assert safety.rollback_last_change(bridge)['ok'] is True
    assert bridge.state == {'mute': True, 'solo': True, 'name': 'manual edit'}
    assert not changelog.recent()


def test_single_field_undo_preserves_unrelated_manual_edit(changelog):
    class Track:
        state = {'mute': False, 'name': 'original'}
        def call(self, command, params):
            if command == 'get_project_state':
                return {'project_token': 'track-project', 'project_loading': False}
            if command == 'mixer_set_mute':
                self.state['mute'] = params['state']
            return dict(self.state)
    bridge = Track()
    safety.safe_write(bridge, tool='mute', scope='mixer_track:1', command='mixer_set_mute',
        params={'track': 1, 'state': True}, build_restore=lambda before: {
            'command': 'mixer_set_mute', 'params': {'track': 1, 'state': before['mute']}})
    bridge.state['name'] = 'manual edit'
    assert safety.rollback_last_change(bridge)['ok'] is True
    assert bridge.state == {'mute': False, 'name': 'manual edit'}

def test_group_final_readback_catches_later_restore_side_effect(changelog):
    class Coupled:
        def __init__(self):
            self.state = {'mute': True, 'solo': True}
            self.coupled = False
        def call(self, command, params):
            if command == 'get_project_state':
                return {'project_token': 'coupled', 'project_loading': False}
            if command != 'mixer_get_track':
                field = 'mute' if command == 'mixer_set_mute' else 'solo'
                self.state[field] = params['state']
                if self.coupled and field == 'mute' and params['state']:
                    self.state['solo'] = False
            return dict(self.state)
    bridge = Coupled()
    writes = [dict(snap_scope='mixer_track:1', command=f'mixer_set_{field}',
                   params={'state': False}, restore=lambda b, f=field: {
                       'command': f'mixer_set_{f}', 'params': {'state': b[f]}})
              for field in ('mute', 'solo')]
    safety.safe_write_group(bridge, tool='coupled', scope='mixer', writes=writes)
    bridge.coupled = True
    result = safety.rollback_last_change(bridge)
    assert result['ok'] is False and 'Final restoration' in result['error']
    assert changelog.recent()
    bridge.coupled = False
    assert safety.rollback_last_change(bridge)['ok'] is True
    assert bridge.state == {'mute': True, 'solo': True} and not changelog.recent()
