# Pitfall: Parameter Ranges & Units

Many FL Studio setters expect normalized values from `0.0` to `1.0`.
UI values, dB, Hz, percentages, MIDI-CC, and normalized values **must not be mixed.**

**Incorrect Example:**
```python
mixer.setEqGain(5, 0, -14)
```

**Correct Example (High-Level Wrapper):**
```python
set_internal_mixer_eq_gain_db(track=5, band=0, db=-14)
```

**Correct Example (API with calibrated knowledge):**
```python
mixer.setEqGain(5, 0, 0.2502)
```
