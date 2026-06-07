# FL Studio Workflow Standards

- **Date:** 2026-06-06
- **Agent/Author:** Codex
- **Topic:** General FL Studio workflow and organization standards for assistant planning.
- **Affected File/API:** Project Organizer, Routing Review, Project Health, Jam-to-Project planning, `fl_channel`, `fl_mixer`, `fl_pattern`, `fl_playlist`.
- **Context:** FL Studio does not force a one-to-one Instrument > Playlist Track > Mixer Track model. Assistants need workflow knowledge that helps organize projects without inventing unsafe write operations.
- **Observation:** Image-Line documents multiple workflows. The Instrument/Audio Track workflow creates linked Channel, Playlist, Mixer, naming, coloring, and pattern context. Channel Rack and Mixer-linked workflows are more flexible but require explicit organization and routing checks. Playlist tracks are universal clip lanes, while Channel Rack routing determines mixer processing.
- **Tested Values:** No live FL Studio state was changed. This entry is source extraction only.
- **Result:** Assistants should prefer preserving the user's existing structure, then use read-only analysis to identify missing names, colors, routing, duplicate names, and unlabeled clip lanes. Suggested cleanup must map to existing rollback-safe primitives and avoid playlist clip editing.
- **Confidence Level:** `docs_confirmed`
- **Source/Method:** Image-Line manual "How to use FL Studio - Making music" and local transcript `scratch/extractions/4ICwZjBvgpo_raw.txt`.
- **Valid Ranges:** Not applicable. This entry defines workflow guidance, not FL API ranges.
- **Example:** If a project uses linked Instrument Tracks, a rename/color proposal should keep Channel, Playlist Track, and Mixer Track names consistent where safe tools can update those surfaces. If a project uses loose Channel Rack routing, the assistant should not assume Playlist Track 5 maps to Mixer Track 5.
- **Known Pitfalls:** Playlist Clip Tracks are not inherently mixer tracks. Raw playlist clip movement/deletion is out of scope. Plugin loading/insertion remains manual. Auto-routing methods shown in the UI are manual FL workflows unless a rollback-safe MCP wrapper exists.
- **Reproduction Steps:** Review the official workflow page sections "Instruments", "Arranging & editing", and "Mixing"; compare with the Mixer Routing Getting Started transcript.
- **Open Questions:** Whether future Jam-to-Project tools should expose a read-only classifier for linked Instrument/Audio Track workflow vs. free-form Channel Rack workflow.
- **Next Recommended Action:** Add a project-structure preservation mode to Jam-to-Project planning before applying cleanup batches.

## Assistant Guidance

- Start organization tasks with a read-only inventory of channels, mixer tracks, playlist tracks, patterns, and routing.
- Treat linked Instrument/Audio Track projects as higher-structure projects: preserve matched names/colors where present.
- Treat Channel Rack workflow projects as flexible: infer relationships from current channel-to-mixer routing and names, not from matching indices.
- Prefer Project Organizer and Routing Review plans over ad hoc low-level writes.
- Use one named rollback unit for approved naming/color/routing cleanup groups.
- Keep manual instructions for UI-only workflows such as loading plugins, dragging instruments to Playlist headers, and external hardware I/O setup.

## Source Notes

- The workflow manual says the Instrument/Audio Track workflow is recommended when simpler layout, routing, ripple renaming/coloring, and Playlist-header access are desired.
- The manual also says Playlist tracks can hold multiple clip types and are not bound to a specific instrument or mixer track.
- The routing video demonstrates sends and buses as manual workflows; the existing MCP safe wrappers can express only the parts that have snapshot/readback/rollback.

