# Architecture

> **Version 2 notes** (the rest of this page describes the transport, which is unchanged):
> - On macOS and Linux the server creates the two MIDI ports itself, both named
>   `FLStudioMCP`. The controller script lists that name under
>   `supportedDevices`, so FL links the script, pairs input and output on one
>   Port number and enables both without any step in MIDI Settings. Windows
>   still uses two loopMIDI ports, `FLStudioMCP RX` and `FLStudioMCP TX`.
> - The first MCP server to start owns the MIDI ports and serves the same
>   line protocol as the daemon on `127.0.0.1:9787`; later servers join it,
>   and one of them takes over if the owner exits.
> - The controller reports a project token (controller session + a counter
>   that moves on every project load). Writes and undo carry it, and the
>   controller refuses a command whose token is stale.
> - `fl_ping` now returns a `status` code and a `next` step; see
>   `setup_cli.STATUS_HELP`.

## Why MIDI, not files

FL Studio runs controller scripts in a sandboxed Python interpreter. The
sandbox is real -- it blocks any operation that could touch the filesystem,
network, or subprocesses. v0.1 of this MCP assumed a JSON file queue would
work because FL's docs say "_io" and "json" are in the built-in module
list. They are -- but the parts that read are exposed, the parts that
write are not.

Concrete error trace on FL 24+ MIDI scripting v40, embedded Python 3.12.1:

```
>>> open("C:/Users/.../x.txt", "w").write("hi")
SystemError: <class '_io.FileIO'> returned NULL without setting an exception

>>> import os
>>> os.open("C:/.../x.txt", os.O_WRONLY|os.O_CREAT|os.O_TRUNC)
TypeError: bad argument type for built-in operation

>>> os.makedirs("C:/temp/test")
SystemError: mkdir returned NULL without setting an exception
```

The same process (FL Studio itself) writes to those paths fine. The block
is at the controller-script sandbox layer.

Piano Roll `.pyscript`s run in a different (more permissive) sandbox where
file I/O does work, but those only execute on user trigger -- you can't run
a `.pyscript` continuously in the background. The controller script is the
only "always on" hook FL gives third-party code.

So the only viable bidirectional channel between an external process and a
controller script is **MIDI**. SysEx supports arbitrary-length payloads, so
we can carry JSON-shaped commands and responses.

## Layers

```
Claude / Cursor
    |  stdio
    v
fl-studio-mcp (Python, our code)
    |  mido + python-rtmidi
    |
    |  out: SysEx "FLStudioMCP RX" port
    |  in:  SysEx "FLStudioMCP TX" port
    v
loopMIDI (Windows) / IAC Driver (macOS) -- virtual MIDI loopback
    |
    v
FL Studio MIDI engine
    |  routes by Port number
    v
device_FLStudioMCP.py
    OnMidiMsg() receives requests
    device.midiOutSysex() emits responses
    transport / mixer / channels / patterns / plugins API calls
```

## Wire format

Between F0 (start of SysEx) and F7 (end of SysEx), the message body is:

```
[0]      0x7D                    Manufacturer ID (MIDI-spec private use)
[1..3]   "MCP" (0x4D 0x43 0x50)  Magic, lets us ignore unrelated SysEx
[4]      direction               0x01 request, 0x02 response, 0x03 heartbeat
[5..12]  8 ASCII chars [a-z0-9]  Request id, correlates response to request
[13..]   base64-encoded UTF-8 JSON payload
```

Why base64 and not 7-to-8 bit packing: base64 chars are all in [A-Za-z0-9+/=]
and thus all < 128, so they slot into SysEx data bytes (which must be < 128)
without further encoding. The 33% size overhead is fine -- our payloads are
tiny (10 bytes to a few hundred). If we ever need to ship larger blobs
(audio samples, presets), we'll switch to 7-to-8 packing and bump protocol
version.

## Response correlation

The MCP server is multithreaded by accident: `mido.open_input(callback=...)`
spawns a background thread that calls the callback with each incoming
message. The main thread, calling tools, blocks on a `threading.Event`
keyed by request id. The callback wakes the event.

```python
slot = _Slot()                # threading.Event + payload slot
self._pending[request_id] = slot
self._out_port.send(msg)
if not slot.event.wait(timeout):
    raise FLTimeout(...)
return slot.payload["data"]
```

Stale responses (callback arrives after a timeout cleared the slot) are
silently dropped.

## Heartbeat

FL emits a `DIR_HEARTBEAT` SysEx every 500 ms from `OnIdle`. The server
tracks `_last_heartbeat = time.monotonic()` whenever a heartbeat callback
fires. `is_alive()` is true if `now - _last_heartbeat <= 3.0s`. This lets
`fl_ping` distinguish four states:

| State | What `fl_ping` returns |
|-------|------------------------|
| FL not running / wrong port config | `alive: false, reason: "No heartbeat received..."` |
| FL crashed / froze after running once | `alive: false, reason: "Heartbeat is N.Ns old..."` |
| Healthy | `alive: true, heartbeat_age_seconds: 0.x, fl_version: ...` |

## Port routing inside FL

FL Studio's MIDI scripting routes script output via Port numbers, not
device names. Every MIDI device (Input AND Output) in `Options -> MIDI
Settings` gets a Port number you can set. When a controller script (assigned
to some input device) calls `device.midiOutSysex(msg)`, FL sends the bytes
to the OUTPUT device that has the SAME Port number as the script's input
device.

So the setup is:
- `FLStudioMCP RX` is an Input device with Controller type FLStudioMCP and
  Port = 42.
- `FLStudioMCP TX` is an Output device with Port = 42.

The numbers must match. We picked 42 in the docs; any number 0-255 works as
long as both sides use it.

## Why not Web/HTTP?

Same sandbox. `socket` is not in the built-in module list, `urllib` chokes
without `socket`, and even if either worked it would expand the attack
surface of FL Studio installs we don't control. MIDI is the boundary
Image-Line trusts; we work inside it.
