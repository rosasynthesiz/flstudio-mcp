"""`fl-studio-mcp setup | doctor | connect` -- install, check, and wire up.

Goal: a new user runs ONE command, opens FL Studio, and is connected.

* ``setup``   copies the controller script that ships with this server into
              FL Studio's user-data folder (backing up a different old copy),
              waits for FL Studio to be opened, then runs ``doctor``.
              It waits when run in a terminal; ``--no-wait`` skips that and
              ``--wait`` forces it elsewhere.
* ``doctor``  checks every stage and prints the one next step. Read-only.
* ``connect`` prints the MCP client entry to paste (it edits no files).

Nothing here installs into a system Python, and "ready" is only reported after
a real ping round trip with a matching controller version.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, paths, protocol

GIT_SOURCE = "git+https://github.com/rosasynthesiz/flstudio-mcp"

# Status code -> the one thing to do next.
STATUS_HELP = {
    "READY": "Connected. Ask Claude to do something in FL Studio.",
    "FL_NOT_INSTALLED": "Install FL Studio 2025 or newer, open it once, then run "
                        "`fl-studio-mcp setup` again.",
    "USER_DATA_MISSING": "Open FL Studio once so it creates its user-data folder, "
                         "then run `fl-studio-mcp setup` again.",
    "CONTROLLER_MISSING": "Run `fl-studio-mcp setup`.",
    "VERSION_MISMATCH": "Run `fl-studio-mcp setup`, then restart FL Studio.",
    "PORTS_MISSING": "Windows: create two loopMIDI ports named 'FLStudioMCP RX' "
                     "and 'FLStudioMCP TX'. macOS/Linux: run `fl-studio-mcp doctor` "
                     "from a normal terminal.",
    "MIDI_UNAVAILABLE": "This app runs the server in a sandbox that blocks MIDI. "
                        "Run `fl-studio-mcp-daemon` in a normal terminal and keep "
                        "it open; the server then uses that.",
    "FL_CLOSED": "Open FL Studio and load any project.",
    "NO_HEARTBEAT": "Restart FL Studio once (needed only the first time). If it "
                    "still fails: Options > MIDI Settings, select FLStudioMCP in "
                    "Input, turn on Enable, choose Controller type FLStudioMCP, "
                    "and give Input and Output the same Port number. On the "
                    "Microsoft Store build of Claude Desktop, also start "
                    "`fl-studio-mcp-daemon` (scripts\\start_daemon.bat) first.",
    "PING_TIMEOUT": "FL Studio is busy (a dialog may be open). Close the dialog "
                    "and try again.",
}


# ---------------------------------------------------------------------------
# Facts about this machine
# ---------------------------------------------------------------------------

def find_fl_app() -> str | None:
    """Path of an installed FL Studio, or None if we could not find one."""
    if sys.platform == "darwin":
        apps = sorted(Path("/Applications").glob("FL Studio*.app"))
        return str(apps[-1]) if apps else None
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not root:
                continue
            hits = sorted(Path(root).glob("Image-Line/FL Studio*/FL64.exe"))
            if hits:
                return str(hits[-1])
    return None


def fl_is_running() -> bool | None:
    """True/False, or None when we cannot tell on this OS."""
    try:
        if sys.platform == "darwin":
            return subprocess.run(["pgrep", "-x", "OsxFL"], capture_output=True).returncode == 0
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FL64.exe"],
                                 capture_output=True, text=True).stdout
            return "FL64.exe" in out
    except OSError:
        return None
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def controller_version(path: Path) -> str | None:
    """The CONTROLLER_VERSION declared in a controller script file."""
    try:
        m = re.search(r'^CONTROLLER_VERSION\s*=\s*"([^"]+)"',
                      path.read_text(encoding="utf-8", errors="replace"), re.M)
    except OSError:
        return None
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

def install_controller() -> dict:
    """Copy the bundled controller into FL's Hardware folder.

    Never overwrites silently: a different existing file is kept next to the
    new one as ``device_FLStudioMCP.py.bak-<timestamp>``. The copy is atomic.
    """
    settings = paths.fl_settings_dir()
    if not settings.is_dir():
        return {"ok": False, "status": "USER_DATA_MISSING", "settings_dir": str(settings)}
    src = paths.bundled_controller()
    dst = paths.installed_controller()
    result = {"ok": True, "path": str(dst), "version": controller_version(src)}
    if dst.is_file() and _sha256(dst) == _sha256(src):
        result["action"] = "already up to date"
        return result
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file():
        backup = dst.with_name(dst.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(dst, backup)
        result["backup"] = str(backup)
        result["action"] = "updated"
    else:
        result["action"] = "installed"
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    return result


def seed_note_bridge() -> str | None:
    """Pre-write the MCP_Apply piano-roll script. Optional; None on failure."""
    try:
        from . import pyscript_gen
        os.makedirs(pyscript_gen.PIANO_ROLL_SCRIPTS_DIR, exist_ok=True)
        return str(pyscript_gen.write_apply_script([], mode="append"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def diagnose(wait: float = 6.0) -> dict:
    """Check each stage and name the first one that blocks the connection.

    Returns ``{"status": CODE, "next": str, "checks": [...], ...}``. ``READY``
    needs a fresh ping round trip and a controller that matches this server.
    """
    checks: list[dict] = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    def done(status: str, **extra) -> dict:
        return {"status": status, "next": STATUS_HELP[status], "server_version": __version__,
                "checks": checks, **extra}

    # File checks explain a failure; they do not veto a connection that works.
    blocked: str | None = None

    app = find_fl_app()
    add("FL Studio installed", bool(app) if sys.platform in ("darwin", "win32") else None,
        app or "not found in the standard location")

    settings = paths.fl_settings_dir()
    add("FL user-data folder", settings.is_dir(), str(settings))
    if not settings.is_dir():
        blocked = "FL_NOT_INSTALLED" if not app else "USER_DATA_MISSING"

    installed = paths.installed_controller()
    have = controller_version(installed) if installed.is_file() else None
    want = controller_version(paths.bundled_controller())
    if not installed.is_file():
        add("Controller script installed", False, str(installed))
        blocked = blocked or "CONTROLLER_MISSING"
    else:
        add("Controller script installed", have == want,
            "version %s (server expects %s)" % (have or "unknown / older", want))
        if have != want:
            blocked = blocked or "VERSION_MISMATCH"

    from .connection import FLBridgeError, FLPortMissing, FLTimeout, get_bridge
    try:
        bridge = get_bridge()
    except FLPortMissing as e:
        add("MIDI bridge", False, str(e))
        return done("PORTS_MISSING")
    except FLBridgeError as e:
        add("MIDI bridge", False, str(e))
        return done("MIDI_UNAVAILABLE")
    except Exception as e:  # rtmidi backend errors, sandboxed CoreMIDI, ...
        add("MIDI bridge", False, "%s: %s" % (type(e).__name__, e))
        return done("MIDI_UNAVAILABLE")
    owner = type(bridge).__name__ == "FLBridge"
    add("MIDI bridge", True, "this process owns the MIDI ports" if owner
        else "joined the running bridge")

    running = fl_is_running()
    add("FL Studio running", running, "yes" if running else
        ("no" if running is False else "could not check on this OS"))

    # FL re-attaches to a known device within a second or two.
    deadline = time.monotonic() + wait
    alive = bridge.is_alive()
    while not alive and time.monotonic() < deadline:
        time.sleep(0.25)
        alive = bridge.is_alive()
    add("Heartbeat from FL Studio", alive, "received" if alive else
        "none in %.0f s" % wait)
    if not alive:
        return done(blocked or ("FL_CLOSED" if running is False else "NO_HEARTBEAT"))

    # Right after the ports appear FL's heartbeat can arrive a moment before
    # FL listens on its input, so the first ping may be lost: retry briefly.
    pong = None
    for attempt in range(4):
        try:
            pong = bridge.call(protocol.CMD_PING, timeout=1.5) or {}
            break
        except FLTimeout as e:
            if attempt == 3:
                add("Ping round trip", False, str(e))
                return done("PING_TIMEOUT")
        except FLBridgeError as e:
            add("Ping round trip", False, str(e))
            return done("NO_HEARTBEAT")
    live = pong.get("controller_version")
    proto_ok = pong.get("protocol_version") == protocol.PROTOCOL_VERSION
    add("Ping round trip", True, str(pong.get("fl_version", "FL Studio answered")))
    add("Controller loaded in FL matches", live == want and proto_ok,
        "loaded %s, protocol %s" % (live or "older build", pong.get("protocol_version")))
    if live != want or not proto_ok:
        return done("VERSION_MISMATCH", fl_version=pong.get("fl_version"))
    return done("READY", fl_version=pong.get("fl_version"))


def wait_for_fl(timeout: float = 180.0, restart: bool = False) -> bool:
    """Hold the MIDI ports open until FL Studio answers. True once it does."""
    from .connection import FLBridgeError, get_bridge
    try:
        bridge = get_bridge()
    except FLBridgeError:
        return False
    print("Now %s FL Studio and load any project. Waiting up to %d s (Ctrl+C to stop)..."
          % ("restart" if restart else "open", timeout), flush=True)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if bridge.is_alive():
                print("FL Studio answered.\n", flush=True)
                return True
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
    return False


def _print_report(report: dict) -> None:
    for c in report["checks"]:
        mark = {True: "ok ", False: "NO ", None: " ? "}[c["ok"]]
        print("  [%s] %s -- %s" % (mark, c["check"], c["detail"]))
    print()
    print("Status: %s" % report["status"])
    print("Next:   %s" % report["next"])


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

def launch_command() -> tuple[str, list[str]]:
    """How an MCP client should start this server.

    * Installed in a lasting environment (the installers' ``.venv``, pip):
      the full path of this ``fl-studio-mcp`` executable.
    * Run through ``uvx`` (a throwaway cache environment): ``uvx`` again --
      from PyPI for a release, from git for a development build, so the
      client does not start the older PyPI server.
    """
    name = "fl-studio-mcp.exe" if sys.platform == "win32" else "fl-studio-mcp"
    exe = Path(sys.executable).parent / name
    parts = [x.lower() for x in exe.parts]
    throwaway = "uv" in parts and any(x.startswith("archive-v") for x in parts)
    if exe.is_file() and not throwaway:
        return str(exe), []
    if "dev" in __version__:
        return "uvx", ["--from", GIT_SOURCE, "fl-studio-mcp"]
    return "uvx", ["fl-studio-mcp"]


def client_snippets() -> dict:
    """Ready-to-paste MCP client entries. We print them; we edit no files."""
    command, args = launch_command()
    entry = {"command": command, "args": args}
    quoted = '"%s"' % command if " " in command else command
    return {
        "claude-code": " ".join(["claude mcp add fl-studio --", quoted] + args),
        "claude-desktop": json.dumps({"mcpServers": {"fl-studio": entry}}, indent=2),
        "cursor": json.dumps({"mcpServers": {"fl-studio": entry}}, indent=2),
        "codex": "[mcp_servers.fl-studio]\ncommand = %s\nargs = %s"
                 % (json.dumps(command), json.dumps(args)),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run(argv: list[str]) -> int:
    """Handle `setup`, `doctor`, `connect`. Returns a process exit code."""
    cmd, rest = argv[0], argv[1:]
    as_json = "--json" in rest

    if cmd == "connect":
        snippets = client_snippets()
        wanted = [a for a in rest if not a.startswith("-")]
        names = wanted or list(snippets)
        unknown = [n for n in names if n not in snippets]
        if unknown:
            print("Unknown client: %s. Choose from: %s"
                  % (", ".join(unknown), ", ".join(snippets)))
            return 2
        for n in names:
            print("# %s\n%s\n" % (n, snippets[n]))
        return 0

    report: dict = {}
    if cmd == "setup":
        installed = install_controller()
        report["install"] = installed
        if installed.get("ok"):
            report["note_bridge"] = seed_note_bridge()
            if not as_json:
                print("Controller %s: %s" % (installed["action"], installed["path"]))
                if installed.get("backup"):
                    print("  old copy kept at %s" % installed["backup"])
                if installed["action"] != "already up to date" and fl_is_running():
                    print("  FL Studio is open: restart it to load the new controller.")
                print()
    report.update(diagnose())
    # Wait only when someone is there to open FL Studio (a terminal), or when
    # asked with --wait. Scripts and CI get the report straight away.
    wants_wait = "--wait" in rest or (sys.stdout.isatty() and "--no-wait" not in rest)
    if (cmd == "setup" and not as_json and wants_wait
            and report["status"] in ("FL_CLOSED", "NO_HEARTBEAT")):
        # First link: FL picks the controller up when it starts while our MIDI
        # ports exist, and remembers it afterwards. So keep them open and wait.
        if wait_for_fl(restart=report["status"] == "NO_HEARTBEAT"):
            report.update(diagnose(wait=2.0))
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
        if cmd == "setup" and report["status"] == "READY":
            print("\nAdd it to your AI client with:  fl-studio-mcp connect")
    return 0 if report["status"] == "READY" else 1
