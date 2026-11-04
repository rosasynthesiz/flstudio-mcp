"""Keep the contributor's generated-script assertions in the CI test suite."""
import os
from pathlib import Path
import subprocess
import sys


def test_porta_generated_script():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'scripts/test_porta.py')],
                            cwd=root, capture_output=True, text=True,
                            env=dict(os.environ, PYTHONIOENCODING='utf-8'), timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '5 passed, 0 failed' in result.stdout
