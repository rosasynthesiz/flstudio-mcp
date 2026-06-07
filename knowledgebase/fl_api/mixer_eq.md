# Internal FL Studio Mixer EQ

Documentation of the internal FL Studio Mixer EQ API.

## API Functions
```python
mixer.getEqBandCount()

mixer.getEqGain(track, band, mode=0)
mixer.setEqGain(track, band, value)

mixer.getEqFrequency(track, band, mode=0)
mixer.setEqFrequency(track, band, value)

mixer.getEqBandwidth(track, band)
mixer.setEqBandwidth(track, band, value)
```

## Bands
- Band `0` = Low
- Band `1` = Mid
- Band `2` = High

## Important Rules
- Setters expect **normalized float values**, not dB or Hz. (`docs_confirmed`)
- `getEqGain(..., mode=1)` can return dB. (`user_reported`)
- `getEqFrequency(..., mode=1)` can return Hz. (`user_reported`)
- `setEqGain(...)` accepts NO dB. (`docs_confirmed`)
- `setEqFrequency(...)` accepts NO Hz. (`docs_confirmed`)
