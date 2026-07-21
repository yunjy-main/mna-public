# -*- coding: utf-8 -*-
"""Precomputed calibration table (Phase 1A asset).

Generates assets/calib_table.json: for each device x corner, a log-spaced x-grid
with calibrated positive/negative branch V(I) samples, beta/scale and endpoint
slope. At runtime V(I; x) is a log-x linear interpolation between neighboring
grid branches, with a C1 extension beyond It2 (V = Vt2 + (I - It2)/g_end) so
soft-penalty optimization stays finite in the infeasible region.

Generate:  python -m server.calibtable        (writes assets/calib_table.json)
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import model as M  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET = os.path.join(ROOT, "assets", "calib_table.json")
GRID_N = 48
SAMPLES = 160


def _downsample(br):
    V, I = br["V"], br["I"]
    n = len(V) - 1
    idx = [round(k * n / (SAMPLES - 1)) for k in range(SAMPLES)]
    return [V[k] for k in idx], [I[k] for k in idx]


def build():
    t0 = time.time()
    out = {"grid_n": GRID_N, "samples": SAMPLES, "model_N": M.N, "devices": {}}
    for dev in (M.D1, M.D2):
        lo, hi = M.xwindow(dev)
        xs = [lo * (hi / lo) ** (k / (GRID_N - 1.0)) for k in range(GRID_N)]
        dv = {"xs": xs, "corners": {}}
        for corner in ("worst", "best"):
            entries = []
            for x in xs:
                c = M.calib(dev, x, corner)
                pv, pi = _downsample(c["pos"])
                nv, ni = _downsample(c["neg"])
                entries.append({
                    "cal_p": c["cp"]["q"] if dev["method"] == "exp" else c["cp"]["s"],
                    "cal_n": c["cn"]["q"] if dev["method"] == "exp" else c["cn"]["s"],
                    "minG": min(min(c["pos"]["G"]), min(c["neg"]["G"])),
                    "gEnd_p": c["pos"]["G"][-1],
                    "gEnd_n": c["neg"]["G"][-1],
                    "pV": pv, "pI": pi, "nV": nv, "nI": ni,
                })
            dv["corners"][corner] = entries
            print("{} {}: {} grid points ({:.1f}s)".format(dev["id"], corner, GRID_N, time.time() - t0))
        out["devices"][dev["id"]] = dv
    os.makedirs(os.path.dirname(ASSET), exist_ok=True)
    with open(ASSET, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print("wrote {} ({:.1f} MB, {:.1f}s)".format(ASSET, os.path.getsize(ASSET) / 1e6, time.time() - t0))


class Table(object):
    """Runtime interpolator over the precomputed grid."""

    def __init__(self, path=ASSET):
        with open(path, "r", encoding="utf-8") as f:
            self.d = json.load(f)
        self._dev = {"diode": M.D1, "clamp": M.D2}

    @staticmethod
    def _branch_v(entry, i, pos=True):
        V = entry["pV"] if pos else entry["nV"]
        I = entry["pI"] if pos else entry["nI"]
        n = len(I) - 1
        end_i, end_v = I[n], V[n]
        g_end = entry["gEnd_p"] if pos else entry["gEnd_n"]
        asc = end_i >= 0
        if (i > end_i) if asc else (i < end_i):
            return end_v + (i - end_i) / g_end  # C1 extension beyond endpoint
        lo, hi = 0, n
        while hi - lo > 1:
            m2 = (lo + hi) // 2
            if (I[m2] <= i) if asc else (I[m2] >= i):
                lo = m2
            else:
                hi = m2
        f = (i - I[lo]) / ((I[hi] - I[lo]) or 1)
        return V[lo] + f * (V[hi] - V[lo])

    def _neighbors(self, dev_id, x):
        xs = self.d["devices"][dev_id]["xs"]
        if x <= xs[0]:
            return 0, 0, 0.0
        if x >= xs[-1]:
            return len(xs) - 1, len(xs) - 1, 0.0
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            m2 = (lo + hi) // 2
            if xs[m2] <= x:
                lo = m2
            else:
                hi = m2
        w = (math.log(x) - math.log(xs[lo])) / (math.log(xs[hi]) - math.log(xs[lo]))
        return lo, hi, w

    def vofi(self, dev_id, corner, x, i, pos=True):
        """V(I; x) via log-x interpolation of calibrated branches (C1-extended)."""
        j0, j1, w = self._neighbors(dev_id, x)
        es = self.d["devices"][dev_id]["corners"][corner]
        v0 = self._branch_v(es[j0], i, pos)
        if j1 == j0:
            return v0
        return (1 - w) * v0 + w * self._branch_v(es[j1], i, pos)

    def it2(self, dev_id, corner, x):
        return M.sv(self._dev[dev_id]["soa"]["ip"], x, corner)

    def vt2(self, dev_id, corner, x):
        return M.sv(self._dev[dev_id]["soa"]["vp"], x, corner)

    def it2n(self, dev_id, corner, x):
        return M.sv(self._dev[dev_id]["soa"]["inn"], x, corner)


_table = None


def get_table():
    global _table
    if _table is None:
        _table = Table()
    return _table


if __name__ == "__main__":
    build()
