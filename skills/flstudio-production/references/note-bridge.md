# Piano roll note bridge — how writes really work

The MCP server cannot read notes back. Every note write is blind: the server
generates `MCP_Apply.pyscript` in FL's `Settings/Piano roll scripts/` folder,
overwrites it, and then presses FL's "Run last script again" hotkey. FL re-reads
the file on every trigger. Knowing this explains almost every weird symptom.

Paths (macOS):

```
~/Documents/Image-Line/FL Studio/Settings/Piano roll scripts/MCP_Apply.pyscript
```

## Hard rules

1. **Arm once per FL session.** Open the Piano roll → Scripting menu →
   `MCP Apply` once manually (this makes "Run last script again" target it).
   The server cannot do it.
2. **The write lands in the channel the Piano roll is OPEN on**, whatever
   `channel=` you pass. See "Channel targeting".
3. **Never `mode="replace"` on an unconfirmed target.** Replace clears that
   channel's notes in the current pattern.
4. **Do not hand-edit the generated script's scaling.** It is correct (below).
5. **Verify by the script, not by the tool's echo.** The JSON echo of big
   `notes` arrays is truncated/garbled in the UI. `grep -n '^NOTES' MCP_Apply.pyscript`
   on disk is the ground truth of what will be written.

## Time scaling (the one that burned a whole session)

The generated script does:

```python
bar = score.PPQ * 4          # ticks per bar in 4/4
n.time = int(round(t_bars * bar))
n.length = max(1, int(round(len_bars * bar)))
```

FL 26.1.7: `score.PPQ == 96` = **pulses per QUARTER note** (ticks per bar = 384).
So `time_bars` maps 1:1 to FL bars only with the `* 4`. The quantize template
uses `GRID_BARS * score.PPQ * 4` for the same reason.

**Do not "fix" this to `score.PPQ`.** Doing so divides every position by 4 and
silently squeezes the whole phrase into bar 1 (symptom: "all notes except drums
are crammed into the first bar"; clips look 3/4 empty).

### How to verify the scale in 60 seconds

1. `fl_arrange_new_pattern("TEST_SCALE_IGNORE")` (patterns cannot be deleted, so
   name test patterns obviously and clear their notes afterwards).
2. Write ONE note at `time_bars=4`.
3. Screenshot the piano roll with the bar ruler visible (`fl_screenshot` with
   `region`) and check the note sits on bar line **5**.
   If it sits on bar **1**, the scale is ÷4. If on **~17**, it is ×4.

Do not use pattern length as the check: `clearNotes` does not shrink a pattern,
FL rounds lengths up (observed: note ending at 4.25 bars → 8 bars; at 8.125 →
12 bars), so the length hides the answer.

## Triggering the script (macOS)

`System Events` `keystroke "y"` resolves the letter through the current keyboard
layout. Under a non-Latin layout (Russian, Greek, …) FL never receives
Cmd+Opt+Y. Use the virtual key code instead (VK 0x10 = 16 is `Y` on macOS):

```bash
osascript \
  -e 'tell application id "com.image-line.flstudio" to activate' \
  -e 'delay 0.4' \
  -e 'tell application "System Events" to key code 16 using {command down, option down}'
```

`src/fl_studio_mcp/pyscript_trigger.py::_trigger_macos` still uses
`keystroke "y"` — if the automatic trigger never lands, this is why. The Windows
path already avoids the problem by sending `VK_Y` directly.

Also: **synthetic clicks do not work.** `System Events ... click at {x, y}`
does not register in FL (it is not a real HID event). Verify that empirically
before building any click-based automation; only key codes get through.

## Channel targeting

`fl_arrange_select_channel` calls `channels.selectOneChannel`, but the Piano
roll re-syncs to its own channel, so:

- the returned `selected` echoes the **Piano roll's** channel, not your request;
- the Piano roll often does not retarget (`piano_roll_retargeted: true` can lie);
- pattern switching does **not** retarget the Piano roll either.

Working loop (fewest user actions):

1. Ask the user to click the channel row in the Channel Rack (a physical click).
2. Confirm with a screenshot: the title must read `Piano roll - <channel name>`.
3. Write **all patterns** for that channel before changing channels
   (`fl_pattern_select` + write + trigger, repeated).
4. Ask for the next channel.

Never write with `replace` while the title shows a different channel than you
intend — that is how a session wipes the melody the user just recorded.

## Large deterministic batches

For big writes (hundreds of notes, several chords × bars) generate the script
yourself instead of passing a huge JSON array through a tool call:

```bash
python3 - <<'EOF'
TPL = '''# Script.Name = "MCP Apply"
# Script.Category = "MCP"
import flpianoroll as flp
MODE = 'replace'
NOTES = %r


def _run():
    score = flp.score
    bar = score.PPQ * 4
    try:
        score.clearNotes(True)
    except TypeError:
        score.clearNotes()
    for pitch, t_bars, len_bars, vel in NOTES:
        n = flp.Note()
        n.number = int(pitch)
        n.time = int(round(t_bars * bar))
        n.length = max(1, int(round(len_bars * bar)))
        n.velocity = float(vel)
        score.addNote(n)


_run()
'''
notes = [(60, 0.0, 0.25, 0.78), (67, 1.0, 0.25, 0.78)]
open('/tmp/batch.pyscript', 'w').write(TPL % (notes,))
EOF
cp /tmp/batch.pyscript "$HOME/Documents/Image-Line/FL Studio/Settings/Piano roll scripts/MCP_Apply.pyscript"
# then the osascript trigger above
```

Then verify visually (bar ruler) before mass-writing the other channels.

## Replace vs append, and undo

- `mode="replace"` clears the target channel's notes in the pattern, then
  writes; `mode="append"` adds. Use `append` for a single probe note.
- `fl_rollback_last_change` covers API-level writes (mixer, routing, names,
  tempo). It does **not** undo pyscript note writes — those rely on FL's own
  undo stack (Cmd/Ctrl+Z in FL).
