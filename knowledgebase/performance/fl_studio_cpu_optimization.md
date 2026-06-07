# FL Studio CPU Optimization

- **Date:** 2026-06-06
- **Agent/Author:** Codex
- **Topic:** CPU, audio buffer, and project-performance guidance for future Performance Review workflows.
- **Affected File/API:** Future CPU/Performance Review, Project Health Overview, manual guidance, possible read-only diagnostics.
- **Context:** The roadmap includes a future CPU / Performance Review. This entry captures official FL Studio performance guidance without adding unsafe system or project mutations.
- **Observation:** FL Studio's CPU meter reflects real-time buffer processing pressure, not total OS CPU utilization. Buffer underruns happen when the audio buffer runs out during live playback. Official guidance includes audio driver choice, sample rate, buffer length, plugin window management, Smart Disable, multithreading, Stretch/Stretch Pro CPU cost, plugin performance monitoring, consolidation, PPQ, and project routing that allows multi-core parallelism.
- **Tested Values:** No live FL Studio performance probes were run. This entry is source extraction only.
- **Result:** A future Performance Review should start read-only/manual: explain CPU meter meaning, identify probable causes from project state where visible, and provide manual steps. It should not modify audio settings, close UI windows, consolidate tracks, change Stretch mode, or alter plugin wrapper settings without a separate safety design.
- **Confidence Level:** `docs_confirmed`
- **Source/Method:** Image-Line Optimizing FL Studio Performance manual, Audio Settings manual, local CPU Meter Explained transcript.
- **Valid Ranges:** Documented guidance includes Apple Silicon buffer candidates 128/192/256/512/1024 samples, Intel/AMD guidance of at least 10 ms and commonly 10-40 ms for performance tuning, and default sample-rate preference of 44.1 kHz or 48 kHz when needed. These are manual settings guidance, not MCP write ranges.
- **Example:** If the user reports crackling while OS CPU is low, the assistant should explain that one audio-processing path may be maxing out the buffer deadline and suggest buffer, driver, plugin, and routing checks.
- **Known Pitfalls:** Longer buffers are not always better on Apple Silicon. Low OS CPU does not rule out underruns. Smart Disable can break time-based, envelope-based, or long-decay plugins. Stretch/Stretch Pro can be CPU-heavy, but this MCP currently must not claim automatic Stretch mode changes.
- **Reproduction Steps:** Review the listed manual pages and CPU Meter transcript. Confirm any future automated diagnostic against live FL Studio state before exposing writes.
- **Open Questions:** Which performance metrics can be read from FL Studio through the controller without broad UI automation or unstable API calls.
- **Next Recommended Action:** Build a read-only Performance Review design that reports likely causes and manual steps, then identify separately which project-state fixes can be rollback-safe.

## Assistant Guidance

- Explain that FL Studio CPU meter is about real-time buffer processing. It can hit 100% while OS-level CPU looks low.
- Treat audible clicks, pops, stuttering, and increasing underrun counts as live playback performance symptoms.
- Differentiate live underruns from rendered-audio glitches. Rendered glitches usually indicate plugin behavior, not buffer underruns.
- Prefer native audio drivers where applicable and align device/system sample rates.
- Use conservative sample rates for production work: 44.1 kHz or 48 kHz unless there is a specific reason for higher rates.
- On Intel/AMD systems, use buffers at least around 10 ms and increase gradually for heavy projects.
- On Apple Silicon, start from documented sample choices such as 128 and increase through 192, 256, 512, and 1024 as needed; do not assume maximum buffer is best.
- Close plugin windows during heavy playback if the user keeps many plugin UIs open.
- Use the Plugin Performance Monitor manually to identify heavy plugins before recommending consolidation.
- Recommend Smart Disable only with the caveat that some time-based, envelope-based, or long-decay plugins may misbehave.
- Recommend avoiding unnecessary plugin bridging and Rosetta 2 where native Apple Silicon FL Studio and native plugins are available.
- For heavy projects, prefer independent mixer-track processing paths for high-CPU plugins and avoid unnecessary shared send dependencies that serialize work.

## Source Notes

- The optimization manual says underruns are caused by CPU overload or system issues and matter during real-time playback, not offline rendering.
- The same manual says high sample rates such as 96 or 192 kHz use significantly more CPU than 44.1/48 kHz.
- The audio-settings manual documents CPU options: multithreaded generator processing, multithreaded mixer processing, Smart Disable, and Align tick lengths.
- The CPU Meter transcript explains why FL Studio's CPU meter can be red while OS CPU use is much lower.
