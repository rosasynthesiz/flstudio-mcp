# MIDI Export Partitioning And Automation CC Transport

**Date:** 2026-06-06  
**Agent/Author:** Codex  
**Topic:** FL Studio MIDI import partitioning and isolated automation CC export  
**Affected File/API:** `scratch/generator-psytrance-rules/*`, Standard MIDI files, FL Studio MIDI import, FL Studio automation clips  
**Affected API/Function/Tool:** External MIDI export artifacts, generated sidecar plans, manual FL Studio MIDI import  
**Confidence Level:** `user_reported`

## Context
The psytrance generator keeps its musical plan intact, but the final MIDI
export should be prepared for stable manual import into FL Studio. The user
reported that FL Studio can become unreliable around 31 imported instrument
tracks/channels in one MIDI import, and requested conservative export
partitioning plus isolated MIDI-CC files for automation curves.

## Observation
Instrument MIDI export should be partitioned at file-write time, not during
musical generation. A single instrument MIDI file should contain at most 30 FL
import tracks or instrument targets. This does not change the Standard MIDI
channel field: `midi.channel` remains `0..15`.

For automation, MIDI should be treated only as curve-data transport. Native FL
automation clips and parameter links remain manual unless a rollback-safe,
readback-verified MCP path exists. The least ambiguous manual-import shape is
one automation target per MIDI-CC file with one fixed CC number, one fixed MIDI
channel, one target parameter, a clear length in bars/BPM, and a mapping-file
entry pointing to the intended FL automation clip or target parameter.

## Tested Values
- Live FL import partitioning was not tested by this agent.
- The 30-track instrument MIDI export threshold is a conservative user-reported
  policy.
- MIDI CC value range is standard `0..127`.
- MIDI channel range remains `0..15`.

## Result
The scratch psytrance rule pack now documents:

- Max 30 FL import tracks/instrument targets per instrument MIDI file.
- Additional Type 1 MIDI files when more instrument tracks are needed.
- Optional sidecar manifest fields for instrument MIDI shards.
- Optional sidecar manifest fields for automation MIDI-CC files.
- A required automation mapping file when automation MIDI files are exported.
- One target, one file, one CC as the preferred automation import policy.

## Valid Ranges
- `midi.channel`: `0..15`.
- Automation MIDI `cc`: `0..127`.
- Automation MIDI `channel`: `0..15`.
- Instrument MIDI file `track_count`: `1..30` by current conservative policy.
- Automation file `length_bars`: integer `>= 1`.
- Automation file `bpm`: positive number.

## Example
For a project with 42 instrument tracks, export:

```text
project_part01_instruments.mid  # 30 import tracks
project_part02_instruments.mid  # 12 import tracks
```

For automation, prefer isolated files:

```text
lead_cutoff_32bar_cc74_ch01.mid -> "LEAD - Cutoff"
bass_filter_16bar_cc74_ch02.mid -> "BASS - Filter"
reverb_wash_16bar_cc91_ch03.mid -> "SEND - Reverb Wash"
```

## Known Pitfalls
- Do not interpret the 30-track export policy as a change to Standard MIDI
  channel range.
- Avoid packing many CCs across many channels into one automation MIDI file for
  manual FL import.
- Do not put many unrelated CCs on the same track/channel.
- Do not claim MIDI-CC import creates or binds FL automation clips.
- MIDI CC resolution is coarse for precise EQ frequency, fine gain,
  mastering, and exact sidechain/volume-shaper curves.

## Source/Method
User report and local rule-pack update on 2026-06-06. No live FL Studio import
smoke test was performed.

## Reproduction Steps
1. Generate a plan with more than 30 instrument/import tracks.
2. Export instrument MIDI in multiple Type 1 files, each with `track_count <= 30`.
3. Keep each track's `midi.channel` in `0..15`.
4. For automation, export one target per MIDI-CC file.
5. Create a JSON/YAML mapping file from each automation MIDI file to the manual
   FL automation clip or target parameter.

## Open Questions
- The exact FL Studio build-specific failure threshold for large MIDI imports
  has not been measured.
- Whether a multi-track automation MIDI file remains practical depends on the
  manual import workflow and target project complexity.

## Next Recommended Action
When FL Studio is available, run a manual import smoke comparing 30-track and
31-track instrument MIDI files and document the build, import settings, and
result.
