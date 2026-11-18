"""Fault-injection safety gates; never opens FL or MIDI."""
import math

import pytest

from fl_studio_mcp import protocol
from fl_studio_mcp.music import calibration as cal
from fl_studio_mcp.music.value_parse import parse_value_string


class Bridge:
    def __init__(self, *, snapshot=.25, refuse=None, stale=0, read_failure=False):
        self.value, self.snapshot = .25, snapshot
        self.refuse, self.stale = refuse, stale
        self.read_failure = read_failure
        self.writes, self.reads, self.pending = [], 0, None

    def call(self, command, params):
        if command == protocol.CMD_PLUGIN_GET_PARAM:
            self.reads += 1
            if self.reads == 1:
                return {} if self.snapshot is None else {'v': self.snapshot, 's': '25 %'}
            if self.read_failure and len(self.writes) == 2:
                self.read_failure = False
                raise RuntimeError('injected GET failure')
            if self.pending:
                value, remaining = self.pending
                if remaining:
                    self.pending = value, remaining - 1
                else:
                    self.value, self.pending = value, None
            return {'v': self.value, 's': f'{self.value * 100} %'}
        assert command == protocol.CMD_PLUGIN_SET_PARAM
        value = params['value']
        self.writes.append(value)
        if value != self.refuse:
            if self.stale and self.pending is None:
                self.pending = value, self.stale
            elif not self.stale:
                self.value = value
        return {'ok': True, 'v': self.value}


@pytest.mark.parametrize('snapshot', [None, math.nan, math.inf, -1, 2, True])
def test_invalid_snapshot_refuses_before_writes(snapshot):
    bridge = Bridge(snapshot=snapshot)
    with pytest.raises(ValueError):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert bridge.writes == []


def test_refused_sweep_write_must_not_produce_curve():
    bridge = Bridge(refuse=.5)
    with pytest.raises(RuntimeError):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert bridge.value == .25


def test_restore_is_verified_and_failure_is_explicit():
    bridge = Bridge(refuse=.25)
    with pytest.raises(RuntimeError, match='restor'):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert bridge.value != .25


def test_stale_readback_is_settled_before_sampling():
    bridge = Bridge(stale=1)
    result = cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert result['table'] == [(0., 0.), (.5, 50.), (1., 100.)]
    assert bridge.value == .25


def test_mid_sweep_exception_still_restores():
    bridge = Bridge(read_failure=True)
    with pytest.raises(RuntimeError, match='injected'):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert bridge.value == .25


@pytest.mark.parametrize('table', [[(0, 1), (1, 1)], [(0, 1), (1, math.nan)],
                                  [(0, 1), (0, 2)], [(0, 2), (1, 1)]])
def test_noninvertible_curve_is_not_usable(table):
    assert cal.build_curve(table)['monotonic'] is False


@pytest.mark.parametrize('text,value,unit', [('50% [-9 dB]', 50, '%'),
    ('0.5 ms [2 kHz]', .5, 'ms'), ('1e3 Hz', 1000, 'Hz'),
    ('-6 dB [50%]', -6, 'dB'), ('1.5 kHz', 1500, 'Hz'),
    ('1 ms [1:4]', 1, 'ms'), ('2:1', 2, 'ratio')])
def test_primary_display_unit(text, value, unit):
    parsed = parse_value_string(text)
    assert (parsed['value'], parsed['unit']) == (value, unit)


def test_mixed_units_refused_after_original_restored():
    class Mixed(Bridge):
        def call(self, command, params):
            result = super().call(command, params)
            if command == protocol.CMD_PLUGIN_GET_PARAM and self.reads > 1:
                result['s'] = '20 Hz' if self.value == 0 else '10 ms'
            return result
    bridge = Mixed()
    with pytest.raises(ValueError, match='units'):
        cal.sweep_param(bridge, 0, 0, 0, steps=3)
    assert bridge.value == .25


def test_failed_restoration_never_writes_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cal, 'CACHE_DIR', tmp_path)
    bridge = Bridge(refuse=.25)
    with pytest.raises(RuntimeError, match='restor'):
        cal.calibrate_param(bridge, 0, 0, 0, steps=3)
    assert list(tmp_path.iterdir()) == []


def test_cache_hit_performs_no_writes(monkeypatch, tmp_path):
    monkeypatch.setattr(cal, 'CACHE_DIR', tmp_path)
    bridge = Bridge()
    first = cal.calibrate_param(bridge, 0, 0, 0, steps=3)
    assert bridge.value == .25 and not first['cached']
    bridge.writes.clear()
    second = cal.calibrate_param(bridge, 0, 0, 0, steps=3)
    assert second['cached'] and bridge.writes == []


@pytest.mark.parametrize('points', [[(0, 0), (1, math.nan)], [(0, 5), (1, 5)]])
def test_invalid_cached_curve_is_recalibrated(monkeypatch, tmp_path, points):
    monkeypatch.setattr(cal, 'CACHE_DIR', tmp_path)
    sig = cal.signature('', 0, None)
    cal.save_cache(sig, {f'{sig}:0:0': {'unit': '%', 'curve': {
        'points': points, 'monotonic': True}}})
    bridge = Bridge()
    result = cal.calibrate_param(bridge, 0, 0, 0, steps=3)
    assert not result['cached'] and bridge.value == .25
