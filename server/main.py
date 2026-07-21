# -*- coding: utf-8 -*-
"""Minimal FastAPI seed for the mna service (port 8807, route /apps/mna).

Phase 2 will grow this into the solver API. For now:
  /apps/mna/                  landing page (frontend/index.html)
  /apps/mna/api/meta          identity + status (healthMatch: mna-esd-solver)
  /apps/mna/api/regression    run tests/regression.py, return result
  /apps/mna/ref/<path>.html   read-only reference HTML artifacts (root, docs/)

Run: python -m uvicorn server.main:app --host 127.0.0.1 --port 8807  (cwd = repo root)
"""
import os
import subprocess
import sys

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

from server import model as M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "/apps/mna"

app = FastAPI(title="mna-esd-solver", docs_url=None, redoc_url=None)


def _refs():
    out = []
    for d in (ROOT, os.path.join(ROOT, "docs")):
        for f in sorted(os.listdir(d)):
            if f.endswith(".html"):
                out.append(os.path.relpath(os.path.join(d, f), ROOT).replace("\\", "/"))
    return out


@app.get(PREFIX + "/api/meta")
def meta():
    return {
        "app": "mna-esd-solver",
        "version": "0.0.1",
        "phase": "0 — regression baseline (tests/golden.json, 50 checks)",
        "runtime": "python {} / fastapi".format(sys.version.split()[0]),
        "refs": _refs(),
    }


@app.get(PREFIX + "/api/regression")
def regression():
    p = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tests", "regression.py")],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
    )
    return {"exit": p.returncode, "output": (p.stdout + p.stderr).strip()}


_models_cache = {}


def _downsample_curve(cal, step=16):
    """Merge neg branch (reversed) + pos branch into one V/I polyline, downsampled."""
    nv = cal["neg"]["V"][::-1]
    ni = cal["neg"]["I"][::-1]
    pv, pi = cal["pos"]["V"], cal["pos"]["I"]
    V = nv + pv[1:]
    I = ni + pi[1:]
    keep = list(range(0, len(V), step))
    if keep[-1] != len(V) - 1:
        keep.append(len(V) - 1)
    return {"V": [V[k] for k in keep], "I": [I[k] for k in keep]}


@app.get(PREFIX + "/api/models")
def models(x1: float = 2.56, x2: float = 1415.232):
    """Device I-V / SOA envelope / victim series-path data for the display screen.

    Corners: both worst and best (decision D3). x windows: measured +-50% (D5).
    """
    key = (round(x1, 6), round(x2, 6))
    if key in _models_cache:
        return _models_cache[key]

    for dev, x in ((M.D1, x1), (M.D2, x2)):
        lo, hi = M.xwindow(dev)
        if not (lo <= x <= hi):
            return PlainTextResponse(
                "{} x={} outside D5 window [{:.4g}, {:.4g}]".format(dev["id"], x, lo, hi),
                status_code=422)

    out = {"x1": x1, "x2": x2, "victim": {"kV": 1.0, "vfail": 4.0},
           "rio": M.RIO, "rvdd": M.RVDD, "devices": {}, "soa": {}, "path": {}}
    cals = {}
    for dev, x in ((M.D1, x1), (M.D2, x2)):
        entry = {"x": x, "measured_range": dev["range"], "window": M.xwindow(dev)}
        for corner in ("worst", "best"):
            c = M.calib(dev, x, corner)
            cals[(dev["id"], corner)] = c
            cal_info = ({"beta_p": c["cp"]["q"], "beta_n": c["cn"]["q"]} if dev["method"] == "exp"
                        else {"scale_p": c["cp"]["s"], "scale_n": c["cn"]["s"]})
            entry[corner] = {
                "curve": _downsample_curve(c),
                "ep": c["e"],
                "cal": cal_info,
                "minG": min(min(c["pos"]["G"]), min(c["neg"]["G"])),
            }
        out["devices"][dev["id"]] = entry

    for dev in (M.D1, M.D2):
        lo, hi = M.xwindow(dev)
        xs = [lo * (hi / lo) ** (i / 79.0) for i in range(80)]
        qmap = {"vp": "vp", "vn": "vn", "ip": "ip", "inn": "inn"}
        env = {}
        for qk in qmap:
            a = dev["soa"][qk]
            env[qk] = {
                "label": a[0], "xs": xs,
                "worst": [M.sv(a, x, "worst") for x in xs],
                "best": [M.sv(a, x, "best") for x in xs],
                "anchors": [{"x": mm["x"], "y": mm[qk]} for mm in dev["m"]],
                "measured_range": dev["range"],
            }
        out["soa"][dev["id"]] = env

    for corner in ("worst", "best"):
        c1, c2 = cals[("diode", corner)], cals[("clamp", corner)]
        ifail = min(c1["e"]["ip"], c2["e"]["ip"])
        limiter = "diode" if c1["e"]["ip"] < c2["e"]["ip"] else "clamp"
        Is = [ifail * 0.999 * i / 59.0 for i in range(60)]
        vios = [M.series_vio(c1, c2, i) for i in Is]
        vfail = out["victim"]["vfail"]
        icross = None
        for a, b in zip(range(59), range(1, 60)):
            if (vios[a] - vfail) * (vios[b] - vfail) <= 0 and vios[a] != vios[b]:
                icross = Is[a] + (vfail - vios[a]) * (Is[b] - Is[a]) / (vios[b] - vios[a])
                break
        out["path"][corner] = {
            "I": Is, "VIO": vios, "Ifail": ifail, "limiter": limiter,
            "hbm_kv": ifail * 1.5, "victim_cross_I": icross,
        }

    _models_cache[key] = out
    return out


@app.get(PREFIX + "/models")
def models_page():
    return FileResponse(os.path.join(ROOT, "frontend", "models.html"))


@app.get(PREFIX + "/ref/{path:path}")
def ref(path: str):
    cand = os.path.normpath(os.path.join(ROOT, path))
    allowed = os.path.dirname(cand) in (ROOT, os.path.join(ROOT, "docs"))
    if not (cand.endswith(".html") and allowed and os.path.isfile(cand)):
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(cand)


@app.get(PREFIX + "/")
@app.get(PREFIX)
def index():
    return FileResponse(os.path.join(ROOT, "frontend", "index.html"))


@app.get("/")
def root():
    return RedirectResponse(PREFIX + "/")
