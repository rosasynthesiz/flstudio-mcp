#!/usr/bin/env python3
"""
Installs the Anti-Vibe Coding Audit script into the git pre-commit hook.
It safely appends to the hook if it exists, or creates a new one.
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
HOOK_PATH = ROOT_DIR / ".git" / "hooks" / "pre-commit"

HOOK_CONTENT = """
# --- Anti-Vibe Coding Hook ---
echo "Running Anti-Vibe Coding Audits..."
.venv/bin/python scripts/audit_anti_vibe.py
if [ $? -ne 0 ]; then
    echo "Commit blocked by Vibe Coding Audit. Please fix the issues above."
    exit 1
fi
# -----------------------------
"""


def install_hook():
    if not (ROOT_DIR / ".git").exists():
        print("Error: .git directory not found. Are you at the repository root?")
        return

    # Check if we already appended our hook
    if HOOK_PATH.exists():
        with open(HOOK_PATH, encoding="utf-8") as f:
            content = f.read()
            if "Anti-Vibe Coding Hook" in content:
                print("Anti-Vibe Coding hook is already installed.")
                return

        print("Appending to existing pre-commit hook...")
        mode = "a"
    else:
        print("Creating new pre-commit hook...")
        mode = "w"
        # Start with shebang if creating new
        HOOK_CONTENT_FINAL = "#!/bin/sh\n" + HOOK_CONTENT

    with open(HOOK_PATH, mode, encoding="utf-8") as f:
        if mode == "a":
            f.write("\n" + HOOK_CONTENT)
        else:
            f.write(HOOK_CONTENT_FINAL)

    # Ensure it's executable
    os.chmod(HOOK_PATH, 0o755)
    print("Successfully installed Anti-Vibe Coding pre-commit hook!")


if __name__ == "__main__":
    install_hook()
