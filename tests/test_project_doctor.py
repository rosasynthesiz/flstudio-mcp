#!/usr/bin/env python3
"""Offline tests for project health reports and dry-run fix plan."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fl_studio_mcp import protocol  # noqa: E402
from fl_studio_mcp.tools import project_doctor as pd  # noqa: E402

_P = _F = 0


class FakeBridge:
    def call(self, command, params=None):
        params = params or {}
        if command == protocol.CMD_GET_PROJECT_STATE:
            return {"playing": False, "tempo": 140.0}
        if command == protocol.CMD_CHANNEL_GET:
            idx = int(params.get("index", 0))
            return {
                "i": idx,
                "name": "" if idx == 2 else f"Chan {idx}",
                "target_fx_track": 0 if idx == 0 else 1,
            }
        raise RuntimeError(f"unexpected call: {command}")


class FakeWatcher:
    def __init__(self, peaks):
        self._peaks = dict(peaks)

    def last_max(self):
        return dict(self._peaks)


def _fake_fetch_all_pages(_bridge, command, key):
    if command == protocol.CMD_CHANNEL_ROUTING_SUMMARY and key == "channels":
        return {
            "channels": [
                {
                    "channel": 0,
                    "name": "Kick",
                    "target_mixer_track": 1,
                    "target_name": "Kick",
                    "type": {"label": "genplug"},
                    "vol_norm": 0.70,
                },
                {
                    "channel": 1,
                    "name": "Audio Loop",
                    "target_mixer_track": 0,
                    "target_name": "Master",
                    "type": {"label": "audioclip"},
                    "vol_norm": 0.85,
                },
                {
                    "channel": 2,
                    "name": "Lead",
                    "target_mixer_track": 2,
                    "target_name": "Lead",
                    "type": {"label": "genplug"},
                    "vol_norm": 0.60,
                },
            ]
        }
    if command == protocol.CMD_CHANNEL_LIST and key == "channels":
        return {"channels": [{"i": 0, "name": "Kick"}, {"i": 2, "name": ""}]}
    if command == protocol.CMD_PATTERN_LIST and key == "patterns":
        return {
            "patterns": [
                {"index": 1, "name": "Lead", "length": 16},
                {"index": 2, "name": "Lead", "length": 16},
                {"index": 3, "name": "", "length": 8},
            ]
        }
    if command == protocol.CMD_PLAYLIST_LIST_TRACKS and key == "tracks":
        return {"tracks": [{"index": 1, "name": "PL1", "mute": True}]}
    if command == protocol.CMD_MIXER_LIST_TRACKS and key == "tracks":
        return {"tracks": [{"i": 1, "name": "Bus A"}, {"i": 2, "name": "Bus A"}]}
    if command == protocol.CMD_MIXER_GET_ROUTING_ALL and key == "routing":
        return {
            "routing": [
                {"i": 1, "name": "Bus A", "routes_to": [{"dst": 0, "dst_name": "Master"}]},
                {"i": 2, "name": "Bus A", "routes_to": [{"dst": 0, "dst_name": "Master"}]},
            ]
        }
    raise RuntimeError(f"unexpected fetch: {command}/{key}")


class MockMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, annotations=None):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def check(label, cond):
    global _P, _F
    if cond:
        _P += 1
        print(f"[PASS] {label}")
    else:
        _F += 1
        print(f"[FAIL] {label}")


def _ref_ids(result):
    return {row.get("id") for row in result.get("kb_policy_refs", [])}


def main() -> int:
    mcp = MockMCP()
    pd.register(mcp)
    pd.get_bridge = lambda: FakeBridge()
    pd.fetch_all_pages = _fake_fetch_all_pages
    original_get_watcher = pd.md.get_watcher

    try:
        report = mcp.tools["fl_project_health_report"]()
        check("health report ok", report.get("ok") is True)
        check("health report has findings", report.get("summary", {}).get("findings", 0) >= 1)

        readiness = mcp.tools["fl_export_readiness_report"]()
        check("readiness report ok", readiness.get("ok") is True)
        check("readiness marks project not ready", readiness.get("ready") is False)
        check(
            "readiness exposes mastering boundary KB ref",
            "mastering_after_mix_readiness" in _ref_ids(readiness),
        )

        plan = mcp.tools["fl_project_dry_run_fix_plan"]()
        check("dry-run fix plan ok", plan.get("ok") is True)
        check("dry-run flag true", plan.get("dry_run") is True)
        check("has planned actions", len(plan.get("plan", [])) > 0)
        check(
            "contains rollback-safe channel assignment action",
            any(
                a.get("tool") == "fl_assign_channel_to_free_mixer_track"
                for a in plan.get("plan", [])
            ),
        )

        dashboard = mcp.tools["fl_project_health_overview"]()
        check(
            "dashboard recommends current Mix Review tool name",
            any("fl_review_mix" in item for item in dashboard.get("recommendations", [])),
        )
        check(
            "dashboard exposes preservation and mastering KB refs",
            {
                "preserve_existing_structure_first",
                "mastering_after_mix_readiness",
            }.issubset(_ref_ids(dashboard)),
        )

        pd.md.get_watcher = lambda: FakeWatcher({0: 1.0})
        preflight = mcp.tools["fl_check_project_preflight"]()
        check(
            "preflight blocks Master output clipping from watch",
            any("output/render clipping risk" in item for item in preflight.get("blockers", [])),
        )
        check(
            "preflight reports watch peak source",
            preflight.get("mix_readiness", {}).get("master_peak_source") == "mix_review_watch",
        )
        check(
            "preflight keeps render and FL Cloud Mastering manual",
            any("FL Cloud Mastering" in item for item in preflight.get("manual_checklist", [])),
        )
        check(
            "preflight no longer uses generic API LIMITATION clipping copy",
            all("API LIMITATION" not in item for item in preflight.get("manual_checklist", [])),
        )
        check(
            "preflight exposes Master/output and manual mastering KB refs",
            {
                "master_peak_boundary",
                "mix_doctor_master_output_boundary",
                "mastering_after_mix_readiness",
                "fl_cloud_mastering_manual_only",
            }.issubset(_ref_ids(preflight)),
        )

        pd.md.get_watcher = lambda: FakeWatcher({0: 10 ** (-0.5 / 20)})
        advisory_preflight = mcp.tools["fl_check_project_preflight"]()
        check(
            "preflight warns near-zero Master peak from watch",
            any("leave more headroom" in item for item in advisory_preflight.get("advisories", [])),
        )

        pd.md.get_watcher = lambda: FakeWatcher({})
        missing_peak_preflight = mcp.tools["fl_check_project_preflight"]()
        check(
            "preflight asks for Mix Review watch when Master peak is missing",
            any(
                "Run Mix Review watch mode" in item
                for item in missing_peak_preflight.get("manual_checklist", [])
            ),
        )
    finally:
        pd.md.get_watcher = original_get_watcher

    print(f"\nProject doctor offline tests: {_P} passed, {_F} failed.")
    return 1 if _F else 0


if __name__ == "__main__":
    raise SystemExit(main())
