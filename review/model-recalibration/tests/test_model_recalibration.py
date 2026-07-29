# -*- coding: utf-8 -*-
"""Regression tests for the SOA-local recalibrated server.model.

Copy this file to tests/test_model_recalibration.py after integrating the model.
Run from repository root:
    python -m unittest tests.test_model_recalibration
"""

import math
import unittest

from server import model as M


class ModelRecalibrationTest(unittest.TestCase):
    def test_project_public_contract_is_preserved(self):
        for name in (
            "N", "D1", "D2", "CAP", "IO_CAP_LIM", "PARAM_META",
            "corr", "branch", "calib", "VofI", "series_vio", "sv",
            "ep", "rdd_r", "BINDING_FUNCS",
        ):
            self.assertTrue(hasattr(M, name), name)
        self.assertEqual(M.D1["method"], "exp")
        self.assertEqual(M.D2["method"], "late")

    def test_original_measured_rows_are_retained(self):
        self.assertEqual(len(M.D1["m"]), 4)
        self.assertEqual(len(M.D2["m"]), 3)
        self.assertAlmostEqual(M.D1["m"][2]["x"], 2.56)
        self.assertAlmostEqual(M.D2["m"][2]["vn"], -9.47609)

    def test_measured_endpoint_direct_calibration(self):
        for dev in (M.D1, M.D2):
            for row in dev["m"]:
                cp = M.corr(row["x"], dev, row["vp"], row["ip"], False, n=1200)
                cn = M.corr(row["x"], dev, -row["vn"], -row["inn"], True, n=1200)
                bp = M.branch(row["x"], dev, row["vp"], cp, False, n=1200)
                bn = M.branch(row["x"], dev, -row["vn"], cn, True, n=1200)
                self.assertAlmostEqual(bp["I"][-1], row["ip"], places=8)
                self.assertAlmostEqual(bn["I"][-1], row["inn"], places=8)
                self.assertGreater(min(bp["G"]), 0.0)
                self.assertGreater(min(bn["G"]), 0.0)

    def test_worst_best_calibtable_grid_is_buildable(self):
        for dev in (M.D1, M.D2):
            lo, hi = M.xwindow(dev)
            for corner in ("worst", "best"):
                for k in range(24):
                    x = lo * (hi / lo) ** (k / 23.0)
                    cal = M.calib(dev, x, corner, n=500)
                    self.assertEqual(set(("e", "pos", "neg", "cp", "cn")) - set(cal), set())
                    for c in (cal["cp"], cal["cn"]):
                        self.assertIn("q", c)
                        self.assertIn("s", c)
                    for br in (cal["pos"], cal["neg"]):
                        self.assertIn("V", br)
                        self.assertIn("I", br)
                        self.assertIn("G", br)
                        self.assertGreater(br["G"][-1], 0.0)

    def test_diode_positive_is_exactly_raw_through_1p6V(self):
        row = M.D1["m"][2]
        cp = M.corr(row["x"], M.D1, row["vp"], row["ip"], False, n=2000)
        bp = M.branch(row["x"], M.D1, row["vp"], cp, False, n=2000)
        for v, raw_i, new_i in zip(bp["V"], bp["I_raw"], bp["I"]):
            if v <= 1.6:
                self.assertAlmostEqual(raw_i, new_i, places=13)

    def test_clamp_low_current_is_not_globally_scaled(self):
        row = M.D2["m"][1]
        for neg, T, target in (
            (False, row["vp"], row["ip"]),
            (True, -row["vn"], -row["inn"]),
        ):
            cc = M.corr(row["x"], M.D2, T, target, neg, n=1600)
            br = M.branch(row["x"], M.D2, T, cc, neg, n=1600)
            endpoint_raw = abs(br["I_raw"][-1])
            for raw_i, new_i in zip(br["I_raw"], br["I"]):
                if abs(raw_i) <= 0.19 * endpoint_raw:
                    self.assertAlmostEqual(raw_i, new_i, places=12)

    def test_positive_size_trend_in_operating_current_range(self):
        checks = (
            (M.D1, [0.64, 1.344, 2.56, 3.84], [0.1, 0.3, 0.5]),
            (M.D2, [1415.232, 2021.76, 2628.288], [1.0, 1.33]),
        )
        for dev, xs, currents in checks:
            cals = [M.calib(dev, x, "worst", n=1800) for x in xs]
            for current in currents:
                voltages = [M.VofI(c["pos"], current) for c in cals]
                self.assertTrue(all(math.isfinite(v) for v in voltages))
                for v_small, v_large in zip(voltages, voltages[1:]):
                    self.assertGreater(v_small, v_large)

    def test_measured_interpolation_helper(self):
        e = M.measured_ep(M.D2, 1800.0)
        self.assertGreater(e["vp"], M.D2["m"][0]["vp"])
        self.assertLess(e["vp"], M.D2["m"][1]["vp"])
        self.assertLess(e["vn"], M.D2["m"][0]["vn"])
        self.assertGreater(e["vn"], M.D2["m"][1]["vn"])


if __name__ == "__main__":
    unittest.main()
