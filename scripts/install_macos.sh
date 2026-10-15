#!/usr/bin/env bash
# ============================================================================
# FLStudioMCP -- macOS installer (v0.2 -- MIDI transport)
# ============================================================================
set -euo pipefail

FL_HARDWARE="$HOME/Documents/Image-Line/FL Studio/Settings/Hardware"
TARGET="$FL_HARDWARE/FLStudioMCP"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo
echo "[1/4] Installing FL Studio controller script..."
if [[ ! -d "$FL_HARDWARE" ]]; then
  echo "  FL Studio Hardware folder not found at:"
  echo "    $FL_HARDWARE"
  echo "  Open FL Studio at least once, then re-run this script."
  exit 1
fi
mkdir -p "$TARGET"
cp "$REPO_ROOT/fl_controller/FLStudioMCP/device_FLStudioMCP.py" "$TARGET/"
echo "  Installed to $TARGET"

echo
echo "[2/4] Installing the MCP server (editable)..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "  python3 not found. Install Python 3.10+ and re-run."
  exit 1
fi
cd "$REPO_ROOT"
python3 -m pip install --upgrade pip >/dev/null
python3 -m pip install -e .

# Optional audio to MIDI. Preset FLMCP_EXTRAS=all or none to skip the question.
echo
if [[ -z "${FLMCP_EXTRAS:-}" ]]; then
  echo "  Optional: audio to MIDI. Turns audio into MIDI notes (melodies and full"
  echo "  chords) and detects tempo and key. About 650 MB. You can re-run this"
  echo "  installer later to add it."
  read -r -p "  Install audio to MIDI? [y/N] " answer
  if [[ "$answer" =~ ^[Yy] ]]; then FLMCP_EXTRAS="all"; else FLMCP_EXTRAS="none"; fi
fi
[[ "$FLMCP_EXTRAS" == *all* ]] && FLMCP_EXTRAS="audio accurate chords"
EXTRAS=()
[[ "$FLMCP_EXTRAS" == *audio* || "$FLMCP_EXTRAS" == *accurate* ]] && EXTRAS+=("audio")
[[ "$FLMCP_EXTRAS" == *accurate* ]] && EXTRAS+=("audio-accurate")
[[ "$FLMCP_EXTRAS" == *chords* ]] && EXTRAS+=("audio-chords")
if (( ${#EXTRAS[@]} )); then
  joined="$(IFS=,; echo "${EXTRAS[*]}")"
  echo "  Installing extras: $joined"
  python3 -m pip install -e ".[$joined]" || echo "  WARNING: installing the extras failed. See output above."
  if [[ "$FLMCP_EXTRAS" == *chords* ]]; then
    # Skip Basic Pitch's TensorFlow/CoreML pins; we run its ONNX model.
    python3 -m pip install --no-deps "basic-pitch==0.4.0"
    python3 -c "from fl_studio_mcp.tools.audio import chords_available as c; print('  Chords to MIDI: ready' if c() else '  WARNING: chords to MIDI is not working, see output above')"
  fi
else
  echo "  Audio to MIDI not installed."
fi

echo
echo "[3/4] Seeding the note-bridge pyscript (MCP_Apply)..."
if ! python3 - <<'PYEOF'
import os

import fl_studio_mcp.pyscript_gen as g

os.makedirs(g.PIANO_ROLL_SCRIPTS_DIR, exist_ok=True)
print("  Seeded " + g.write_apply_script([], mode="append"))
PYEOF
then
  echo "  Note: Could not pre-seed MCP_Apply. Non-fatal -- the daemon will write it on first note-write."
fi

echo
echo "[4/4] Checking for IAC Driver ports..."
python3 - <<'PYEOF'
import mido
names = set(mido.get_output_names()) | set(mido.get_input_names())
rx, tx = "FLStudioMCP RX", "FLStudioMCP TX"
missing = [n for n in (rx, tx) if not any(n.lower() in x.lower() for x in names)]
if not missing:
    print("  All required ports present.")
else:
    print(f"  Missing ports: {missing}")
PYEOF

cat <<EOF

Done.

Next steps:
  1. If the port check above said any port is MISSING:
     - Open 'Audio MIDI Setup'.
     - Window > Show MIDI Studio.
     - Double-click IAC Driver. Tick 'Device is online'.
     - Under 'Ports', add two ports named exactly:
         FLStudioMCP RX
         FLStudioMCP TX
     - Apply, then re-run this installer.
  2. Open FL Studio.
  3. Options > MIDI Settings:
       Input list  > click 'FLStudioMCP RX', tick Enable, Controller type=FLStudioMCP, Port=42.
       Output list > click 'FLStudioMCP TX', tick Enable, Port=42 (SAME number).
  4. View > Script output should show '[FLStudioMCP] Ready. ...'.
  5. Run: python3 scripts/test_bridge.py

IMPORTANT (macOS Accessibility):
  Note writing simulates Cmd+Opt+Y to trigger FL Studio's "Run last script again"
  command. Grant Accessibility permission to the application running the MCP
  server or daemon, for example Terminal, iTerm, Claude Desktop, or Cursor:

    System Settings > Privacy & Security > Accessibility
EOF
