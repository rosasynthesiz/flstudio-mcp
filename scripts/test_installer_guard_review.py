"""Simulate a running daemon; installer must refuse before copying controller."""
import os
from pathlib import Path
import subprocess
import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows batch installer guard')


@pytest.mark.parametrize('process', ['fl-studio-mcp-daemon.exe', 'fl-studio-mcp.exe'])
def test_lock_guard_precedes_controller_copy(tmp_path, process):
    root = Path(os.environ.get('INSTALLER_ROOT', Path(__file__).resolve().parents[1]))
    settings = tmp_path / 'Settings'
    controller = settings / 'Hardware/FLStudioMCP/device_FLStudioMCP.py'
    controller.parent.mkdir(parents=True)
    controller.write_text('# existing controller sentinel', encoding='utf-8')
    fakebin = tmp_path / 'bin'
    fakebin.mkdir()
    (fakebin / 'tasklist.cmd').write_text('@echo ' + process + '\n', encoding='ascii')
    env = dict(os.environ, FL_SETTINGS=str(settings), FLMCP_EXTRAS='none',
               PATH=str(fakebin) + os.pathsep + os.environ['PATH'])
    result = subprocess.run(['cmd', '/d', '/c', str(root / 'scripts/install_windows.bat')],
                            cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert ('daemon is running' if 'daemon' in process else 'mcp server is running') in result.stdout.lower(), result.stdout
    assert controller.read_text(encoding='utf-8') == '# existing controller sentinel'
