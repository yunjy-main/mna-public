# MNA-compatible diode/clamp SOA-local recalibration

Target repository: `yunjy-sec/mna`  
Reviewed base HEAD: `58fd8015b7dc5ba3c5b5b13d85d6952aff0927ff`

## What this bundle changes

The existing raw Softplus parameter equations, measured rows, SOA power-law envelopes, capacitance model, RDD model, victim model, netlist bindings, and optimizer-facing APIs remain in place.

Only the calibration core inside `server/model.py` is changed.

- Diode positive
  - Raw I-V is exactly preserved through 1.6 V.
  - Above 1.6 V, differential conductance decreases smoothly toward saturation.
  - The selected SOA endpoint is matched exactly.
- Diode negative
  - The raw size trend is preserved through the early branch.
  - Near SOA, a local conductance reduction or breakdown-like increase is applied as required by the endpoint.
- Clamp positive and negative
  - The former branch-wide `scale` is removed.
  - The raw width trend is preserved at low current.
  - Conductance is reduced only near SOA, so larger clamp size retains lower voltage at operating current.
- Extrapolation fallback
  - Existing `xwindow()` remains unchanged.
  - If an extrapolated SOA envelope asks for more current than raw I-V, only the late branch is locally boosted. No global scaling is used.

## Preserved project contracts

The patch preserves:

- `D1["method"] == "exp"`
- `D2["method"] == "late"`
- `corr(x, d, T, I, neg, n=N)` signature
- `corr()` fields `q` and `s`
- `branch()` result fields `V`, `I`, `G`
- `calib()` result fields `e`, `pos`, `neg`, `cp`, `cn`
- `VofI()`, `series_vio()`, `sv()`, `ep()`
- `CAP`, `PARAM_META`, `rdd_r()`, `BINDING_FUNCS`
- all code after the calibration core, including the existing victim functions

Additional fields such as `I_raw`, `G_raw`, and `multiplier` are additive; existing callers may ignore them.

## Required generated assets

The model values change, so old generated assets must not be reused.

```bash
python -m server.calibtable
python tests/regression.py --emit
python tests/regression.py
```

`server/calibtable.py` does not need a structural change because the existing `calib()` and branch schemas are preserved. It will regenerate `assets/calib_table.json` using the new curves.

## Independent JavaScript witness

`tests/regression.js` is an independent port of the old calibration equations. After the Python model and `golden.json` are updated, its model core must be ported to the same SOA-local equations before requiring the JS witness to pass. Do not interpret a JS-witness failure at that stage as a Python runtime integration failure.

The HTML model documentation should likewise be refreshed after the Python behavior is accepted.

## Validation performed on the compatibility fixture

- 8 dedicated compatibility tests passed.
- 192 calibrations were built: 2 devices × 2 corners × 48 extrapolation-grid sizes.
- Maximum endpoint error: approximately `3.6e-15 A`.
- Minimum endpoint conductance: approximately `1.7e-4 S`.
- Positive size order was confirmed:
  - diode at 0.5 A: voltage decreases from x=0.64 to 3.84;
  - clamp at 1.33 A: voltage decreases from x=1415.232 to 2628.288.

## Important scope statement

The patcher was tested against a contract fixture matching the current `server/model.py` public structure. It was not executed inside the private repository checkout in this environment. Therefore the repository's complete existing test suite and generated assets still need to be run after applying it locally or on an integration branch.
