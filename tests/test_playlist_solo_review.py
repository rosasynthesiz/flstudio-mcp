"""Independent solo-state preservation gate, using an exclusive-solo fake DAW."""
from copy import deepcopy

from fastmcp import Client
import pytest

from fl_studio_mcp import connection, safety
from fl_studio_mcp.server import build_server


@pytest.mark.asyncio
async def test_playlist_solo_undo_preserves_other_solo_state(monkeypatch, tmp_path):
    class Bridge:
        def __init__(self):
            self.tracks = {1:{'track':1,'solo':False,'muted':False},
                           2:{'track':2,'solo':True,'muted':False}}
        def call(self, command, params):
            if command == 'playlist_track_list':
                return {'total':2,'tracks':list(self.tracks.values())}
            track = params['track']
            if command == 'playlist_get_track':
                return dict(self.tracks[track])
            assert command == 'playlist_solo_track'
            if params['state']:
                for value in self.tracks.values():
                    value['solo'] = False
            self.tracks[track]['solo'] = params['state']
            return dict(self.tracks[track])
    bridge = Bridge()
    before = deepcopy(bridge.tracks)
    monkeypatch.setattr(connection, '_bridge', bridge)
    monkeypatch.setattr(safety, '_DIR', tmp_path)
    monkeypatch.setattr(safety, '_PATH', tmp_path/'log.jsonl')
    monkeypatch.setattr(safety, '_log', safety.ChangeLog())
    safety.set_dry_run(False)
    async with Client(build_server()) as client:
        result = await client.call_tool('fl_playlist_solo_track', {'track':1,'solo':True})
        if result.data['ok']:
            await client.call_tool('fl_rollback_last_change')
        else:
            assert result.data['supported'] is False
            assert result.data['affected_tracks'] == [2]
            assert safety.get_changelog().recent() == []
    assert bridge.tracks == before, 'Undo lost another track\'s pre-existing solo state'
