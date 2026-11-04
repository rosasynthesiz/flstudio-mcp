# Bridge correctness regressions

These fixes cover three failures observed with Windows and FL Studio Producer
26.1.6 build 5639. The MIDI wire version remains 2.

## Signed zero in JSON responses

FL's default mixer fader can return approximately `0.7999999523` for normalized
unity (`0.8`). Converting that value to dB and rounding to two decimal places
produces `-0.0`. Python JSON preserves the sign, whereas JavaScript JSON
serialization converts negative zero to `0`; clients that require lossless
numbers can reject the entire mixer or snapshot result.

The controller canonicalizes zero in volume/pan fields and outgoing nested data.
The shared protocol encoder and daemon TCP serializer also normalize zero, so
the daemon can serve a controller that has not been reloaded yet. Real negative
values such as `-0.04` and text containing `-0.0` are preserved. NaN and infinity
are rejected rather than silently converted into missing data. An invalid daemon
reply reports `invalid_result` without replaying the command: a write may already
have taken effect, so inspect the state before retrying.

## Dry-run before mutation

`fl_set_dry_run(true)` now covers tempo, playhead position, play/stop/toggle/record,
pattern creation/cloning/markers, channel selection, Piano Roll note writing,
quantization, raga note writing, and rollback. Preview branches run before the
FL command, generated-script operation, or undo-log consumption. They return
`{"ok": true, "dry_run": true, "planned": ...}`. Reads remain available.

Dry-run is local to the MCP server process. Set the flag and invoke the tool on
the same server connection. Reconnecting starts with dry-run off. After updating
the source, restart the daemon and reconnect every existing MCP client to load
the updated code; a server started before the update retains its old functions.

## Known Windows Emphasizer parameter names

On the tested localized Windows build, `plugins.getParamName` returned four
Emphasizer labels as UTF-8 Chinese names decoded as GBK. Parameter-list,
single-parameter and setter echoes use the same exact mapping for those four
verified labels, limited to Emphasizer on Windows. Unknown names, other plugins,
other platforms, track names and display strings retain their original text.

A generic encoding round-trip is insufficient to detect corruption: valid
short names such as `湿` and `L路` also decode successfully into different text.
Regression tests explicitly preserve those names.

## Validation

Run the offline suite with Python 3.12 and the development dependencies:

```text
python -m pytest tests -q
```

The suite exercises controller handlers with substitute FL API modules, both
MIDI encoders, a real local daemon TCP request, and registered FastMCP tools.
It verifies signed-zero normalization, preservation of nonzero values, strict
non-finite rejection, absence of command replay, dry-run dispatch prevention,
undo-log preservation, and localized parameter-name consistency.

Live checks in the reported Windows/FL build covered all 18 mixer tracks,
Master and individual-track/channel snapshots, readable localized Emphasizer
parameter names, and a name-based parameter-set preview. A tempo preview left
the project at 130 BPM. A same-value mixer-pan write preserved the value and
persisted its changelog entry. Additional transport/arrangement/note dry-runs
were checked through a read-only verification proxy: every command returned a
plan and attempted no write to FL.

These checks do not establish that automatic Piano Roll channel targeting or
the separately reported UI hang is resolved. The non-preview note-trigger path
is outside this patch's validation scope.
