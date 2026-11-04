"""Independent fault injection for PR 27; never contacts FL Studio."""
from fl_studio_mcp import safety
import pytest


@pytest.fixture
def isolated_log(monkeypatch, tmp_path):
    monkeypatch.setattr(safety, '_DIR', tmp_path)
    monkeypatch.setattr(safety, '_PATH', tmp_path / 'changelog.jsonl')
    log = safety.ChangeLog()
    monkeypatch.setattr(safety, '_log', log)
    safety.set_dry_run(False)
    return log


class FaultBridge:
    def __init__(self, failure):
        self.failure = failure
        self.values = {0: 0.1, 1: 0.2}
        self.writes = 0

    def call(self, command, params):
        if command == "get_project_state":
            return {"project_token": "fault-project", "project_loading": False}
        index = params["param"]
        if command == 'plugin_get_param':
            if self.failure == 'read' and self.writes:
                raise RuntimeError('readback unavailable')
            return {'v': self.values[index]}
        self.writes += 1
        if self.failure == 'second' and index == 1:
            raise RuntimeError('second write unavailable')
        self.values[index] = params['value']
        return {'v': params['value']}


def write(index):
    return dict(snap_scope=f'plugin_param:0:0:{index}', command='plugin_set_param',
                params={'track': 0, 'slot': 0, 'param': index, 'value': 0.8},
                restore=lambda b: {'command': 'plugin_set_param',
                                   'params': {'track': 0, 'slot': 0, 'param': index, 'value': b['v']}})


def test_failed_readback_must_not_claim_verified(isolated_log):
    w = write(0)
    result = safety.safe_write(FaultBridge('read'), tool='audit', scope=w['snap_scope'],
                              command=w['command'], params=w['params'], build_restore=w['restore'],
                              verify_value=('v', 0.8, 0.02), verify_delay=0)
    assert result['verified'] is False, 'A setter echo is not an independent successful readback'


def test_partial_batch_retains_recovery_record(isolated_log):
    bridge = FaultBridge('second')
    with pytest.raises(RuntimeError):
        safety.safe_write_group(bridge, tool='audit', scope='plugin_params:0:0',
                                writes=[write(0), write(1)])
    assert bridge.values[0] == 0.1 or isolated_log.recent(), 'Partial write was neither restored nor logged'
    bridge.failure = None
    safety.rollback_last_change(bridge)
    assert bridge.values == {0: 0.1, 1: 0.2}
    assert isolated_log.recent() == []


def test_single_retry_exception_retains_recovery_record(isolated_log):
    class RetryFault(FaultBridge):
        fail_retry = True

        def call(self, command, params):
            if command == "get_project_state":
                return super().call(command, params)
            if self.fail_retry and self.writes:
                if command == 'plugin_get_param':
                    return {'v': 0.1}  # stale read after the first write landed
                raise RuntimeError('retry unavailable')
            return super().call(command, params)

    bridge = RetryFault(None)
    w = write(0)
    with pytest.raises(RuntimeError):
        safety.safe_write(bridge, tool='audit', scope=w['snap_scope'], command=w['command'],
                          params=w['params'], build_restore=w['restore'],
                          verify_value=('v', 0.8, 0.02), verify_delay=0)
    assert isolated_log.recent(), 'A failed retry must not lose the first write recovery action'
    bridge.fail_retry = False
    safety.rollback_last_change(bridge)
    assert bridge.values[0] == 0.1
