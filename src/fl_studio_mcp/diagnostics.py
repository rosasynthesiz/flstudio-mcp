"""Read-only installation and connection diagnostics; never sends DAW mutations."""
from __future__ import annotations

import argparse
import json

from .connection import TCPBridge, list_ports
from .paths import fl_settings_dir


def diagnose(*, live=False):
    settings = fl_settings_dir()
    report = {'settings': str(settings), 'files': {
        'controller': (settings / 'Hardware/FLStudioMCP/device_FLStudioMCP.py').is_file(),
        'note_script': (settings / 'Piano roll scripts/MCP_Apply.pyscript').is_file()},
        'manual_checks': ['FL MIDI RX input enabled with FLStudioMCP controller; TX output same port number',
                          'Run MCP_Apply once per session; confirm disposable target before note writes',
                          'macOS: Accessibility permission for the process sending note hotkeys'],
        'live_tested': False}
    try:
        ports = list_ports()
        report['midi_ports'] = ports
        report['missing_ports'] = [name for name, direction in (
            ('FLStudioMCP RX', 'outputs'), ('FLStudioMCP TX', 'inputs'))
            if not any(name.lower() in port.lower() for port in ports[direction])]
    except Exception as error:
        report['midi_error'] = str(error)
    if live:
        bridge = TCPBridge()
        try:
            state = bridge.call('get_project_state', {})
            report['project'] = state
            report['project_guard_ready'] = bool(state.get('project_token')) and state.get('project_loading') is False
            report['live_tested'] = True
        except Exception as error:
            report['connection_error'] = str(error)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Read current project through the local daemon')
    args = parser.parse_args()
    print(json.dumps(diagnose(live=args.live), indent=2))


if __name__ == '__main__':
    main()
