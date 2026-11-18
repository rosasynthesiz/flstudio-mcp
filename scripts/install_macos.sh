#!/usr/bin/env bash
# ============================================================================
# FLStudioMCP -- macOS installer (v2)
#
# From a checkout. Most users do not need this file:
#     uvx fl-studio-mcp setup
#
# What it does: makes a private .venv in this folder (your system Python is not
# touched), installs the server there, then runs `fl-studio-mcp setup`, which
# installs the FL controller, waits for FL Studio and checks the connection.
# No IAC Driver / Audio MIDI Setup step: the server creates its own MIDI ports.
#
# Optional audio features: FLMCP_EXTRAS="audio" | "audio accurate chords" | "all"
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_ROOT/.venv"
cd "$REPO_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ and re-run."
  exit 1
fi

echo "[1/3] Private environment: $VENV"
[[ -d "$VENV" ]] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip

echo "[2/3] Installing the MCP server..."
FLMCP_EXTRAS="${FLMCP_EXTRAS:-none}"
[[ "$FLMCP_EXTRAS" == *all* ]] && FLMCP_EXTRAS="audio accurate chords"
EXTRAS=()
[[ "$FLMCP_EXTRAS" == *audio* || "$FLMCP_EXTRAS" == *accurate* ]] && EXTRAS+=("audio")
[[ "$FLMCP_EXTRAS" == *accurate* ]] && EXTRAS+=("audio-accurate")
[[ "$FLMCP_EXTRAS" == *chords* ]] && EXTRAS+=("audio-chords")
if (( ${#EXTRAS[@]} )); then
  joined="$(IFS=,; echo "${EXTRAS[*]}")"
  "$VENV/bin/python" -m pip install --quiet -e ".[$joined]"
  if [[ "$FLMCP_EXTRAS" == *chords* ]]; then
    # Skip Basic Pitch's TensorFlow/CoreML pins; we run its ONNX model.
    "$VENV/bin/python" -m pip install --quiet --no-deps "basic-pitch==0.4.0"
    "$VENV/bin/python" -c "from fl_studio_mcp.tools.audio import chords_available as c; print('  Chords to MIDI: ready' if c() else '  WARNING: chords to MIDI is not working')"
  fi
else
  "$VENV/bin/python" -m pip install --quiet -e .
  echo "  Audio to MIDI not installed (optional: FLMCP_EXTRAS=all)."
fi

echo "[3/3] Controller + connection check..."
echo
# The install itself is done here. `setup` exits non-zero while FL Studio is
# not connected yet, which is normal on a first run: report it, do not fail.
if "$VENV/bin/fl-studio-mcp" setup "$@"; then
  echo
  echo "Installed and connected. Commands live in: $VENV/bin"
else
  echo
  echo "Installed. FL Studio is not connected yet: do the 'Next' step above,"
  echo "then run:  $VENV/bin/fl-studio-mcp doctor"
fi
