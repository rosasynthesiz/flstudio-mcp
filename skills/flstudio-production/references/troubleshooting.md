# FLStudioMCP Troubleshooting

## Bridge Preflight

- Start with `fl_transport(action="ping")`.
- If the TCP daemon is needed for a live script, start it before running live
  tests and stop it afterward.
- Confirm FL Studio, the virtual MIDI ports, and the controller build marker.

## Common Failures

- Bridge not alive: FL is closed, MIDI ports are missing, or the controller is
  not selected in FL MIDI settings.
- Timeout: controller is loaded but not responding; reload MIDI scripts or
  reselect the FLStudioMCP controller.
- Unknown command: FL is running an older controller script; install/reload the
  current script and confirm the `fl_transport(action="ping")` build marker.
- Piano Roll write reports triggered but notes do not appear: `MCP Apply` was
  probably not armed from the Piano Roll Scripting menu.
- Plugin write preflight fails: the expected plugin is not loaded on that
  track/slot. Do not load it through the API.

## Readback Mismatch

When a write returns but readback does not match:

1. Roll back immediately if project state changed.
2. Check target selection, indexing, focus, and readback timing.
3. If the API is documented, keep it documented-unconfirmed and run a targeted
   false-positive probe before removing support.
4. Record the FL build, controller build marker, target, attempted value,
   readback, and rollback result.

## Leaving The System Clean

- Stop live-test daemons you started.
- Leave playback stopped and recording disarmed after transport tests.
- Do not leave temporary plugin parameters, colors, routes, notes, or pattern
  changes in the project unless the user asked for the final edit.
