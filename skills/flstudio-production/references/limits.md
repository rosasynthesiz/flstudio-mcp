# Limits and how to talk about them

Hard API limits (FL's own, measured on FL 26.1.7 / Producer Edition):

| Cannot | Consequence |
|---|---|
| Load a new VST/AU/FLEX instance | Only shape plugins already in the project (`fl_plugin_*`) |
| Load favourite presets programmatically | Read preset names (`fl_list_presets`, `fl_suggest_preset`), user loads; then tweak params |
| Read notes back | Every write is blind — verify with screenshots and the generated script |
| Create/move/resize playlist clips | User drags clips; you give exact bar + length |
| Delete patterns | Empty patterns stay; name test patterns clearly |
| Render/bounce audio, load audio files | Bouncing is manual; no audio-sample workflow |
| Set channel → mixer-track routing | `fl_set_route` only edits mixer→mixer sends |
| Encode automation curves | No automation writing at all |
| Read FL's output audio | Level metering only (`fl_get_track_level`, watch mode) |

## Writes FL refuses

- Any write while a dialog is open (the welcome screen counts) → `FL_BUSY`.
  Ask the user to close it; do not retry in a loop.
- Writes also fail while FL is in the background for hotkey-driven paths; the
  pyscript trigger needs FL active.

## Levels and "sounds wrong"

- `fl_get_track_level` returns `playing: false` when the transport is stopped
  *or* the window landed on silence. Re-check `fl_get_play_state` before
  concluding a track is dead.
- A single 1.2 s snapshot can miss clipping in a drop; use
  `fl_mix_watch_start` → play the loudest section → `fl_mix_watch_stop`.
- Without plugins loaded there is no EQ/compression to offer. Say so instead of
  proposing a chain the session cannot build (`fl_setup_chain` reports MISSING
  steps for exactly this reason).

## Honesty rules for this bridge

- Never claim a note write landed without a visual check.
- If a tool returns `verified: false` / `verified: true` on a stale read, trust
  the screenshot for notes and the fresh readback for mixer values.
- Say which of your actions were destructive, and keep a `.mid` export as the
  backup for anything the user performed live.
