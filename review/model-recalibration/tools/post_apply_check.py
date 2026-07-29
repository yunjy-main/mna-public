#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Post-integration compatibility and numerical checks for mna/server/model.py."""

import math
from server import model as M


def main():
    max_endpoint_error = 0.0
    min_endpoint_g = float("inf")
    calibration_count = 0
    fallback_count = 0

    for dev in (M.D1, M.D2):
        lo, hi = M.xwindow(dev)
        for corner in ("worst", "best"):
            for k in range(48):
                x = lo * (hi / lo) ** (k / 47.0)
                cal = M.calib(dev, x, corner, n=800)
                max_endpoint_error = max(
                    max_endpoint_error,
                    abs(cal["pos"]["I"][-1] - cal["e"]["ip"]),
                    abs(cal["neg"]["I"][-1] - cal["e"]["inn"]),
                )
                min_endpoint_g = min(
                    min_endpoint_g,
                    cal["pos"]["G"][-1],
                    cal["neg"]["G"][-1],
                )
                fallback_count += int(bool(cal["cp"].get("fallback_from")))
                fallback_count += int(bool(cal["cn"].get("fallback_from")))
                calibration_count += 1

    checks = (
        (M.D1, [0.64, 1.344, 2.56, 3.84], 0.5),
        (M.D2, [1415.232, 2021.76, 2628.288], 1.33),
    )
    order_report = {}
    for dev, xs, current in checks:
        voltages = [
            M.VofI(M.calib(dev, x, "worst", n=1600)["pos"], current)
            for x in xs
        ]
        if not all(math.isfinite(v) for v in voltages):
            raise RuntimeError("non-finite VofI: {}".format((dev["id"], voltages)))
        if not all(a > b for a, b in zip(voltages, voltages[1:])):
            raise RuntimeError("positive size order failed: {}".format((dev["id"], voltages)))
        order_report[dev["id"]] = {"current": current, "voltages": voltages}

    if max_endpoint_error > 1e-8:
        raise RuntimeError("endpoint error too large: {}".format(max_endpoint_error))
    if min_endpoint_g <= 0.0:
        raise RuntimeError("non-positive endpoint conductance: {}".format(min_endpoint_g))

    print("PASS model recalibration compatibility")
    print("calibrations={}".format(calibration_count))
    print("max_endpoint_error={:.6e}".format(max_endpoint_error))
    print("min_endpoint_g={:.6e}".format(min_endpoint_g))
    print("local_fallback_count={}".format(fallback_count))
    print("positive_size_order={}".format(order_report))


if __name__ == "__main__":
    main()
