# Arrangement: phrases, drum grid, playlist clips

## The one alignment rule

A pattern's musical content must be the same length as the drum step grid,
because that is what the user will see in a playlist clip.

- Read the grid before assuming: `fl_get_step_grid(channel, length=64)`.
  A 16-step grid = 1 bar; a 64-step grid = 4 bars of 16ths
  (`x...x...` repeated 16× is still a 4-bar grid).
- Write melodic parts (chords/bass/motif) across that same span
  (e.g. 4 bars: chord stabs at 0.125/0.375/0.625/0.875 per bar).
- Playlist clips **cannot be created by the API**. Tell the user the exact clip
  length to drag (the phrase length), not "the pattern length": FL sizes a
  dragged clip to the whole pattern, which may be far longer than the phrase.

Symptom to recognise: "in the clip the notes occupy 1/4 and the rest is drums"
→ usually the phrase is one bar while the drum grid is four (or the ÷4 scaling
bug in `note-bridge.md`). Do not start resizing clips until the phrase length is
verified against the grid.

## Patterns cannot be created or deleted arbitrarily

- `fl_arrange_new_pattern` only names + selects the next **empty** pattern; the
  count never shrinks. Test patterns stay forever — name them
  `TEST_..._IGNORE` and clear their notes.
- Patterns can be cloned (`fl_arrange_clone_pattern`) but not deleted.
- `fl_set_song_position` does nothing while FL is in PAT mode (transport stays
  in the pattern); it is only meaningful in song mode.

## Using a user's recorded MIDI as the motif

The bridge is one-way, so get the source of truth from the exported file:

- Ask the user to export the channel: Piano roll → Scripting/File → "Export as
  MIDI" (or File → Export → MIDI), then parse the `.mid` with plain Python
  (system python3 usually has no `mido`; a 40-line VLQ parser is enough).
- Convert: `bar = 1 + tick / (ppq * beats_per_bar)`; a note at 1.021 in a MIDI
  file means "just after bar 1" in FL's 1-based ruler.
- Quantize deliberately: report the snapped grid to the user and keep the
  original `.mid` as the backup before `replace`-ing the live take.
- Template for a 1/8-grid motif derived from a live take: notes at 0, .25, .5,
  .625, .75, .875 of the bar with the last one longer.
- When the user says "use my MIDI as a sample": clarify that it is MIDI (plays
  through the channel's instrument). FL's scripting API cannot render audio or
  load audio samples — bouncing is manual.

## Sectioning

Markers are free (`fl_arrange_add_marker`) and read back with
`fl_arrangement_markers`. Agree on section lengths first (e.g. Intro 16 /
Groove 16 / Hook 32 / Main 32), then produce per-section pattern variants
rhythmically, not just dynamically:

- quietest section: half the stabs, lower velocity, no bass, no motif;
- groove section: root-only bass with an extra 16th, 4 stabs per bar;
- hook: full stabs + motif + bass with fifths;
- keep one channel (e.g. the lead) identical across sections so the motif
  recurs; vary the others.

## Channels vs mixer tracks

`fl_get_channel_routing` shows channel → mixer track. There is **no tool to
change that routing** (`fl_set_route` edits mixer→mixer sends only). If the
routing is wrong, say so and let the user set it in the Channel Rack settings
rather than pretending a route change worked.
