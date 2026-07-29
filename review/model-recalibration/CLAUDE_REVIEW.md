# Claude integration request

Repository: `yunjy-sec/mna`
Review branch: `agent/model-recalibration-review`
Base reviewed: `58fd8015b7dc5ba3c5b5b13d85d6952aff0927ff`
Related issue: #16

## Purpose

The current calibrated clamp model applies a branch-wide scale to match the SOA endpoint. That global scale suppresses the low-current branch and reverses the expected size trend: a larger clamp can show a larger voltage at the same operating current.

This package proposes a local SOA correction while retaining the original raw Softplus equations and measured SOA source rows.

## Requested integration work

1. Review the proposed equations in `MODEL_SPEC.md`.
2. Inspect `model_core_reference.py` as a reference fragment; do not copy it blindly.
3. Integrate the accepted calibration core into `server/model.py` manually on a separate implementation branch.
4. Preserve all current public contracts used by:
   - `server/calibtable.py`
   - `server/optimizer.py`
   - `server/main.py`
   - `tests/regression.py`
   - netlist/MNA/victim/capacitance code
5. Regenerate `assets/calib_table.json` and Python golden values only after numerical review.
6. Port the same equations to `tests/regression.js` before treating the independent JS witness as required.
7. Update `docs/two_device_complete_iv_soa_model.html` after runtime behavior is accepted.

## Required physical behavior

### Diode positive
- Raw I-V must be exactly preserved through 1.6 V.
- Above 1.6 V, conductance must decrease smoothly toward saturation.
- The selected SOA endpoint must be reached.
- `dI/dV` must stay positive.

### Diode negative
- Preserve the raw size trend away from SOA.
- Apply only a local correction near SOA.
- Allow local conductance reduction or breakdown-like increase depending on endpoint/raw relation.

### Clamp positive and negative
- Remove branch-wide scale calibration.
- Preserve the original size trend at operating current.
- Apply conductance degradation only near SOA.
- Match the selected SOA endpoint.

## Acceptance checks

- Existing `D1`, `D2`, `corr`, `branch`, `calib`, `VofI`, `series_vio`, `ep`, `sv` call contracts remain valid.
- `calib()` returns `e`, `pos`, `neg`, `cp`, `cn`.
- Branches return at least `V`, `I`, `G`.
- All generated conductances are finite and positive.
- Measured endpoint error is within numerical integration tolerance.
- Both worst/best corners build across the full `xwindow()` calibration-table grid.
- Clamp voltage at 1.33 A decreases with size across the measured sizes.
- Diode voltage at representative positive currents decreases with size, except any explicitly documented raw-model micro-crossing.
- Full Python tests and optimizer regression pass after regenerating intentional numerical assets.

## Non-goals

- Do not merge this review directory itself into the runtime as the final architecture.
- Do not overwrite `main` or regenerate golden files before reviewing the numerical behavior.
- Do not remove existing capacitance, RDD, victim, netlist, optimizer, or response-schema work.

## Suggested implementation sequence

1. Create an integration branch from current `main`.
2. Copy only accepted calibration logic into `server/model.py`.
3. Add/update focused model tests.
4. Generate calibration table.
5. Run Python regression and inspect changed golden values.
6. Run optimizer smoke tests, especially W-free and clamp-size trends.
7. Port JS witness and documentation.
8. Open a draft PR with before/after plots and numerical summary.
