"""E-1 unit tests: verified writes + batch as one rollback unit (no live FL).

The live scenario is scripts/test_e1_plugin_write.py. These drive the same
logic through FakeBridge: the fresh re-read, the retry budget, honest
verified:false, and safe_write_group's single changelog entry.
"""

from __future__ import annotations

from fl_studio_mcp import protocol, safety

SCOPE = "plugin_param:1:0:5"


def _write(param=5, value=0.6, track=1, slot=0):
    return {
        "snap_scope": f"plugin_param:{track}:{slot}:{param}",
        "command": protocol.CMD_PLUGIN_SET_PARAM,
        "params": {"track": track, "slot": slot, "param": param, "value": value},
        "restore": lambda b, _t=track, _s=slot, _i=param: {
            "command": protocol.CMD_PLUGIN_SET_PARAM,
            "params": {"track": _t, "slot": _s, "param": _i, "value": b["v"]},
        },
    }


def _safe_write(bridge, w, target, attempts=3):
    return safety.safe_write(
        bridge, tool="plugin_set_param", scope=w["snap_scope"],
        command=w["command"], params=w["params"], build_restore=w["restore"],
        verify_value=("v", target, 0.02), verify_attempts=attempts,
        verify_delay=0.0,
    )


def test_verified_write_lands_first_try(fake_bridge, changelog):
    fake_bridge.replies[protocol.CMD_PLUGIN_GET_PARAM] = [
        {"v": 0.2},            # before-snapshot
        {"v": 0.6},            # fresh re-read after the write
    ]
    fake_bridge.replies[protocol.CMD_PLUGIN_SET_PARAM] = {"ok": True}
    w = _write(value=0.6)
    out = _safe_write(fake_bridge, w, 0.6)
    assert out["verified"] is True
    assert out["attempts"] == 1
    assert len(fake_bridge.calls_to(protocol.CMD_PLUGIN_SET_PARAM)) == 1
    entries = changelog.recent()
    assert len(entries) == 1
    assert entries[0]["before"]["v"] == 0.2
    assert entries[0]["after"]["v"] == 0.6


def test_retry_budget_then_lands(fake_bridge, changelog):
    fake_bridge.replies[protocol.CMD_PLUGIN_GET_PARAM] = [
        {"v": 0.2},            # before-snapshot
        {"v": 0.0},            # miss: FL swallowed the first write
        {"v": 0.6},            # retry lands
    ]
    fake_bridge.replies[protocol.CMD_PLUGIN_SET_PARAM] = {"ok": True}
    w = _write(value=0.6)
    out = _safe_write(fake_bridge, w, 0.6, attempts=3)
    assert out["verified"] is True
    assert out["attempts"] == 2
    assert len(fake_bridge.calls_to(protocol.CMD_PLUGIN_SET_PARAM)) == 2
    assert len(changelog.recent()) == 1


def test_exhausted_budget_reports_honest_false(fake_bridge, changelog):
    fake_bridge.replies[protocol.CMD_PLUGIN_GET_PARAM] = {"v": 0.0}
    fake_bridge.replies[protocol.CMD_PLUGIN_SET_PARAM] = {"ok": True}
    w = _write(value=0.6)
    out = _safe_write(fake_bridge, w, 0.6, attempts=2)
    assert out["verified"] is False
    assert out["attempts"] == 3          # initial write + 2 retries
    assert out["after"]["v"] == 0.0      # true state, not the request
    assert len(fake_bridge.calls_to(protocol.CMD_PLUGIN_SET_PARAM)) == 3
    assert len(changelog.recent()) == 1


def test_batch_is_one_rollback_unit_with_per_write_verify(fake_bridge, changelog):
    fake_bridge.replies[protocol.CMD_PLUGIN_GET_PARAM] = [
        {"v": 0.1},            # snapshot of param 5
        {"v": 0.2},            # snapshot of param 7
        {"v": 0.6},            # re-read param 5 after write
        {"v": 0.55},           # re-read param 7 after write
    ]
    fake_bridge.replies[protocol.CMD_PLUGIN_SET_PARAM] = {"ok": True}
    w1, w2 = _write(param=5, value=0.6), _write(param=7, value=0.55)
    out = safety.safe_write_group(
        fake_bridge, tool="plugin_set_params", scope="plugin_params:1:0",
        writes=[w1, w2], delay=0.0,
        verify_values=[("v", 0.6, 0.02), ("v", 0.55, 0.02)],
        verify_attempts=3, verify_delay=0.0,
    )
    assert out["verified"] == [True, True]
    assert out["attempts"] == [1, 1]
    assert len(fake_bridge.calls_to(protocol.CMD_PLUGIN_SET_PARAM)) == 2

    entries = changelog.recent()
    assert len(entries) == 1
    assert entries[0]["group"] is True
    assert len(entries[0]["restores"]) == 2

    safety.rollback_last_change(fake_bridge)
    restored = fake_bridge.calls_to(protocol.CMD_PLUGIN_SET_PARAM)[-2:]
    assert [p["param"] for p in restored] == [5, 7]
    assert [p["value"] for p in restored] == [0.1, 0.2]
    assert changelog.recent() == []
