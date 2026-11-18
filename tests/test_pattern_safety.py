"""Pattern tools through real MIDI encoding/controller dispatch, with fake FL APIs."""

import json
from types import SimpleNamespace

import pytest
from fastmcp import Client

from fl_studio_mcp import connection, protocol, safety
from fl_studio_mcp.server import build_server


@pytest.fixture
def rig(controller, monkeypatch, changelog):
    class Project:
        names = {i: f"Pattern {i} " + "அ" * 30 for i in range(1, 61)}
        current = 1
        failure = None
        calls = []
        writes = []
        responses = []

        def jump(self, i):
            self.writes.append(("select", i))
            if self.failure != "select":
                self.current = i

        def rename(self, i, name):
            self.writes.append(("rename", i, name))
            if self.failure == "rename":
                raise RuntimeError("injected rename failure")
            self.names[i] = name

        def call(self, command, params=None):
            self.calls.append((command, params))
            request = protocol.encode_message(
                protocol.DIR_REQUEST, "12345678", protocol.make_request(command, params)
            )
            controller.OnSysEx(SimpleNamespace(sysex=b"\xf0" + request + b"\xf7"))
            wire = self.responses[-1]
            assert len(wire) < 1000, "Response exceeds the conservative MIDI limit"
            reply = protocol.decode_message(wire[1:-1])[2]
            if not reply["ok"]:
                raise connection.FLCommandFailed(reply["error"], code=reply["code"])
            return reply["data"]

    p = Project()
    monkeypatch.setattr(controller, "_send_sysex_fn", p.responses.append)
    for key, fn in dict(
        patternCount=lambda: len(p.names),
        patternNumber=lambda: p.current,
        getPatternName=lambda i: p.names[i],
        jumpToPattern=p.jump,
        setPatternName=p.rename,
        getPatternLength=lambda i: 16,
        isPatternSelected=lambda i: i == p.current,
    ).items():
        monkeypatch.setattr(controller.patterns, key, fn, raising=False)
    monkeypatch.setattr(controller.general, "getRecPPQ", lambda: 96, raising=False)
    monkeypatch.setattr(controller.general, "getRecPPB", lambda: 384, raising=False)
    # Writes are project-bound (v2): the controller reports a project token.
    monkeypatch.setattr(controller.mixer, "getCurrentTempo", lambda: 140000, raising=False)
    monkeypatch.setattr(controller.mixer, "trackCount", lambda: 1, raising=False)
    monkeypatch.setattr(controller.channels, "channelCount", lambda: 1, raising=False)
    monkeypatch.setattr(connection, "_bridge", p)
    safety.set_dry_run(False)
    return p, controller, changelog


@pytest.mark.asyncio
async def test_success_and_two_undos(rig):
    p, c, log = rig
    old = p.names[2]
    async with Client(build_server()) as client:
        r = (await client.call_tool("fl_pattern_rename", {"index": 2, "name": "Renamed"})).data
        assert r["ok"] and r["before"]["name"] == old and r["after"]["name"] == "Renamed"
        r = (await client.call_tool("fl_pattern_select", {"index": 2})).data
        assert r["ok"] and r["prev_index"] == 1 and r["resolved_index"] == 2
        assert len(log.recent()) == 2
        await client.call_tool("fl_rollback_last_change", {})
        assert p.current == 1 and p.names[2] == "Renamed"
        await client.call_tool("fl_rollback_last_change", {})
        assert p.names[2] == old and not log.recent()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,limit", [(0, None), (17, 7), (59, 5), (100, 4), (17, None), (100, None)]
)
async def test_pagination(rig, start, limit):
    p, c, log = rig
    async with Client(build_server()) as client:
        args = {"start": start}
        if limit is not None:
            args["limit"] = limit
        r = (await client.call_tool("fl_pattern_list", args)).data
        expected = list(range(1, 61))[start:]
        if limit is not None:
            expected = expected[:limit]
        assert [x["pattern"] for x in r["patterns"]] == expected
        assert r["total"] == 60
        assert all(x.get("trunc") for x in r["patterns"])


@pytest.mark.parametrize("index", [0, -3, 61, 9999])
@pytest.mark.parametrize("cmd", ["pattern_select", "pattern_rename", "pattern_get_length"])
def test_invalid_controller_indices(rig, index, cmd):
    p, c, log = rig
    before = dict(p.names)
    assert p.call(cmd, {"index": index, "name": "bad"})["ok"] is False
    assert p.current == 1 and p.names == before


@pytest.mark.asyncio
@pytest.mark.parametrize("cmd", ["fl_pattern_select", "fl_pattern_rename", "fl_pattern_get_length"])
@pytest.mark.parametrize("index", [0, -3, 9999])
async def test_invalid_tool_indices(rig, cmd, index):
    p, c, log = rig
    args = {"index": index}
    if cmd.endswith("rename"):
        args["name"] = "bad"
    async with Client(build_server()) as client:
        r = await client.call_tool(cmd, args, raise_on_error=False)
        assert r.is_error or r.data.get("ok") is False
    assert p.current == 1 and not log.recent()


@pytest.mark.parametrize("ppq,ppb,expected", [(96, 384, 4), (120, 360, 16 / 3), (0, 0, 4)])
def test_length_units(rig, monkeypatch, ppq, ppb, expected):
    p, c, log = rig
    monkeypatch.setattr(c.general, "getRecPPQ", lambda: ppq)
    monkeypatch.setattr(c.general, "getRecPPB", lambda: ppb)
    r = p.call("pattern_get_length", {"index": 1})
    assert r["length_beats"] == 16 and r["length_ticks"] == 16 * (ppq or 96)
    assert r["length_bars"] == round(expected, 3)
    assert not log.recent()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["rename", "select"])
async def test_failed_write_does_not_claim_success(rig, action):
    p, c, log = rig
    p.failure = action
    args = {"index": 2}
    if action == "rename":
        args["name"] = "never applied"
    async with Client(build_server()) as client:
        r = await client.call_tool("fl_pattern_" + action, args, raise_on_error=False)
        assert r.is_error or r.data.get("ok") is False, r.data


@pytest.mark.asyncio
async def test_failed_undo_retains_recovery(rig):
    p, c, log = rig
    async with Client(build_server()) as client:
        await client.call_tool("fl_pattern_rename", {"index": 2, "name": "changed"})
        p.failure = "rename"
        r = await client.call_tool("fl_rollback_last_change", {}, raise_on_error=False)
        assert (r.is_error or r.data.get("ok") is False) and log.recent(), (r.data, log.recent())


@pytest.mark.asyncio
async def test_transport_failure_keeps_undo_record(rig, monkeypatch):
    p, c, log = rig
    original = p.call

    def fail(command, params=None):
        result = original(command, params)
        if command == "pattern_rename":
            raise RuntimeError("reply lost after write")
        return result

    monkeypatch.setattr(p, "call", fail)
    async with Client(build_server()) as client:
        r = await client.call_tool(
            "fl_pattern_rename", {"index": 2, "name": "changed"}, raise_on_error=False
        )
        assert r.is_error and p.names[2] == "changed" and log.recent()[-1]["incomplete"]
        monkeypatch.setattr(p, "call", original)
        await client.call_tool("fl_rollback_last_change", {})
        assert p.names[2] != "changed" and not log.recent()


@pytest.mark.asyncio
async def test_page_transport_error_surfaces(rig, monkeypatch):
    p, c, log = rig
    original = p.call

    def fail(command, params=None):
        if command == "pattern_list" and params.get("start", 0) > 0:
            raise RuntimeError("page unavailable")
        return original(command, params)

    monkeypatch.setattr(p, "call", fail)
    async with Client(build_server()) as client:
        assert (await client.call_tool("fl_pattern_list", {}, raise_on_error=False)).is_error


def test_page_budget_and_fallback_api(rig, monkeypatch):
    import json

    p, c, log = rig
    start = 0
    while True:
        page = p.call("pattern_list", {"start": start})
        assert len(json.dumps(page, separators=(",", ":"))) <= 600
        if page["next_start"] is None:
            break
        assert page["next_start"] > start
        start = page["next_start"]
    monkeypatch.delattr(c.general, "getRecPPQ")
    monkeypatch.delattr(c.general, "getRecPPB")
    monkeypatch.delattr(c.patterns, "isPatternSelected")
    r = p.call("pattern_get_length", {"index": 1})
    assert r["ppq"] == 96 and r["length_bars"] == 4 and r["selected"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["rename", "select"])
async def test_failed_undo_survives_reload_then_retries(rig, monkeypatch, action):
    p, c, log = rig
    original = p.names[2]
    args = {"index": 2}
    if action == "rename":
        args["name"] = "changed"
    async with Client(build_server()) as client:
        await client.call_tool("fl_pattern_" + action, args)
        p.failure = action
        result = (await client.call_tool("fl_rollback_last_change", {})).data
        assert result["ok"] is False and result["recovery_retained"]
        reloaded = safety.ChangeLog()
        assert reloaded.recent() == log.recent()
        monkeypatch.setattr(safety, "_log", reloaded)
        p.failure = None
        result = (await client.call_tool("fl_rollback_last_change", {})).data
        assert result["ok"] is True
        assert p.names[2] == original and p.current == 1
        assert safety.ChangeLog().recent() == []


@pytest.mark.asyncio
async def test_undo_read_failure_retains_record(rig, monkeypatch):
    p, c, log = rig
    async with Client(build_server()) as client:
        await client.call_tool("fl_pattern_select", {"index": 2})
        original = p.call

        def fail_read(command, params=None):
            if command == "pattern_get_length":
                raise connection.FLTimeout("read unavailable")
            return original(command, params)

        monkeypatch.setattr(p, "call", fail_read)
        r = (await client.call_tool("fl_rollback_last_change", {})).data
        assert not r["ok"] and r["recovery_retained"] and log.recent()
        assert p.current == 1  # write landed; unreadable is not verified success
        monkeypatch.setattr(p, "call", original)
        assert (await client.call_tool("fl_rollback_last_change", {})).data["ok"]


@pytest.mark.asyncio
async def test_write_read_failure_keeps_record(rig, monkeypatch):
    p, c, log = rig
    original = p.call

    def fail_read(command, params=None):
        if command == "pattern_get_length" and p.writes:
            raise connection.FLTimeout("read unavailable")
        return original(command, params)

    monkeypatch.setattr(p, "call", fail_read)
    async with Client(build_server()) as client:
        r = await client.call_tool("fl_pattern_select", {"index": 2}, raise_on_error=False)
        assert r.is_error and p.current == 2 and log.recent()[-1]["incomplete"]


@pytest.mark.asyncio
async def test_optional_previous_name_failure_does_not_hide_success(rig, monkeypatch):
    p, c, log = rig
    original = p.call

    def fail_metadata(command, params=None):
        if command == "pattern_get_length" and params["index"] == 1:
            raise connection.FLTimeout("metadata unavailable")
        return original(command, params)

    monkeypatch.setattr(p, "call", fail_metadata)
    async with Client(build_server()) as client:
        r = (await client.call_tool("fl_pattern_select", {"index": 2})).data
        assert r["ok"] and r["verified"] and r["prev_index"] == 1
        assert "prev_name" not in r and log.recent()


@pytest.mark.parametrize("name", ["அ" * 300, "😀" * 150, '\\"' * 500])
@pytest.mark.parametrize("cmd", ["pattern_get_length", "pattern_rename", "pattern_select"])
def test_oversize_existing_name_rejected_without_mutation(rig, name, cmd):
    p, c, log = rig
    p.names[2] = name
    r = p.call(cmd, {"index": 2, "name": "replacement"})
    assert r["ok"] is False and r["code"] == "response_too_large"
    assert p.names[2] == name and p.current == 1 and not p.writes
    assert (
        len(json.dumps(protocol.decode_message(p.responses[-1][1:-1])[2], separators=(",", ":")))
        <= 600
    )


@pytest.mark.parametrize("name", ["அ" * 300, "😀" * 150, "அ" * 75])
def test_oversize_new_name_rejected_before_setter(rig, name):
    p, c, log = rig
    p.names[2] = "short"
    r = p.call("pattern_rename", {"index": 2, "name": name})
    assert not r["ok"] and r["code"] == "response_too_large"
    assert p.names[2] == "short" and not p.writes


@pytest.mark.parametrize("cmd", ["pattern_select", "pattern_rename"])
def test_combined_names_preflight(rig, cmd):
    p, c, log = rig
    p.names[1] = p.names[2] = "அ" * 46
    assert p.call("pattern_get_length", {"index": 2})["ok"]
    r = p.call(cmd, {"index": 2, "name": "அ" * 46})
    assert not r["ok"] and not p.writes


@pytest.mark.asyncio
async def test_lossless_unicode_undo(rig):
    p, c, log = rig
    old = 'தமிழ்😀\\"' * 3
    p.names[2] = old
    async with Client(build_server()) as client:
        result = (await client.call_tool("fl_pattern_rename", {"index": 2, "name": "புதிய"})).data
        assert result["ok"] and result["verified"] and result["before"]["name"] == old
        assert safety.ChangeLog().recent()[-1]["restore"]["params"]["name"] == old
        result = (await client.call_tool("fl_rollback_last_change", {})).data
        assert result["ok"] and p.names[2] == old


@pytest.mark.parametrize("cmd", ["pattern_select", "pattern_rename", "pattern_get_length"])
def test_large_native_exception_is_bounded(rig, monkeypatch, cmd):
    p, c, log = rig

    def fail(*args):
        raise RuntimeError("அ" * 500)

    native = {
        "pattern_select": "jumpToPattern",
        "pattern_rename": "setPatternName",
        "pattern_get_length": "getPatternLength",
    }[cmd]
    monkeypatch.setattr(c.patterns, native, fail)
    try:
        result = p.call(cmd, {"index": 2, "name": "changed"})
        assert result["ok"] is False
    except connection.FLCommandFailed as error:
        assert error.code == "response_too_large"
    assert (
        len(json.dumps(protocol.decode_message(p.responses[-1][1:-1])[2], separators=(",", ":")))
        <= 600
    )


@pytest.mark.parametrize("failure", ["exception", "rejected"])
def test_partial_group_undo_keeps_entire_record(rig, failure):
    p, c, log = rig
    entry = {
        "tool": "test_group",
        "group": True,
        "restores": [{"command": "restore", "params": {"index": i}} for i in (1, 2)],
    }
    log.append(entry)

    class Bridge:
        def call(self, command, params):
            if params["index"] == 2:
                if failure == "exception":
                    raise connection.FLTimeout("reply lost")
                return {"ok": False, "error": "rejected"}
            return {"ok": True}

    result = safety.rollback_last_change(Bridge())
    assert not result["ok"] and result["recovery_retained"]
    assert safety.ChangeLog().recent() == [entry]


def test_undo_does_not_remove_a_newer_entry(rig):
    p, c, log = rig
    first = {"tool": "first", "scope": "tempo", "before": {"bpm": 120.0},
             "restore": {"command": "set_tempo", "params": {"bpm": 120.0}},
             "project_token": "session:1"}
    newer = {"tool": "newer", "restore": {"command": "restore"}}
    log.append(first)

    class Bridge:
        def call(self, command, params=None):
            if command == "get_project_state":
                return {"project_token": "session:1", "project_loading": False}
            if command == "set_tempo":
                log.append(newer)          # something else lands mid-undo
                return {"ok": True}
            return {"bpm": 120.0}

    assert safety.rollback_last_change(Bridge())["ok"]
    assert log.recent() == [newer]


def test_undo_from_another_project_is_refused_and_kept(rig):
    p, c, log = rig
    stale = {"tool": "old", "scope": "tempo", "before": {"bpm": 120.0},
             "restore": {"command": "set_tempo", "params": {"bpm": 120.0}},
             "project_token": "other-session:7"}
    log.append(stale)
    result = safety.rollback_last_change(p)
    assert result["ok"] is False and result["undo_retained"]
    assert "another project" in result["error"]
    assert log.recent() == [stale] and p.writes == []


@pytest.mark.asyncio
async def test_large_rename_request_never_contacts_bridge(rig):
    p, c, log = rig
    async with Client(build_server()) as client:
        result = (
            await client.call_tool("fl_pattern_rename", {"index": 2, "name": "😀" * 300})
        ).data
        assert not result["ok"] and result["code"] == "request_too_large"
        assert not p.calls and not log.recent()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["fl_pattern_select", "fl_pattern_rename"])
async def test_oversized_snapshot_prevents_tool_write(rig, tool):
    p, c, log = rig
    p.names[2] = "😀" * 300
    args = {"index": 2}
    if tool.endswith("rename"):
        args["name"] = "new"
    async with Client(build_server()) as client:
        result = await client.call_tool(tool, args, raise_on_error=False)
        assert result.is_error or result.data.get("ok") is False
        assert not p.writes and not log.recent()


@pytest.mark.asyncio
async def test_all_999_patterns_even_with_one_entry_per_page(rig):
    p, c, log = rig
    p.names = {i: "😀" * 24 for i in range(1, 1000)}
    assert len(p.call("pattern_list", {})["patterns"]) == 1
    async with Client(build_server()) as client:
        result = (await client.call_tool("fl_pattern_list", {})).data
        assert [p["pattern"] for p in result["patterns"]] == list(range(1, 1000))


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [None, 50])
@pytest.mark.parametrize(
    "page",
    [
        {"ok": False, "error": "page rejected"},
        {"total": 60, "patterns": [], "next_start": 5},
        {"total": 60, "patterns": [{"pattern": 1, "name": "one"}], "next_start": 0},
    ],
)
async def test_invalid_page_does_not_look_like_complete_list(rig, monkeypatch, limit, page):
    p, c, log = rig
    monkeypatch.setattr(p, "call", lambda *args: page)
    async with Client(build_server()) as client:
        args = {} if limit is None else {"limit": limit}
        assert (await client.call_tool("fl_pattern_list", args, raise_on_error=False)).is_error


def test_page_cap_reports_incomplete_list():
    class Bridge:
        def call(self, command, params):
            start = params["start"]
            return {"total": 999, "patterns": [{"pattern": start + 1}], "next_start": start + 1}

    with pytest.raises(connection.FLCommandFailed, match="page limit"):
        connection.fetch_all_pages(Bridge(), "pattern_list", "patterns", max_pages=2)
