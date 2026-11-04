"""Fault-injected installer tests in temporary folders; no real FL or pip."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_deploy_backups_preserve_unknown_files(tmp_path):
    target = tmp_path / 'settings/controller.py'
    target.parent.mkdir()
    target.write_bytes(b'old controller')
    unknown = target.parent / 'custom.py'
    unknown.write_bytes(b'user content')
    backup = tmp_path / 'backup'
    installer.deploy({target: b'new controller'}, backup)
    assert target.read_bytes() == b'new controller'
    assert (backup / '0').read_bytes() == b'old controller'
    assert unknown.read_bytes() == b'user content'
    assert json.loads((backup / 'manifest.json').read_text())[0]['path'] == str(target)


def test_partial_deployment_restores_existing_and_removes_new_file(tmp_path, monkeypatch):
    old, new, manifest = [tmp_path / name for name in ('old.py', 'new.pyscript', 'runtime.json')]
    old.write_bytes(b'old controller')
    original = installer.atomic_write
    def write(path, data):
        if path == manifest:
            raise OSError('injected final activation failure')
        original(path, data)
    monkeypatch.setattr(installer, 'atomic_write', write)
    with pytest.raises(RuntimeError, match='Install failed'):
        installer.deploy({old: b'changed', new: b'seed', manifest: b'{}'}, tmp_path / 'backup')
    assert old.read_bytes() == b'old controller'
    assert not new.exists() and not manifest.exists()


def test_dependency_failure_leaves_installation_unchanged(tmp_path, monkeypatch):
    root, settings = tmp_path / 'repo', tmp_path / 'custom FL/Settings'
    root.mkdir()
    controller = settings / 'Hardware/FLStudioMCP/device_FLStudioMCP.py'
    controller.parent.mkdir(parents=True)
    controller.write_bytes(b'old controller')
    monkeypatch.setattr(installer, 'preflight', lambda *_: None)
    monkeypatch.setattr(installer.venv.EnvBuilder, 'create', lambda *_: None)
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(installer.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        installer.install(root, settings)
    assert controller.read_bytes() == b'old controller'
    assert not (root / '.flmcp-runtime.json').exists()
    assert not (root / '.flmcp-install.lock').exists()


def test_missing_hardware_refuses_before_runtime_creation(tmp_path):
    (tmp_path / 'pyproject.toml').touch()
    with pytest.raises(RuntimeError, match='Hardware missing'):
        installer.install(tmp_path, tmp_path / 'missing Settings')
    assert not (tmp_path / '.runtimes').exists()


def test_concurrent_installer_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, 'preflight', lambda *_: None)
    lock = tmp_path / '.flmcp-install.lock'
    lock.write_text('existing installer')
    with pytest.raises(FileExistsError):
        installer.install(tmp_path, tmp_path)
    assert lock.read_text() == 'existing installer'


def test_custom_path_propagates_to_runtime_validation_and_config(tmp_path, monkeypatch):
    root = tmp_path / 'repo with spaces'
    settings = tmp_path / 'custom FL/Settings'
    (root / 'fl_controller/FLStudioMCP').mkdir(parents=True)
    (root / 'fl_controller/FLStudioMCP/device_FLStudioMCP.py').write_bytes(b'controller')
    monkeypatch.setattr(installer, 'preflight', lambda *_: None)
    monkeypatch.setattr(installer.venv.EnvBuilder, 'create', lambda *_: None)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(installer.subprocess, 'run', run)
    monkeypatch.setattr(installer.subprocess, 'check_output', lambda *a, **k: b'seed script')
    result = installer.install(root, settings)
    assert result['settings'] == str(settings)
    assert (settings / 'Piano roll scripts/MCP_Apply.pyscript').read_bytes() == b'seed script'
    assert result['python'].startswith(str(root / '.runtimes'))
    assert all(k['env']['FL_SETTINGS'] == str(settings) for a, k in calls if 'env' in k)
    assert not (root / '.venv').exists()
