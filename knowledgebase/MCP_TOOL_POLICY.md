# MCP Tool Policy

## Tool Hierarchy
1. **Use High-Level Safe Tools** (e.g. `set_internal_mixer_eq_gain_db`).
2. **Use Calibrated Conversion Tools**, if no high-level tools are available.
3. **Raw FL Studio API only as a Last Resort** (e.g. `mixer.setEqGain`).
4. **Never guess normalized values!**

## Examples
**Forbidden:**
```python
mixer.setEqGain(5, 0, -14)
```
*(Reason: `-14` is a dB value, but `mixer.setEqGain` expects a normalized float).*

**Allowed:**
```python
set_internal_mixer_eq_gain_db(track=5, band="low", db=-14)
```
