# Electro Template Mixer Setup

- **Date:** 2026-06-07
- **Agent/Author:** Codex
- **Topic:** Live-read mixer, plugin, routing, pan, and stereo-separation structure for the FL Studio stock-style `Electro` template.
- **Affected File/API:** `mixer_list_tracks`, `mixer_get_track`, `mixer_get_routing_all`, `mixer_get_routing`, `mixer_get_slot`, `plugin_list`, `plugin_get_params`, `channel_routing_summary`, Mix Review, Routing Review, Project Health / Preflight, cleanup detection.
- **Context:** The user reported a live standard project template named `Electro`, with occupied mixer tracks 1-3 and 116-125. The goal is to make MCP tools understand this stem-based mono/stereo setup instead of reporting false routing, cleanup, or mix-improvement findings.
- **Observation:** The template uses tracks 1-3 as M/S premaster stages and tracks 116-125 as stem/control buses. Tracks 4-21 are source tracks. Default-named tracks 22-115 are not ordinary unused tracks in this template; they are pre-routed placeholders to `Instruments ► Mix` on track 120. The `SideChain` track 124 sends to tracks 123 and 125 at send level `0.0`, apparently as control routing for the loaded Fruity peak controller rather than a broken audio route.
- **Tested Values:**
  - FL Studio: Producer Edition v25.2.5 [build 5055].
  - Controller build marker: `channels-v38`.
  - Transport: TCP daemon, heartbeat alive.
  - Project state: 128 BPM, 9 channels, 127 mixer tracks, stopped, not recording.
  - Focus tracks read: 1-3 and 116-125 with mixer detail, effect slots, plugin parameter pages, routing, pan, and `stereo_sep`.
  - Existing tool behavior probe: `scripts/run_mix_doctor.py --no-params --max-tracks 126 --peak-samples 1` returned 111 low findings in the stopped template; `detect_cleanup(..., max_plugin_checks=120)` returned 95 unused mixer tracks, primarily `Insert 22`-`Insert 115`.
- **Result:** The live readback confirms a recognizable template topology. Current generic heuristics can misclassify template placeholders and bus tracks as real tracks needing high-pass filters, as ungrouped sources, or as unused cleanup candidates. Template-aware classification should run before Mix Review, Routing Review, Project Health, Preflight, and cleanup judgements.
- **Confidence Level:** `measured_once`
- **Source/Method:** Read-only live probe `scratch/scripts/read_electro_template_live.py`, full dump at `scratch/analysis/2026-06-07_electro_template/electro_template_live_read.json`, compact profile at `knowledgebase/templates/profiles/electro.json`; read-only Mix Doctor and cleanup probes over TCP.
- **Valid Ranges:** Mixer pan readback is `-1..+1`; mixer `stereo_sep` readback is `-1..+1`; route send levels were observed as `0.8` for template audio routes and `0.0` for `SideChain` control routes; plugin parameter values are normalized `0..1` with display strings from `plugin_get_params`.
- **Example:** Track 125 `Sub ► Mix` routes only to track 2 `PreMaster M` at `0.8`, has `stereo_sep=1.0`, and contains Fruity Limiter slot 8 plus Fruity PanOMatic slot 9. In this template, that should be treated as deliberate mono/stem routing, not as an automatic stereo-width error or a routing omission.
- **Known Pitfalls:** Default-named tracks 22-115 route to `Instruments ► Mix`; outgoing non-Master route alone does not prove a track contains audio. Conversely, default name plus no plugin does not prove an unused cleanup candidate when the route is part of a template placeholder bank. Bus names use `► Mix`, not only `bus`, so bus-detection heuristics that only search for `bus` miss this setup.
- **Reproduction Steps:** Open the `Electro` template in FL Studio, start the TCP daemon, confirm `fl_transport(action="ping")`, then run `PYTHONPATH=src FLSTUDIO_MCP_TRANSPORT=tcp .venv/bin/python scratch/scripts/read_electro_template_live.py`.
- **Open Questions:** Verify the other 12 standard templates. Confirm whether `stereo_sep=1.0` on `Sub ► Mix` is intended as mono fold-down in this template despite current generic KB wording around positive stereo-separation values. Reload/verify controller build `channels-v39` before relying on the latest source-only stereo metadata changes.
- **Next Recommended Action:** Use the compact profile as the reference fixture for data-driven classifier work, then capture and validate the 12 remaining standard templates in the same schema.

## Live Topology Summary

| Track | Role | Route |
|---:|---|---|
| 1 | `PreMaster MS` | `Master` |
| 2 | `PreMaster M` | `PreMaster MS` |
| 3 | `PreMaster S` | `PreMaster MS` |
| 116 | `Drums ► Mix` | `PreMaster M`, `PreMaster S` |
| 117 | `Kick ► Mix` | `Drums ► Mix`, `SideChain` |
| 118 | `Snare ► Mix` | `Drums ► Mix`, `SideChain` |
| 119 | `Overhead ► Mix` | `Drums ► Mix` |
| 120 | `Instruments ► Mix` | `PreMaster M`, `PreMaster S` |
| 121 | `Background ► Mix` | `PreMaster M`, `PreMaster S` |
| 122 | `Vocals ► Mix` | `PreMaster M`, `PreMaster S` |
| 123 | `SideChained ► Mix` | `PreMaster M`, `PreMaster S` |
| 124 | `SideChain` | `SideChained ► Mix` at `0.0`, `Sub ► Mix` at `0.0` |
| 125 | `Sub ► Mix` | `PreMaster M` |

## Plugin Highlights

- Track 2 `PreMaster M`: Fruity Parametric EQ 2, Fruity Stereo Shaper, Fruity PanOMatic.
- Track 3 `PreMaster S`: Fruity Parametric EQ 2, Fruity Stereo Shaper, Fruity PanOMatic.
- Track 119 `Overhead ► Mix`: Fruity Delay 3.
- Track 121 `Background ► Mix`: Fruity Parametric EQ 2, Fruity PanOMatic.
- Track 123 `SideChained ► Mix`: Fruity Parametric EQ 2, Fruity WaveShaper, Fruity Limiter, Fruity PanOMatic.
- Track 124 `SideChain`: Fruity peak controller.
- Track 125 `Sub ► Mix`: Fruity Limiter, Fruity PanOMatic.
