# Normalized Values vs. Real Units

Many FL Studio setters expect normalized values from `0.0` to `1.0`.
- **dB, Hz, percentages, MIDI-CC, and normalized floats** are fundamentally different domains.
- **Getters** can (depending on `mode`) return real units, while **setters** still require normalized values.
- **Readback is mandatory** when setting precise target values without a complete calibration mapping.
