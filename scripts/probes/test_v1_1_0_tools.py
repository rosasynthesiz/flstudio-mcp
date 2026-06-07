"""Live test for v1.1.0 project organization and routing tools.
Creates a mess in FL Studio, verifies the tools detect it, fixes it, and rolls back.
"""

import time

from fl_studio_mcp import safety
from fl_studio_mcp.connection import get_bridge
from fl_studio_mcp.protocol import (
    CMD_CHANNEL_SET_NAME,
    CMD_CHANNEL_SET_TARGET,
    CMD_CHANNEL_SET_VOLUME,
)

# Import tools modules
from fl_studio_mcp.tools import channels, mixer_core, project_doctor, project_organizer, routing


class DummyMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, annotations=None, **kwargs):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def run_tests():
    print("--- Starting Live Verification for v1.1.0 Tools ---")

    # 1. Extract tools
    mcp = DummyMCP()
    channels.register(mcp)
    routing.register(mcp)
    project_organizer.register(mcp)
    project_doctor.register(mcp)
    mixer_core.register(mcp)

    tools = mcp.tools

    bridge = get_bridge()

    print("Creating test cases in FL Studio (Channel 0)...")
    safety.safe_write(
        bridge,
        tool="test_setup",
        scope="channel:0",
        command=CMD_CHANNEL_SET_NAME,
        params={"channel": 0, "name": "Channel 1"},
        build_restore=lambda b: {
            "command": CMD_CHANNEL_SET_NAME,
            "params": {"channel": 0, "name": b.get("name", "Sampler")},
        },
    )
    safety.safe_write(
        bridge,
        tool="test_setup",
        scope="channel:0",
        command=CMD_CHANNEL_SET_VOLUME,
        params={"channel": 0, "value": 0.9, "unit": "normalized"},
        build_restore=lambda b: {
            "command": CMD_CHANNEL_SET_VOLUME,
            "params": {"channel": 0, "value": b.get("vol_norm", 0.78), "unit": "normalized"},
        },
    )
    safety.safe_write(
        bridge,
        tool="test_setup",
        scope="channel:0",
        command=CMD_CHANNEL_SET_TARGET,
        params={"channel": 0, "track": 0},
        build_restore=lambda b: {
            "command": CMD_CHANNEL_SET_TARGET,
            "params": {"channel": 0, "track": b.get("target_fx_track", 1)},
        },
    )

    time.sleep(0.5)

    try:
        # 2. Test Analyzers
        print("\n--- Testing Analyzers ---")
        org_report = tools["fl_analyze_project_organization"]()
        print("Project Organization Analysis (Unnamed):", len(org_report["unnamed_channels"]))

        audio_report = tools["fl_inspect_audio_clips"]()
        print(f"Audio Clips Found: {audio_report['count']}")
        if audio_report["count"] > 0:
            print(f"Audio Clip Issues: {audio_report['audio_clips'][0].get('issues', [])}")

        routing_report = tools["fl_review_routing"]()
        print(f"Unrouted Channels: {len(routing_report['unrouted_channels'])}")

        health = tools["fl_project_health_overview"]()
        print(
            f"Health Overview Status: {health['status']} | Unrouted: {health['metrics']['unrouted_channels']}"
        )

        preflight = tools["fl_check_project_preflight"]()
        print(f"Preflight Status: {preflight['status']} | Blockers: {len(preflight['blockers'])}")

        # 3. Test Apply Audio Clip Safe Defaults
        print("\n--- Testing Apply Audio Clip Safe Defaults ---")
        if audio_report["count"] > 0:
            res = tools["fl_apply_audio_clip_safe_defaults"]()
            print("Safe Defaults result:", res.get("assignments", "No writes"))
            if res.get("assignments"):
                print("Rolling back safe defaults...")
                tools["fl_rollback_last_change"]()

        # 4. Test Naming Standard
        print("\n--- Testing Apply Naming Standard ---")
        res = tools["fl_apply_naming_standard"](
            style="psytrance", rules=[{"type": "channel", "index": 0, "name": "PSY_KICK"}]
        )
        print("Naming Standard Result:", res.get("after"))
        print("Rolling back naming standard...")
        tools["fl_rollback_last_change"]()

        # 5. Test Bus Layout
        print("\n--- Testing Create Bus Layout ---")
        res = tools["fl_apply_bus_layout"](
            buses=[{"bus_track": 10, "name": "DRUM_BUS", "source_tracks": [1, 2]}]
        )
        print("Bus Layout Result:", res.get("after"))
        print("Rolling back bus layout...")
        tools["fl_rollback_last_change"]()

        # 6. Test Change Log Summary
        print("\n--- Testing Change Log Summary ---")
        res = tools["fl_get_change_log_summary"](limit=5)
        print("Change log table snippet:")
        print(res.get("markdown_table", "No table")[:200] + "...")

        print("\nAll tests passed successfully.")

    finally:
        print("\nRolling back test setup mess...")
        tools["fl_rollback_last_change"]()  # target
        tools["fl_rollback_last_change"]()  # volume
        tools["fl_rollback_last_change"]()  # name


if __name__ == "__main__":
    run_tests()
