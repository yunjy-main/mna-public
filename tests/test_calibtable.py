# -*- coding: utf-8 -*-
"""Calibration-table accuracy check: interpolated V(I; x) vs direct calibration.

Off-grid x spot checks (worst corner) at 50% and 90% of It2. Tolerance is the
interpolation budget (log-x linear, 48-point grid): rel < 5e-3.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import model as M  # noqa: E402
from server.calibtable import get_table  # noqa: E402

TOL = 5e-3
fails = []
tbl = get_table()

for dev, dev_id, xs in ((M.D1, "diode", (1.7, 3.1)), (M.D2, "clamp", (1700.0, 2400.0))):
    for x in xs:
        c = M.calib(dev, x, "worst")
        it2 = c["e"]["ip"]
        for frac in (0.5, 0.9):
            i = frac * it2
            exact = M.VofI(c["pos"], i)
            approx = tbl.vofi(dev_id, "worst", x, i)
            rel = abs(approx / exact - 1)
            if rel > TOL:
                fails.append("{} x={} I={:.3f}: table {:.6f} vs exact {:.6f} (rel {:.2e})".format(
                    dev_id, x, i, approx, exact, rel))
        # C1 extension sanity: finite and increasing beyond endpoint
        v1, v2 = tbl.vofi(dev_id, "worst", x, it2 * 1.05), tbl.vofi(dev_id, "worst", x, it2 * 1.2)
        if not (v2 > v1 > 0):
            fails.append("{} x={}: C1 extension not monotone ({}, {})".format(dev_id, x, v1, v2))

if fails:
    for m in fails:
        print("FAIL " + m)
    sys.exit(1)
print("PASS: calibration table accuracy (8 spot checks + C1 extension, rel<5e-3)")
