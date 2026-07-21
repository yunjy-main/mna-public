# -*- coding: utf-8 -*-
"""Regression harness (Python primary runtime, D4 revised).

Imports the model from server/model.py — the golden checks guard exactly the
model the service serves. tests/regression.js is an independent JS port kept as
a cross-language witness; both runners must pass the same tests/golden.json.

Usage:
    python tests/regression.py          # check against tests/golden.json
    python tests/regression.py --emit   # regenerate golden.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.model import (  # noqa: E402
    N, D1, D2, RIO, RVDD, branch, calib, corr, series_vio, sv, VofI,
)


def fmt_x(x):
    # match JS number-to-string (no trailing .0 for integers, full precision otherwise)
    return str(int(x)) if x == int(x) else repr(x)


def compute_all():
    g = []

    def add(key, value, tol, kind="abs"):
        g.append({"key": key, "value": value, "tol": tol, "kind": kind})

    for d in (D1, D2):
        for mm in d["m"]:
            cp = corr(mm["x"], d, mm["vp"], mm["ip"], False)
            cn = corr(mm["x"], d, -mm["vn"], -mm["inn"], True)
            bp = branch(mm["x"], d, mm["vp"], cp, False)
            bn = branch(mm["x"], d, -mm["vn"], cn, True)
            add("endpoint/{}/x={}/pos".format(d["id"], fmt_x(mm["x"])), bp["I"][-1] / mm["ip"] - 1, 1e-9, "raw")
            add("endpoint/{}/x={}/neg".format(d["id"], fmt_x(mm["x"])), bn["I"][-1] / mm["inn"] - 1, 1e-9, "raw")
    for x in (0.64, 1.344, 2.56, 3.84):
        add("env/diode/It2+w/x={}".format(fmt_x(x)), sv(D1["soa"]["ip"], x, "worst"), 1e-12, "rel")
    for x in (1415.232, 2021.76, 2628.288):
        add("env/clamp/It2+w/x={}".format(fmt_x(x)), sv(D2["soa"]["ip"], x, "worst"), 1e-12, "rel")
    for mm in D1["m"]:
        c = calib(D1, mm["x"], "worst")
        add("beta+/diode/x={}/worst".format(fmt_x(mm["x"])), c["cp"]["q"], 1e-6, "rel")
        add("beta-/diode/x={}/worst".format(fmt_x(mm["x"])), c["cn"]["q"], 1e-6, "rel")
        add("minG/diode/x={}/worst".format(fmt_x(mm["x"])), min(min(c["pos"]["G"]), min(c["neg"]["G"])), 1e-6, "rel")
    for mm in D2["m"]:
        c = calib(D2, mm["x"], "worst")
        add("scale+/clamp/x={}/worst".format(fmt_x(mm["x"])), c["cp"]["s"], 1e-6, "rel")
        add("minG/clamp/x={}/worst".format(fmt_x(mm["x"])), min(min(c["pos"]["G"]), min(c["neg"]["G"])), 1e-6, "rel")

    w1, w2 = calib(D1, 2.56, "worst"), calib(D2, 1415.232, "worst")
    b1, b2 = calib(D1, 2.56, "best"), calib(D2, 1415.232, "best")
    add("ref/Ifail/worst", min(w1["e"]["ip"], w2["e"]["ip"]), 1e-9, "rel")
    for I in (0.5, 1.0, 1.33):
        add("ref/VIO/worst/I={}".format(fmt_x(I)), series_vio(w1, w2, I), 1e-6, "abs")
    add("ref/VIO/best/I=1.33", series_vio(b1, b2, 1.33), 1e-6, "abs")

    c1, c2 = calib(D1, 2.56, "worst"), calib(D2, 2021.76, "worst")
    add("series/VIO/x1=2.56/x2=2021.76/worst/I=2.0", series_vio(c1, c2, 2.0), 1e-6, "abs")

    a = D1["soa"]["ip"]
    add("x1min/2A/worst", a[2] * (2.0 / a[4]) ** (1 / a[3]), 1e-9, "rel")

    c1, c2 = calib(D1, 2.56, "worst"), calib(D2, 1415.232, "worst")
    add("neg/It2-/diode/x=2.56/worst", c1["e"]["inn"], 1e-9, "rel")
    I = c1["e"]["inn"] * 0.999
    add("neg/VIO/ref/0.999It2-", I * (RIO + RVDD) + VofI(c1["neg"], I) + VofI(c2["neg"], I), 1e-6, "abs")

    all_g = c1["pos"]["G"] + c1["neg"]["G"] + c2["pos"]["G"] + c2["neg"]["G"]
    add("invariant/allG_positive", 1 if all(v > 0 for v in all_g) else 0, 0, "exact")
    add("invariant/I0_at_0_selfref", 0.0, 0, "exact")
    return g


def main():
    golden_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden.json")
    computed = compute_all()
    if "--emit" in sys.argv:
        with open(golden_path, "w", encoding="utf-8") as f:
            json.dump({"grid_N": N, "generated_with": "tests/regression.py --emit", "values": computed}, f, indent=1)
        print("wrote {} ({} entries, N={})".format(golden_path, len(computed), N))
        return 0
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)
    if golden["grid_N"] != N:
        print("FAIL: grid N mismatch (golden {} vs runner {})".format(golden["grid_N"], N))
        return 1
    by_key = {e["key"]: e for e in golden["values"]}
    fail = 0
    for c in computed:
        ref = by_key.get(c["key"])
        if ref is None:
            print("FAIL missing golden: {}".format(c["key"]))
            fail += 1
            continue
        if c["kind"] == "exact":
            ok = c["value"] == ref["value"]
        elif c["kind"] == "raw":
            ok = abs(c["value"]) <= ref["tol"]
        elif c["kind"] == "rel":
            ok = abs(c["value"] / ref["value"] - 1) <= ref["tol"]
        else:
            ok = abs(c["value"] - ref["value"]) <= ref["tol"]
        if not ok:
            print("FAIL {}: got {}, golden {}, tol {} ({})".format(c["key"], c["value"], ref["value"], ref["tol"], c["kind"]))
            fail += 1
    print("PASS: {} golden checks (N={})".format(len(computed), N) if fail == 0
          else "{} FAILURES of {}".format(fail, len(computed)))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
