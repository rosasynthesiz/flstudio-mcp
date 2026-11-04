"""Source installer with isolated immutable runtimes and journaled file deployment.

No project, MIDI configuration, or AI client configuration is edited here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import venv


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.flmcp-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def preflight(root: Path, settings: Path):
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10+ required')
    if not (root / 'pyproject.toml').is_file():
        raise RuntimeError('Run from a complete source checkout')
    if not (settings / 'Hardware').is_dir():
        raise RuntimeError(f'FL Settings/Hardware missing: {settings}; open FL once or set FL_SETTINGS')
    # Refuse redirected targets; resolve custom absolute folders explicitly instead.
    for folder in (settings, settings / 'Hardware', settings / 'Hardware/FLStudioMCP',
                   settings / 'Piano roll scripts'):
        for parent in (folder, *folder.parents):
            if parent.exists() and (parent.is_symlink() or
                    getattr(parent.stat(follow_symlinks=False), 'st_file_attributes', 0) & 0x400):
                raise RuntimeError(f'Redirected install path refused: {parent}')
    if sys.platform == 'win32':
        output = subprocess.check_output(['tasklist', '/FO', 'CSV', '/NH'], text=True).lower()
        names = ('fl64.exe', 'fl.exe', 'fl-studio-mcp.exe', 'fl-studio-mcp-daemon.exe')
        if any(f'"{name}"' in output for name in names):
            raise RuntimeError('FL Studio, daemon or MCP server is running; close them before installation')
    elif sys.platform == 'darwin':
        result = subprocess.run(['pgrep', '-f', r'FL Studio.app/Contents/MacOS|fl-studio-mcp'],
                                capture_output=True, text=True)
        if result.returncode == 0:
            raise RuntimeError('FL Studio, daemon or MCP server is running; close them before installation')
        if result.returncode != 1:
            raise RuntimeError('Could not check running applications')


def deploy(files: dict[Path, bytes], backup: Path):
    """Durable originals before any replacement; rollback all attempted files on failure."""
    backup.mkdir(parents=True, exist_ok=False)
    records = []
    for i, (path, data) in enumerate(files.items()):
        if path.is_symlink():
            raise RuntimeError(f'Symlink target refused: {path}')
        original = path.read_bytes() if path.exists() else None
        if original is not None:
            atomic_write(backup / str(i), original)
        records.append({'path': str(path), 'original': str(i) if original is not None else None})
    atomic_write(backup / 'manifest.json', json.dumps(records, indent=2).encode())
    attempted = []
    try:
        for record, (path, data) in zip(records, files.items()):
            attempted.append((record, path, data))
            atomic_write(path, data)
    except Exception as error:
        failures = []
        for record, path, data in reversed(attempted):
            try:
                if record['original'] is None:
                    if path.exists():
                        if path.read_bytes() != data:
                            raise RuntimeError('file changed during failed install; manual recovery required')
                        path.unlink()
                else:
                    atomic_write(path, (backup / record['original']).read_bytes())
            except Exception as recovery_error:
                failures.append(f'{path}: {recovery_error}')
        raise RuntimeError(f'Install failed: {error}; backups: {backup}; recovery errors: {failures}') from error


def install(root: Path, settings: Path, extras: str = 'none'):
    preflight(root, settings)
    choices = set(extras.replace(',', ' ').split())
    if choices - {'none', 'all', 'audio', 'accurate', 'chords'}:
        raise ValueError('FLMCP_EXTRAS must be none, all, or audio accurate chords')
    if 'all' in choices:
        choices = {'audio', 'accurate', 'chords'}
    selected = []
    if choices & {'audio', 'accurate'}:
        selected.append('audio')
    if 'accurate' in choices:
        selected.append('audio-accurate')
    if 'chords' in choices:
        selected.append('audio-chords')
    lock = root / '.flmcp-install.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    try:
        runtime = root / '.runtimes' / uuid.uuid4().hex
        print(f'Staging isolated runtime: {runtime}', flush=True)
        venv.EnvBuilder(with_pip=True).create(runtime)
        bin_dir = runtime / ('Scripts' if os.name == 'nt' else 'bin')
        python = bin_dir / ('python.exe' if os.name == 'nt' else 'python')
        package = str(root) + ('[' + ','.join(selected) + ']' if selected else '')
        subprocess.run([str(python), '-m', 'pip', 'install', package], check=True)
        if 'chords' in choices:
            subprocess.run([str(python), '-m', 'pip', 'install', '--no-deps', 'basic-pitch==0.4.0'], check=True)
        env = dict(os.environ, FL_SETTINGS=str(settings), FLSTUDIO_MCP_TRANSPORT='tcp')
        # No port creation, daemon launch, hotkey, or FL access during runtime validation.
        subprocess.run([str(python), '-c', 'import rtmidi; from fl_studio_mcp.server import build_server; build_server()'],
                       check=True, env=env, cwd=runtime)
        subprocess.run([str(python), '-m', 'fl_studio_mcp.diagnostics'], check=True, env=env, cwd=runtime)
        seed = subprocess.check_output([str(python), '-c',
            'from fl_studio_mcp.pyscript_gen import render_apply_script; print(render_apply_script([], "append"), end="")'],
            env=dict(env, PYTHONIOENCODING='utf-8'), cwd=runtime)
        preflight(root, settings)  # refuse if FL opened during dependency installation
        suffix = '.exe' if os.name == 'nt' else ''
        manifest = {'python': str(python), 'settings': str(settings),
                    'server': str(bin_dir / ('fl-studio-mcp' + suffix)),
                    'daemon': str(bin_dir / ('fl-studio-mcp-daemon' + suffix))}
        files = {
            settings / 'Hardware/FLStudioMCP/device_FLStudioMCP.py':
                (root / 'fl_controller/FLStudioMCP/device_FLStudioMCP.py').read_bytes(),
            settings / 'Piano roll scripts/MCP_Apply.pyscript': seed,
            root / '.flmcp-runtime.json': json.dumps(manifest, indent=2).encode(),
        }
        backup = root / '.install-backups' / uuid.uuid4().hex
        deploy(files, backup)
        print(f'Installed; originals and restore manifest: {backup}')
        print('Existing .venv, AI client settings, MIDI settings and projects were preserved.')
        print('Keep the source folder and runtime in place. Configure your AI client using:')
        print(json.dumps({'command': manifest['server'], 'env': {
            'FLSTUDIO_MCP_TRANSPORT': 'tcp', 'FL_SETTINGS': str(settings)}}, indent=2))
        print('Daemon command:', manifest['daemon'])
        print('Set up named RX/TX MIDI ports, then configure FL MIDI and arm MCP_Apply once per session.')
        print('Optional audio features: ' + (', '.join(selected) or 'none'))
        print('No live connection test was performed. See docs/SAFE_INSTALL.md for checks and recovery.')
        return manifest
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--settings', type=Path)
    args = parser.parse_args()
    # Import only the stdlib-only path resolver, before any dependency install.
    sys.path.insert(0, str(args.root / 'src'))
    from fl_studio_mcp.paths import fl_settings_dir
    settings = args.settings or fl_settings_dir()
    if not settings.is_absolute():
        parser.error('FL_SETTINGS / --settings must be an absolute path')
    install(args.root.resolve(), settings.absolute(), os.environ.get('FLMCP_EXTRAS', 'none'))


if __name__ == '__main__':
    main()
