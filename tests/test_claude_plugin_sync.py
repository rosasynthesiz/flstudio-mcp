"""The vendored copy in claude-plugin/ must match src/ (run scripts/sync_claude_plugin.py)."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_claude_plugin", ROOT / "scripts" / "sync_claude_plugin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vendored_package_matches_src():
    problems = _sync_module().drift()
    assert not problems, "claude-plugin is stale; run scripts/sync_claude_plugin.py:\n" + "\n".join(problems)


def test_setup_cli_not_vendored():
    assert not (ROOT / "claude-plugin" / "fl_studio_mcp" / "setup_cli.py").exists()


def test_plugin_version_matches_main_package():
    main = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    plugin = tomllib.loads((ROOT / "claude-plugin" / "pyproject.toml").read_text())["project"]["version"]
    assert main == plugin


def test_ping_without_setup_helper(monkeypatch):
    from fl_studio_mcp.connection import FLPortMissing
    from fl_studio_mcp.tools import transport

    def no_ports():
        raise FLPortMissing("no ports")

    monkeypatch.setattr(transport, "get_bridge", no_ports)
    out = transport._ping_without_setup()
    assert out["status"] == "PORTS_MISSING" and out["alive"] is False
    assert out["next"] and out["server_version"]
