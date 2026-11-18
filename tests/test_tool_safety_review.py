"""PR12 registered-tool checks with no external DAW or hotkey actions."""
from fastmcp import Client
import pytest

from fl_studio_mcp import connection, safety
from fl_studio_mcp.server import build_server
from fl_studio_mcp.tools.loader import describe_load_limitation
from fl_studio_mcp.tools import vst


@pytest.mark.asyncio
@pytest.mark.parametrize('name,args', [
    ('fl_plugin_calibrate_param', {'track': 0, 'slot': 0, 'param': 0}),
    ('fl_plugin_set_param_value', {'track': 0, 'slot': 0, 'param': 0, 'target': 50}),
    ('fl_plugin_intent', {'track': 0, 'slot': 0, 'intent': 'brighter'}),
    ('fl_playlist_mute_track', {'track': 1}),
    ('fl_playlist_solo_track', {'track': 1}),
    ('fl_playlist_rename_track', {'track': 1, 'name': 'test'}),
    ('fl_playlist_set_track_color', {'track': 1, 'color': 'blue'}),
    ('fl_channel_set_step', {'channel': 0, 'index': 0}),
    ('fl_channel_set_steps', {'channel': 0, 'steps': [0, 4]}),
    ('fl_channel_clear_grid', {'channel': 0}),
    ('fl_pattern_select', {'pattern': 1}),
    ('fl_pattern_rename', {'pattern': 1, 'name': 'test'}),
])
async def test_new_mutations_preview_without_daw_calls(monkeypatch, name, args):
    class NoDaw:
        def call(self, *_):
            pytest.fail('Dry-run must not dispatch to the DAW')

    monkeypatch.setattr(connection, '_bridge', NoDaw())
    safety.set_dry_run(True)
    try:
        async with Client(build_server()) as client:
            result = await client.call_tool(name, args)
        assert result.data['dry_run'] is True
    finally:
        safety.set_dry_run(False)


@pytest.mark.parametrize('generator', [False, True])
def test_loader_never_claims_plugin_was_loaded(generator):
    result = describe_load_limitation('Test Plugin', generator)
    assert result['supported'] is False and result['ok'] is False


@pytest.mark.parametrize('scope,expected', [('playlist_track:3', ('playlist_get_track', {'track': 3})),
    ('grid_bit:2:7', ('channel_get_grid_bit', {'channel': 2, 'index': 7}))])
def test_added_snapshot_scope_addresses_exact_target(scope, expected):
    class Bridge:
        calls = []
        def call(self, command, params):
            self.calls.append((command, params))
            return {'value': 0}
    bridge = Bridge()
    bridge.calls = []
    assert safety.take_snapshot(bridge, scope) == {'value': 0}
    assert bridge.calls == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize('refuse', [False, True])
@pytest.mark.parametrize('name,args', [
    ('fl_plugin_set_param_value', {'param': 0, 'target': 80}),
    ('fl_plugin_intent', {'intent': 'brighter', 'amount': .5})])
async def test_unit_targeted_tools_verify_and_retain_original(monkeypatch, tmp_path, refuse, name, args):
    class Bridge:
        value = .2
        def call(self, command, params):
            if command == 'plugin_get_params':
                return {'plugin': 'Offline', 'total': 1, 'params': [
                    {'i': 0, 'name': 'Cutoff', 'v': self.value, 's': f'{100*self.value} Hz'}]}
            if command == 'plugin_get_param':
                return {'v': self.value, 'name': 'Cutoff', 's': f'{100*self.value} Hz'}
            assert command == 'plugin_set_param'
            if not refuse or params['value'] == .2:
                self.value = params['value']
            return {'v': params['value']}  # Deliberately optimistic setter echo.
    bridge = Bridge()
    monkeypatch.setattr(connection, '_bridge', bridge)
    monkeypatch.setattr(safety, '_DIR', tmp_path)
    monkeypatch.setattr(safety, '_PATH', tmp_path / 'log.jsonl')
    monkeypatch.setattr(safety, '_log', safety.ChangeLog())
    monkeypatch.setattr(safety.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(vst.cal, 'calibrate_param', lambda *a, **k: {
        'unit': 'Hz', 'curve': {'monotonic': True, 'points': [(0, 0), (1, 100)]}})
    safety.set_dry_run(False)
    async with Client(build_server()) as client:
        result = await client.call_tool(name, dict(track=0, slot=0, **args))
    assert result.data['verified'] is not refuse
    assert safety.get_changelog().recent()[0]['restore']['params']['value'] == .2
    safety.rollback_last_change(bridge)
    assert bridge.value == .2
