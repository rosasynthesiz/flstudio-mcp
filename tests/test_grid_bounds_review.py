"""Reject invalid grid writes before any DAW access; no crash reproduction."""
from fastmcp import Client
import pytest

from fl_studio_mcp import connection
from fl_studio_mcp.server import build_server


@pytest.mark.asyncio
@pytest.mark.parametrize('tool,args', [
    ('fl_channel_set_step', {'channel':0,'index':256}),
    ('fl_channel_set_steps', {'channel':0,'steps':[-1],'length':16}),
    ('fl_channel_set_steps', {'channel':0,'steps':[16],'length':16})])
async def test_invalid_grid_write_never_dispatches(monkeypatch, tool, args):
    class Forbidden:
        def call(self, *_):
            pytest.fail('Invalid grid write reached DAW')
    monkeypatch.setattr(connection, '_bridge', Forbidden())
    async with Client(build_server()) as client:
        with pytest.raises(Exception):
            await client.call_tool(tool,args)


@pytest.mark.parametrize('handler', ['_h_channel_get_grid_bit', '_h_channel_set_grid_bit'])
@pytest.mark.parametrize('channel,index', [(-1,0), (5,0), (0,-1), (0,256)])
def test_controller_rejects_bounds_before_native_grid_call(controller, monkeypatch, handler, channel, index):
    monkeypatch.setattr(controller.channels, 'channelCount', lambda:5, raising=False)
    def forbidden(*_):
        pytest.fail('Invalid index reached native grid API')
    monkeypatch.setattr(controller.channels, 'getGridBit', forbidden, raising=False)
    monkeypatch.setattr(controller.channels, 'setGridBit', forbidden, raising=False)
    with pytest.raises(ValueError, match='bounds'):
        getattr(controller, handler)({'channel':channel,'index':index,'value':1})
