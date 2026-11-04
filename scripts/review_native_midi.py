"""Native backend probe for held PR11. Unique test ports; never controls FL."""
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

if sys.platform == 'linux' and not Path('/dev/snd/seq').exists():
    print(json.dumps({'status': 'blocked', 'reason': 'ALSA /dev/snd/seq is absent; no native sequencer backend'}))
    raise SystemExit(77)
if sys.platform not in ('darwin', 'linux'):
    print('Native CoreMIDI/ALSA host required')
    raise SystemExit(77)

os.environ['FLSTUDIO_MCP_VIRTUAL_PORTS'] = '1'
from fl_studio_mcp import connection, protocol
import mido


def wait_for(predicate, message):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError(message)


def find(names, pattern):
    hits = [name for name in names if pattern in name]
    assert len(hits) == 1, (pattern, hits)
    return hits[0]


results = []
for cycle in range(3):
    tag = 'FLMCP_REVIEW_' + uuid.uuid4().hex[:10]
    rx, tx = tag + '_RX', tag + '_TX'
    bridge = connection.FLBridge(rx, tx, default_timeout=5)
    peer_in = peer_out = None
    errors = []
    try:
        bridge.open()
        assert bridge._virtual
        wait_for(lambda: any(rx in n for n in mido.get_input_names())
                 and any(tx in n for n in mido.get_output_names()), 'Ports not discoverable')
        peer_in = mido.open_input(find(mido.get_input_names(), rx))
        peer_out = mido.open_output(find(mido.get_output_names(), tx))

        def respond():
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    message = peer_in.poll()
                    if message is None:
                        time.sleep(.01)
                        continue
                    decoded = protocol.decode_message(message.data)
                    assert decoded and decoded[0] == protocol.DIR_REQUEST
                    _, rid, payload = decoded
                    assert payload['cmd'] == 'review_native_echo'
                    data = protocol.encode_message(protocol.DIR_RESPONSE, rid,
                        protocol.make_response_ok({'native_echo': payload['params']}))
                    peer_out.send(mido.Message('sysex', data=list(data)))
                    return
                raise AssertionError('No native SysEx request arrived')
            except BaseException as error:
                errors.append(repr(error))

        worker = threading.Thread(target=respond, daemon=True)
        worker.start()
        reply = bridge.call('review_native_echo', {'cycle': cycle})
        worker.join(6)
        assert not worker.is_alive() and not errors, errors
        assert reply == {'native_echo': {'cycle': cycle}}, reply
        duplicate = connection.FLBridge(rx, tx)
        try:
            try:
                duplicate.open()
            except connection.FLPortMissing:
                pass
            else:
                assert not duplicate._virtual, 'Duplicate virtual creation was allowed'
        finally:
            duplicate.close()
        results.append({'cycle': cycle, 'discovered': True, 'sysex_roundtrip': True,
                        'duplicate_prevented': True})
    finally:
        if peer_in:
            peer_in.close()
        if peer_out:
            peer_out.close()
        bridge.close()
        bridge.close()
    wait_for(lambda: not any(tag in n for n in mido.get_input_names() + mido.get_output_names()),
             'Virtual test ports remained after close')
    results[-1]['cleanup'] = True
print(json.dumps({'status': 'passed', 'platform': sys.platform, 'cycles': results}, indent=2))
