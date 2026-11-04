#!/usr/bin/env bash
# Source installer: stages an isolated runtime; never uses system pip.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Install Python 3.10+ and re-run. No installed files were changed."
  exit 1
fi
exec python3 "$SCRIPT_DIR/install.py" "$@"
