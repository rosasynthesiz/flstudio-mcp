# Mixer EQ Calibration Procedure

Guide for determining reliable mappings for `setEqGain` and `setEqFrequency`.

## Procedure
1. **Only test on an empty test mixer track.** Not during productive sessions.
2. Save project beforehand.
3. Set test values in small steps (`0.0` to `1.0`).
4. After each set, read back the value using `getEqGain(track, band, mode=1)` or `getEqFrequency(track, band, mode=1)`.
5. Enter results into `mixer_eq_calibration.json`.
6. **Do not make assumptions about linear mappings.**
7. Document FL Studio version, API version, and platform in the JSON.

## JSON Example Fragment
```json
{
  "normalized": 0.2502,
  "db": -14.0,
  "confidence": "user_reported",
  "source": "user_reported"
}
```
