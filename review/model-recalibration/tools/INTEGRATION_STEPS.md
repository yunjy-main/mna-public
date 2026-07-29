# Integration steps for Claude

This review package intentionally does not modify runtime files on this branch.

## Recommended workflow

1. Create a separate implementation branch from current `main`.
2. Read `../MODEL_SPEC.md` and `../model_core_reference.py`.
3. Integrate the accepted correction metadata and calibration core into `server/model.py` while preserving all unrelated code.
4. Copy `../tests/test_model_recalibration.py` into the repository test suite.
5. Run the focused tests first.
6. Regenerate `assets/calib_table.json`.
7. Regenerate and review Python golden values.
8. Run the full Python regression suite and optimizer smoke tests.
9. Port the accepted equations to `tests/regression.js`.
10. Update the HTML model documentation and open a draft PR.

## Commands after implementation

```bash
python -m unittest tests.test_model_recalibration -v
python review/model-recalibration/tools/post_apply_check.py
python -m server.calibtable
python tests/regression.py --emit
python tests/regression.py
```

Do not regenerate golden assets before inspecting the changed diode/clamp curves and confirming the expected size ordering.
