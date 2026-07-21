# -*- coding: utf-8 -*-
"""Sweep optimizer over the precomputed calibration table (v4-parity milestone).

Design variables (log-parameterized Adam): x1 (diode), x2 (clamp), L (Rvdd
metal length, D7: W fixed, R = 0.5 * L / 350um). Loss follows v4's structure
(cost + softplus penalties + separate hard PASS/FAIL) but with:
  - measured nonlinear models via the table (V(I; x), C1-extended beyond It2)
  - current-SOA usage I/It2(x) with nonzero gradient (dIt2/dx = p*It2/x)
  - both corners evaluated, per-metric pessimistic value (D3)
  - asymmetric rules (A/C min = harsh FAIL penalty, no projection; max = quasi
    rule; L window = process/EM origins) — numerical clamp only at D5 bounds
"""
import math

from server import model as M
from server import victim_soa as VS
from server.calibtable import get_table

SP_BETA = 30.0


def _sp(h):
    z = SP_BETA * h
    if z > 50:
        return h
    if z < -50:
        return 0.0
    return math.log1p(math.exp(z)) / SP_BETA


def _sig(z):
    z = max(-50.0, min(50.0, z))
    return 1.0 / (1.0 + math.exp(-z))


DEFAULTS = {
    # stress / victim (inverter drain via Resd; SOA from docs/victim_soa_model.html
    # — user-selected SG NFET + SG PFET, 1stk_1rx)
    "imax": 2.0, "npts": 41, "resd": 500.0, "vVon": 0.7,
    "vRonJ": 10.0, "bILim": 0.01, "vTopo": "1stk_1rx", "vgIn": 0.0,
    # rules (asymmetric: min = harsh, max = quasi(cap-driven))
    "x1min": 0.64, "x1max": 3.84, "x2min": 1415.232, "x2max": 2628.288,
    "lmin": 70.0, "lmax": 1400.0, "rio": 0.1,
    # initial condition
    "x1init": 2.56, "x2init": 1415.232, "linit": 350.0,
    # cost weights (normalized by max rule)
    "wA": 1.0, "wC": 1.0, "wL": 0.0,
    # cap / leakage axes (radar; real computed quantities with user coefficients)
    "capK1": 1.0, "capLim1": 8.0, "leakK1": 0.1, "leakLim1": 1.0,
    "capK2": 0.002, "capLim2": 8.0, "leakK2": 2e-4, "leakLim2": 1.0,
    # metal SOA (W fixed per D7 -> EM limit constant)
    "rVLim": 1.0, "iEM": 4.0, "pJoule": 2.0, "resLim": 4.0, "lref": 350.0,
    # optimizer
    "muSOA": 12.0, "muRule": 20.0, "lr": 0.03, "iters": 300, "logEvery": 25,
    "warmStart": 1,
}


def rvdd_of(L):
    return 0.5 * L / 350.0


def evaluate(tbl, p, I, x1, x2, L, it):
    rvdd = rvdd_of(L)
    vio_c, vd_c, vc_c = {}, {}, {}
    for corner in ("worst", "best"):
        vd = tbl.vofi("diode", corner, x1, I) if I > 0 else 0.0
        vc = tbl.vofi("clamp", corner, x2, I) if I > 0 else 0.0
        vd_c[corner], vc_c[corner] = vd, vc
        vio_c[corner] = I * (p["rio"] + rvdd) + vd + vc
    vio = max(vio_c.values())  # per-metric pessimistic (D3; corner inversion)
    # victim probe + SOA (inverter drain via Resd; SG NFET/PFET, user-set topology)
    vnds, iv, soa = 0.0, 0.0, None
    for corner in ("worst", "best"):
        vo, ivc = M.victim_probe(vio_c[corner], vc_c[corner], p["resd"], p["vVon"], p["vRonJ"])
        s = VS.inverter_victim(vo, vc_c[corner], p["vgIn"], topology=p["vTopo"])
        if soa is None or s["u"] > soa["u"]:
            soa = s
        vnds, iv = max(vnds, vo), max(iv, ivc)
    it2d = tbl.it2("diode", "worst", x1)
    it2c = tbl.it2("clamp", "worst", x2)
    vt2d = tbl.vt2("diode", "worst", x1)
    vt2c = tbl.vt2("clamp", "worst", x2)
    uV = soa["u"] if I > 0 else 0.0
    uID, uIC = I / it2d if I > 0 else 0.0, I / it2c if I > 0 else 0.0
    uVD = vd_c["worst"] / vt2d if I > 0 else 0.0
    uVC = vc_c["worst"] / vt2c if I > 0 else 0.0
    uBI = iv / p["bILim"] if I > 0 else 0.0
    # rule usages (positions)
    x1pos = (x1 - p["x1min"]) / (p["x1max"] - p["x1min"]) if p["x1max"] > p["x1min"] else 0.0
    x2pos = (x2 - p["x2min"]) / (p["x2max"] - p["x2min"]) if p["x2max"] > p["x2min"] else 0.0
    lpos = (L - p["lmin"]) / (p["lmax"] - p["lmin"]) if p["lmax"] > p["lmin"] else 0.0
    # metal usages (W fixed)
    uRV = I * rvdd / p["rVLim"]
    uEM = I / p["iEM"]
    uPJ = I * I * rvdd / p["pJoule"]
    uRes = (p["lref"] / L) / p["resLim"]
    # cap / leakage
    uCap1, uLeak1 = p["capK1"] * x1 / p["capLim1"], p["leakK1"] * x1 / p["leakLim1"]
    uCap2, uLeak2 = p["capK2"] * x2 / p["capLim2"], p["leakK2"] * x2 / p["leakLim2"]

    cost = p["wA"] * x1 / p["x1max"] + p["wC"] * x2 / p["x2max"] + p["wL"] * p["lref"] / L
    soa_pen = p["muSOA"] * (_sp(uV - 1) + _sp(uID - 1) + _sp(uIC - 1) + _sp(uBI - 1)
                            + _sp(uRV - 1) + _sp(uEM - 1) + _sp(uPJ - 1) + _sp(uRes - 1))
    rule_pen = p["muRule"] * (
        _sp((p["x1min"] - x1) / p["x1min"]) + _sp((x1 - p["x1max"]) / p["x1max"])
        + _sp((p["x2min"] - x2) / p["x2min"]) + _sp((x2 - p["x2max"]) / p["x2max"])
        + _sp((p["lmin"] - L) / p["lmin"]) + _sp((L - p["lmax"]) / p["lmax"]))
    loss = cost + soa_pen + rule_pen

    pass_v = uV <= 1 and uBI <= 1
    pass_d = uID <= 1
    pass_cl = uIC <= 1
    pass_metal = uRV <= 1 and uEM <= 1 and uPJ <= 1 and uRes <= 1
    pass_rule = (x1 >= p["x1min"] and x1 <= p["x1max"] and x2 >= p["x2min"]
                 and x2 <= p["x2max"] and L >= p["lmin"] and L <= p["lmax"])
    return {
        "it": it, "x1": x1, "x2": x2, "L": L, "R": rvdd,
        "vio": vio, "vio_w": vio_c["worst"], "vio_b": vio_c["best"],
        "vd": vd_c["worst"], "vc": vc_c["worst"], "vnds": vnds, "iv": iv,
        "vWorst": soa["worst"] if I > 0 else "-",
        "uVNt": soa["uN_term"] if I > 0 else 0.0, "uVNo": soa["uN_ox"] if I > 0 else 0.0,
        "uVPt": soa["uP_term"] if I > 0 else 0.0, "uVPo": soa["uP_ox"] if I > 0 else 0.0,
        "limNterm": soa["limN_term"], "limPterm": soa["limP_term"],
        "it2d": it2d, "it2c": it2c, "vt2d": vt2d, "vt2c": vt2c,
        "uV": uV, "uID": uID, "uIC": uIC, "uBI": uBI, "uVD": uVD, "uVC": uVC,
        "uRV": uRV, "uEM": uEM, "uPJ": uPJ, "uRes": uRes,
        "uCap1": uCap1, "uLeak1": uLeak1, "uCap2": uCap2, "uLeak2": uLeak2,
        "x1pos": x1pos, "x2pos": x2pos, "lpos": lpos,
        "cost": cost, "soaPen": soa_pen, "rulePen": rule_pen, "loss": loss,
        "passV": pass_v, "passD": pass_d, "passC": pass_cl,
        "passM": pass_metal, "passRule": pass_rule,
        "passAll": pass_v and pass_d and pass_cl and pass_metal and pass_rule,
    }


def _loss_only(tbl, p, I, y):
    x1, x2, L = math.exp(y[0]), math.exp(y[1]), math.exp(y[2])
    return evaluate(tbl, p, I, x1, x2, L, -1)["loss"]


# D5 numerical bounds (extrapolation window) — hard clamps in y-space
_YB = None


def _ybounds():
    global _YB
    if _YB is None:
        d_lo, d_hi = M.xwindow(M.D1)
        c_lo, c_hi = M.xwindow(M.D2)
        _YB = [(math.log(d_lo), math.log(d_hi)),
               (math.log(c_lo), math.log(c_hi)),
               (math.log(35.0), math.log(2800.0))]
    return _YB


def run_point(tbl, p, I, y0):
    yb = _ybounds()
    y = list(y0)
    m = [0.0] * 3
    v = [0.0] * 3
    b1, b2, eps = 0.9, 0.999, 1e-8
    rows = []
    iters = int(p["iters"])
    log_every = max(1, int(p["logEvery"]))
    h = 1e-4
    for it in range(iters + 1):
        x1, x2, L = math.exp(y[0]), math.exp(y[1]), math.exp(y[2])
        if it % log_every == 0 or it == iters:
            rows.append(evaluate(tbl, p, I, x1, x2, L, it))
        if it == iters:
            break
        g = [0.0] * 3
        for k in range(3):
            yp, ym = list(y), list(y)
            yp[k] += h
            ym[k] -= h
            g[k] = (_loss_only(tbl, p, I, yp) - _loss_only(tbl, p, I, ym)) / (2 * h)
        t = it + 1
        for k in range(3):
            m[k] = b1 * m[k] + (1 - b1) * g[k]
            v[k] = b2 * v[k] + (1 - b2) * g[k] * g[k]
            mh = m[k] / (1 - b1 ** t)
            vh = v[k] / (1 - b2 ** t)
            y[k] -= p["lr"] * mh / (math.sqrt(vh) + eps)
            y[k] = max(yb[k][0], min(yb[k][1], y[k]))
    return rows, y


def ipass_of(tbl, p, x1, x2, L):
    """First-fail current for a fixed design (victim SOA/current or device It2)."""
    ifail = min(tbl.it2("diode", "worst", x1), tbl.it2("clamp", "worst", x2))
    rvdd = rvdd_of(L)

    def victim_ok(i):
        for c in ("worst", "best"):
            vc = tbl.vofi("clamp", c, x2, i)
            vio = i * (p["rio"] + rvdd) + tbl.vofi("diode", c, x1, i) + vc
            vo, iv = M.victim_probe(vio, vc, p["resd"], p["vVon"], p["vRonJ"])
            s = VS.inverter_victim(vo, vc, p["vgIn"], topology=p["vTopo"])
            if s["u"] >= 1.0 or iv > p["bILim"]:
                return False
        return True
    if victim_ok(ifail):
        return ifail, ifail
    lo, hi = 0.0, ifail
    for _ in range(50):
        mid = (lo + hi) / 2
        if victim_ok(mid):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, ifail


def run_sweep(params):
    p = dict(DEFAULTS)
    for k, val in (params or {}).items():
        if k in p:
            p[k] = type(p[k])(val)
    if p["vTopo"] not in VS.TOPOLOGIES:
        p["vTopo"] = "1stk_1rx"
    tbl = get_table()
    n = int(p["npts"])
    y = [math.log(p["x1init"]), math.log(p["x2init"]), math.log(p["linit"])]
    out = []
    for j in range(n):
        I = p["imax"] * j / (n - 1.0)
        y0 = y if p["warmStart"] else [math.log(p["x1init"]), math.log(p["x2init"]), math.log(p["linit"])]
        rows, y_final = run_point(tbl, p, I, y0)
        if p["warmStart"]:
            y = y_final
        fin = rows[-1]
        ip, ifail = ipass_of(tbl, p, fin["x1"], fin["x2"], fin["L"])
        mm = ip / I if I > 0 else float("inf")
        fin["ipass"] = ip
        fin["ifail"] = ifail
        fin["M"] = mm if mm != float("inf") else None
        fin["tier"] = ("robust" if mm >= 1.5 else "recommended" if mm >= 1.2
                       else "minimum" if mm >= 1.0 else None)
        out.append({"I": I, "final": fin, "history": rows})
    return {"settings": p, "sweep": out}
