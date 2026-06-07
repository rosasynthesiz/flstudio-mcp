# Channel vs. Pattern Indexing Pitfalls

**Date:** 2026-06-06  
**Agent/Author:** Antigravity  
**Topic:** FL Studio Channel and Pattern Index Synchronization  
**Affected File/API:** `fl_studio_mcp.protocol.CMD_CHANNEL_ROUTING_SUMMARY`, `channel_list`, `pattern_list`  
**Confidence Level:** `implementation_verified`

## Context
When processing a newly imported MIDI file, the script attempted to configure channel and pattern mappings assuming that the channel index `c['i']` from `channel_list` exactly mirrors the fixed absolute channel IDs from `CMD_CHANNEL_ROUTING_SUMMARY` and that pattern indices rigidly follow relative offsets based on earlier runs.

## Observation
1. In FL Studio, when reading the `routing` via `CMD_CHANNEL_ROUTING_SUMMARY`, each item has a static `channel` index (e.g. `channel: 5` for `MIDI_08_Snare_Roll`).
2. However, the `channel_list` API response yields an `i` value which reflects the *current, potentially dynamic index* within the rack list. If any channel has been deleted or shifted before running the setup script, the `i` from `channel_list` will **NOT** match the absolute `channel` value stored in the routing mapping!
3. Furthermore, when executing "Split by channel", FL Studio creates exactly one Pattern per channel with note data. The relationship is always exactly `pattern_index = channel_index + 1` relative to the current `channel_list` indices.
4. Because the indices shifted slightly (e.g. from 5 to 6), a script relying on relative offsets or hardcoded sequential processing mapped names to the wrong patterns, overwriting previously correctly configured patterns (e.g. `PAT_DRM_Fills` being renamed to `PAT_DRM_Snare_Roll_Build`).

## Result
Applying renaming logic based on assumed static indices resulted in off-by-one errors for patterns. The script modified the incorrect patterns, resulting in unmapped leftover patterns like `warm_air_over_the_field_`.

## Open Questions
- Is there an internal, immutable UUID-like identifier for Channels or Patterns across the bridge? (Current assumption: No, we must rely on names).

## Next Recommended Action
Always verify `c['name']` directly to identify the target element before issuing a rename or color command. **Never assume index stability between successive script runs or different API calls.**
For pattern operations targeting a specific channel, always derive `pat_idx = c['i'] + 1` from the *current* `channel_list` pass where you've verified the channel by its string name.
