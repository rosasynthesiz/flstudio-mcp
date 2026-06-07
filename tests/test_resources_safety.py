from __future__ import annotations

import asyncio
from unittest.mock import patch

from fl_studio_mcp.server import build_server
from fl_studio_mcp.tools.resources import _summary


def test_resource_truncation_hints_use_domain_tools() -> None:
    """Ensure truncated resources do not suggest stale tools."""

    # Simulate a large response that forces truncation
    fake_channels = {"total": 50, "channels": [{"name": f"Ch {i}"} for i in range(50)]}

    # Test channels truncation hint
    result_channels = _summary(fake_channels, "channels", 'fl_channel(action="list")')
    assert result_channels.get("truncated") is True
    assert 'fl_channel(action="list")' in result_channels["note"]
    assert "fl_get_channel_state" not in result_channels["note"]

    # Test mixer truncation hint
    fake_tracks = {"total": 50, "tracks": [{"name": f"Tr {i}"} for i in range(50)]}
    result_mixer = _summary(fake_tracks, "tracks", 'fl_mixer(action="list")')
    assert result_mixer.get("truncated") is True
    assert 'fl_mixer(action="list")' in result_mixer["note"]
    assert "fl_get_mixer_state" not in result_mixer["note"]

    # Test patterns truncation hint
    fake_patterns = {"total": 100, "patterns": [{"name": f"Pat {i}"} for i in range(100)]}
    result_patterns = _summary(fake_patterns, "patterns", 'fl_pattern(action="list")')
    assert result_patterns.get("truncated") is True
    assert 'fl_pattern(action="list")' in result_patterns["note"]
    assert "fl_get_project_state" not in result_patterns["note"]


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


@patch("fl_studio_mcp.tools.resources.get_bridge")
def test_bridge_failure_handling(mock_get_bridge) -> None:
    """Ensure all resources degrade gracefully when bridge is down."""

    # Make get_bridge raise an exception simulating bridge down
    mock_get_bridge.side_effect = Exception("Bridge connection refused")

    server = build_server()

    # Read resources and assert they return graceful error dicts instead of crashing
    resources = [
        "fl://status",
        "fl://project",
        "fl://transport",
        "fl://channels",
        "fl://mixer",
        "fl://patterns",
    ]

    for uri in resources:
        text = _text(asyncio.run(server.read_resource(uri)))
        assert "error" in text.lower(), f"Resource {uri} did not gracefully handle bridge failure."
        assert "Exception: Bridge connection refused" in text
