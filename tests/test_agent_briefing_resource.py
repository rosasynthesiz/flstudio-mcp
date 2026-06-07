from __future__ import annotations

import asyncio

from fl_studio_mcp.server import build_server


def _text(resource_result) -> str:
    if isinstance(resource_result, (list, tuple)) and resource_result:
        resource_result = resource_result[0]
    for attr in ("text", "content", "data"):
        value = getattr(resource_result, attr, None)
        if isinstance(value, str):
            return value
        if value is not None:
            return str(value)
    return str(resource_result)


def test_agent_briefing_resource_is_compact_and_current() -> None:
    server = build_server()
    text = _text(asyncio.run(server.read_resource("fl://agent-briefing")))

    assert len(text) < 5000
    assert "fl://status" in text
    for name in (
        "fl_transport",
        "fl_mixer",
        "fl_channel",
        "fl_pattern",
        "fl_playlist",
        "fl_effect",
        "fl_plugin",
        "fl_piano_roll",
        "fl_batch",
    ):
        assert name in text

    assert "snapshot" in text
    assert "readback" in text
    assert "rollback" in text
    assert "fl_ping" not in text
    assert "fl_get_tempo" not in text
    assert "fl_plugin_list" not in text
    assert "fl_piano_write_notes" not in text
