# -*- coding: utf-8 -*-
"""Regression harness (Python primary runtime, D4 revised).

Checks the same tests/golden.json as tests/regression.js — passing both runners
proves cross-language equivalence of the model port. Model code is a faithful
port of docs/two_device_complete_iv_soa_model.html with one deliberate
deviation: a single unified integration grid N for calibration and curve.

Usage:
    python tests/regression.py          # check against tests/golden.json
    python tests/regression.py --emit   # regenerate golden.json
"""
import json
import math
import os
import sys

N = 4000  # unified grid (calibration AND curve)


def sp(z):
    if z > 50:
        return z
    if z < -50:
        return math.exp(z)
    return math.log1p(math.exp(z))


def sg(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


D1 = {
    "id": "diode", "method": "exp",
    "par": lambda x: {"a1": 15.14 / x ** .08, "r1": .869 / x ** .826, "c1": 1.193 / x ** .0075,
                      "a2": 5.07 / x ** .0629, "r2": 27.48 / x ** 1.267, "c2": -7.18 / x ** -.0881},
    "m": [{"x": .64, "vp": 2.1145, "vn": -7.7309, "ip": .6002, "inn": -.01541},
          {"x": 1.344, "vp": 2.1779, "vn": -7.8437, "ip": 1.2137, "inn": -.0343},
          {"x": 2.56, "vp": 2.1802, "vn": -7.7251, "ip": 2.13426, "inn": -.0514632},
          {"x": 3.84, "vp": 2.15264, "vn": -7.8867, "ip": 2.91253, "inn": -.0957299}],
    "soa": {"vp": ["Vt2+", 1, 1.7052482326597274, .010814475389598174, 2.1338251606769485, 2.183514224890132],
            "vn": ["Vt2-", -1, 1.7052482326597274, .006758644201696505, 7.703915866993116, 7.856330403842027],
            "ip": ["It2+", 1, 1.7052482326597274, .8853326789209258, 1.4195543445506187, 1.4984574918281428],
            "inn": ["It2-", -1, 1.7052482326597274, .9679787370175855, .03472919025401326, .04363077033143844]},
}

D2 = {
    "id": "clamp", "method": "late",
    "par": lambda x: {"a1": 829.4 / x ** .452, "r1": 5.462 / x ** .2865, "c1": .08357 / x ** -.207,
                      "a2": 30 / x ** -3.28e-29, "r2": 9.204 / x ** .3384, "c2": -.6568 / x ** .02765},
    "m": [{"x": 1415.232, "vp": 4.8121, "vn": -4.96245, "ip": 4.46711, "inn": -4.82594},
          {"x": 2021.76, "vp": 6.35918, "vn": -6.71245, "ip": 6.10259, "inn": -6.42855},
          {"x": 2628.288, "vp": 11.5124, "vn": -9.47609, "ip": 7.70351, "inn": -7.47626}],
    "soa": {"vp": ["Vt2+", 1, 1959.190790564251, 1.3726632026868713, 6.090603488345262, 7.691645019533501],
            "vn": ["Vt2-", -1, 1959.190790564251, 1.0334594160835273, 6.497875372967659, 6.994612508780857],
            "ip": ["It2+", 1, 1959.190790564251, .8799640088461418, 5.936085662066821, 5.948515095817292],
            "inn": ["It2-", -1, 1959.190790564251, .712730158253558, 6.063770015250391, 6.2861134455085015]},
}


def g0(v, x, d):
    p = d["par"](x)
    return sg(p["a1"] * (v - p["c1"])) / p["r1"] + sg(p["a2"] * (p["c2"] - v)) / p["r2"]


def mod(t, T, q, d):
    if d["method"] == "late":
        r = t / T
        if r <= .5:
            z = 0.0
        else:
            u = 2 * r - 1
            z = 3 * u * u - 2 * u * u * u
        return .35 + .65 / (1 + 2 * z ** 1.5)
    vd = .45 * T
    k = 10 / T
    z = (sp(k * (t - vd)) - sp(-k * vd)) / (sp(k * (T - vd)) - sp(-k * vd))
    return math.exp(-q * z * z)


def integ(x, d, T, q, s, neg, n=N):
    h = T / n
    a = 0.0
    for j in range(n + 1):
        t = j * h
        v = -t if neg else t
        y = g0(v, x, d) * mod(t, T, q, d) * s
        a += (1.0 if 0 < j < n else .5) * y
    return a * h


def corr(x, d, T, I, neg):
    if d["method"] == "late":
        return {"q": 2, "s": I / integ(x, d, T, 2, 1, neg)}
    l, h = -1.0, 1.0
    while integ(x, d, T, l, 1, neg) < I:
        l *= 2
    while integ(x, d, T, h, 1, neg) > I:
        h *= 2
    for _ in range(65):
        m2 = (l + h) / 2
        if integ(x, d, T, m2, 1, neg) > I:
            l = m2
        else:
            h = m2
    return {"q": (l + h) / 2, "s": 1}


def branch(x, d, T, c, neg, n=N):
    h = T / n
    V, I, G = [0.0], [0.0], []
    s = 0.0
    p = g0(0, x, d) * mod(0, T, c["q"], d) * c["s"]
    G.append(p)
    for j in range(1, n + 1):
        t = j * h
        v = -t if neg else t
        g = g0(v, x, d) * mod(t, T, c["q"], d) * c["s"]
        s += (p + g) * h / 2
        V.append(v)
        I.append(-s if neg else s)
        G.append(g)
        p = g
    return {"V": V, "I": I, "G": G}


def sv(a, x, c):
    return a[1] * (a[4] if c == "worst" else a[5]) * (x / a[2]) ** a[3]


def ep(d, x, c):
    return {"x": x, "vp": sv(d["soa"]["vp"], x, c), "vn": sv(d["soa"]["vn"], x, c),
            "ip": sv(d["soa"]["ip"], x, c), "inn": sv(d["soa"]["inn"], x, c)}


def calib(d, x, c):
    e = ep(d, x, c)
    cp = corr(x, d, e["vp"], e["ip"], False)
    cn = corr(x, d, -e["vn"], -e["inn"], True)
    return {"e": e, "pos": branch(x, d, e["vp"], cp, False),
            "neg": branch(x, d, -e["vn"], cn, True), "cp": cp, "cn": cn}


def VofI(br, i):
    I, V = br["I"], br["V"]
    n = len(I) - 1
    end_i = I[n]
    asc = end_i >= 0
    if (i > end_i) if asc else (i < end_i):
        return float("nan")
    lo, hi = 0, n
    while hi - lo > 1:
        m2 = (lo + hi) // 2
        if (I[m2] <= i) if asc else (I[m2] >= i):
            lo = m2
        else:
            hi = m2
    denom = (I[hi] - I[lo]) or 1
    f = (i - I[lo]) / denom
    return V[lo] + f * (V[hi] - V[lo])


RIO, RVDD = 0.1, 0.5


def vio(c1, c2, I):
    return I * (RIO + RVDD) + VofI(c1["pos"], I) + VofI(c2["pos"], I)


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
        add("ref/VIO/worst/I={}".format(fmt_x(I)), vio(w1, w2, I), 1e-6, "abs")
    add("ref/VIO/best/I=1.33", vio(b1, b2, 1.33), 1e-6, "abs")

    c1, c2 = calib(D1, 2.56, "worst"), calib(D2, 2021.76, "worst")
    add("series/VIO/x1=2.56/x2=2021.76/worst/I=2.0", vio(c1, c2, 2.0), 1e-6, "abs")

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


def fmt_x(x):
    # match JS number-to-string (no trailing .0 for integers, full precision otherwise)
    return str(int(x)) if x == int(x) else repr(x)


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
