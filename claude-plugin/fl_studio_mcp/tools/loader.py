"""Plugin loading -- capability-aware, drawback-informing tool.

FL Studio's scripting API cannot instantiate a plugin or add a channel/mixer
insert (verified: channels/mixer/general expose zero add/load/create functions).
Rather than silently fail or perform fragile, unreliable UI automation, this
tool tells the calling agent exactly WHY loading isn't supported, the drawbacks
of the only workaround (UI automation), and the reliable alternatives -- so the
agent can make an informed decision and guide the user.

An opt-in ``attempt_focus`` flag will bring FL to the foreground (best-effort)
to make manual loading quicker, but it never blindly simulates plugin selection
(which would risk loading the wrong thing).
"""
from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field


def describe_load_limitation(name: str, as_generator: bool) -> dict:
    """Structured explanation of the load limitation + safe alternatives. PURE."""
    where = ("channel rack (a generator/instrument)" if as_generator
             else "a mixer insert slot (an effect)")
    return {
        "ok": False,
        "supported": False,
        "requested": {"name": name, "as_generator": as_generator},
        "reason": ("FL Studio's MIDI Controller Scripting API exposes NO function "
                   "to instantiate a plugin or add a channel/mixer insert "
                   "(verified on this build: channels/mixer/general expose zero "
                   "add/load/create/insert functions)."),
        "drawbacks_of_ui_automation": [
            "Brittle: simulating clicks/keystrokes to drive FL's plugin picker "
            "depends on window layout, FL version, theme, and current screen "
            "state -- it can misfire and load the WRONG plugin or nothing.",
            "Not verifiable: the bridge can't confirm what actually got loaded.",
            "Needs macOS Accessibility permission and FL frontmost.",
            "So it is intentionally NOT performed automatically here.",
        ],
        "recommended": [
            "Load '%s' manually into %s, then control it fully via the plugin "
            "tools." % (name, where),
            "Or keep a TEMPLATE project with your go-to instruments/effects "
            "pre-loaded; the server controls everything in it immediately.",
        ],
        "after_loading": (
            "Once loaded, confirm with fl_plugin_list(track) for an effect, or "
            "fl_plugin_get_params(track=<channel>, slot=-1) for a generator; then "
            "shape it with fl_plugin_overview / fl_plugin_calibrate_param / "
            "fl_plugin_set_param_value / fl_plugin_intent (all reversible)."),
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations={
        "title": "Load a plugin (NOT supported by FL API -- explains why)",
        "readOnlyHint": True, "idempotentHint": True, "openWorldHint": True,
    })
    def fl_load_plugin(
        name: Annotated[str, Field(description="Plugin name you want loaded, e.g. 'Vital'.")],
        as_generator: Annotated[bool, Field(
            description="True = instrument on a channel; False = effect on a mixer slot.")] = True,
        attempt_focus: Annotated[bool, Field(
            description="Best-effort: bring FL to the foreground to speed up MANUAL "
                        "loading. Never simulates plugin selection.")] = False,
    ) -> dict:
        """Attempt to load a plugin -- but FL's scripting API CANNOT do this, so
        this tool instead explains why, the drawbacks of UI-automation
        workarounds, and the reliable path (load manually or use a template),
        then tells you exactly how to control the plugin once it's loaded. Call
        it to understand the limitation rather than expecting an actual load."""
        result = describe_load_limitation(name, as_generator)
        if attempt_focus:
            import subprocess
            import sys
            try:
                if sys.platform == "darwin":
                    subprocess.run(
                        ["osascript", "-e", 'tell application "FL Studio" to activate'],
                        check=True, capture_output=True, timeout=3)
                    result["focus_attempt"] = {"focused": True, "method": "AppleScript activate"}
                else:
                    result["focus_attempt"] = {
                        "focused": False,
                        "note": "focus attempt implemented for macOS only; bring FL forward manually",
                    }
            except Exception as e:
                result["focus_attempt"] = {"focused": False, "note": "%s: %s" % (type(e).__name__, e)}
        return result
