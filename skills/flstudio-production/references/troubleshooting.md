# Troubleshooting: symptom → cause → fix

| Symptom | Cause | Fix |
|---|---|---|
| Notes never appear after a write | Script was never armed this FL session | Open Piano roll → Scripting → `MCP Apply` once |
| Notes appear on the wrong channel | Writes go to the channel the Piano roll is **open** on; `selectOneChannel` does not retarget it | Ask the user to click the channel row; confirm the `Piano roll - <name>` title in a screenshot |
| The melody the user recorded vanished | A `mode="replace"` write hit that channel | Restore from the exported `.mid`, or FL undo |
| All notes crammed into bar 1 | Position scaling divided by 4 (someone "fixed" `score.PPQ * 4` → `score.PPQ`) | Restore `* 4`, rewrite, verify against the bar ruler |
| Everything lands ×4 too far | Inverse of the above | Same |
| `fl_arrange_select_channel` reports `selected: 6` for channel 4 | `selected` echoes the Piano roll's channel | Ignore the field; trust the window title |
| Hotkey never triggers (macOS, non-Latin layout) | `keystroke "y"` resolves through the layout | `key code 16 using {command down, option down}` |
| Synthetic clicks do nothing in FL | `System Events click at` is not a real HID event | Don't automate clicks; ask the user or use key codes |
| Pattern length contradicts the notes | `clearNotes`/shortening doesn't shrink; FL rounds up to multiples of 4 bars | Verify positions on the ruler, not by length |
| `PAT` mode: `fl_set_song_position` ignored | Transport is in pattern mode | Switch FL to song mode (user) |
| Bass/lead silent though notes exist | Channel→mixer routing or the instrument's own volume | `fl_get_channel_routing`, `fl_get_channel_state`; routing cannot be set by API |
| `FL_BUSY` on every write | A dialog is open (welcome screen counts) | Ask the user to close it |
| Take/clip sounds like only its first bar | Clip is shorter than the phrase, or the phrase is shorter than the drum grid | Align phrase = grid = clip length (see `arrangement.md`) |
| `fl_screenshot` region misses what you expect | `region` is in logical points; the PNG is 2× on Retina | Convert: `logical = px / (png_width / screen_width)` |

## Cheap diagnostic order

1. `fl_ping` (status + `next`).
2. `fl_capabilities` (what this install can automate on this OS).
3. `fl_pattern_list` + `fl_get_project_state` (where am I: pattern vs song).
4. For note content: screenshot with the Piano roll title + bar ruler visible —
   the title gives the channel, the ruler gives the timing. One screenshot
   answers both.
