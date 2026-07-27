# -*- coding: utf-8 -*-
"""Minimal FastAPI seed for the mna service (port 8807, route /apps/mna).

Phase 2 will grow this into the solver API. For now:
  /apps/mna/                  landing page (frontend/index.html)
  /apps/mna/api/meta          identity + status (healthMatch: mna-esd-solver)
  /apps/mna/api/regression    run tests/regression.py, return result
  /apps/mna/ref/<path>.html   read-only reference HTML artifacts (root, docs/)

Run: python -m uvicorn server.main:app --host 127.0.0.1 --port 8807  (cwd = repo root)
"""
import json
import os
import subprocess
import sys

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response

from server import model as M
from server import victim_soa as VS

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
        "version": "0.3.2",
        "phase": "1A(테이블)+2(직렬 optimizer) 부분 — v4-parity optimizer + display screens",
        "runtime": "python {} / fastapi".format(sys.version.split()[0]),
        "refs": _refs(),
    }


@app.get(PREFIX + "/api/regression")
def regression():
    outputs, code = [], 0
    for script in ("regression.py", "founding_benchmarks.py", "test_calibtable.py",
                   "test_victim_probe.py", "test_victim_soa.py"):
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tests", script)],
            capture_output=True, text=True, cwd=ROOT, timeout=300,
        )
        outputs.append("[{}] {}".format(script, (p.stdout + p.stderr).strip()))
        code = code or p.returncode
    return {"exit": code, "output": "\n".join(outputs)}


A_PER_KV = 1.33  # user-fixed spec rule (D9 revised): ESD 1 kV <-> 1.33 A
# victim = PMOS+NMOS inverter, drain node via Resd from IO (user-fixed topology).
# SOA from docs/victim_soa_model.html — user-selected SG NFET + SG PFET, 1stk_1rx.
VICTIM = {"ifail": 0.01, "resd": 500.0, "von": 0.7, "ronj": 10.0,
          "nmos": "SG_NFET", "pmos": "SG_PFET", "topology": "1stk_1rx"}
# gate = OUT (diode-connected — Resd 우측 node가 inverter gate에도 연결, 사용자 지시)
NAMED_SPEC_KV = 1.0  # the named ESD spec level (1 kV <-> 1.33 A)


def _victim_soa(v_out, vdd_local, vss_local=0.0):
    return VS.inverter_victim(v_out, vdd_local, v_out,  # gate = OUT (diode-connected)
                              VICTIM["nmos"], VICTIM["pmos"], VICTIM["topology"],
                              vss_local=vss_local)

def _page(name):
    """Serve a frontend page with no-store so UI updates are never cache-stale."""
    return FileResponse(os.path.join(ROOT, "frontend", name),
                        headers={"Cache-Control": "no-store"})


@app.get(PREFIX + "/static/{path:path}")
def static_file(path: str):
    """Shared design-system assets (style.css / charts.js), no-store like pages."""
    cand = os.path.normpath(os.path.join(ROOT, "frontend", "static", path))
    ok = (os.path.dirname(cand) == os.path.join(ROOT, "frontend", "static")
          and cand.endswith((".css", ".js")) and os.path.isfile(cand))
    if not ok:
        return PlainTextResponse("not found", status_code=404)
    return FileResponse(cand, headers={"Cache-Control": "no-store"})


_models_cache = {}
_calib_cache = {}


def _cal(dev, x, corner):
    key = (dev["id"], round(x, 9), corner)
    if key not in _calib_cache:
        _calib_cache[key] = M.calib(dev, x, corner)
    return _calib_cache[key]


def _window_error(x1, x2):
    for dev, x in ((M.D1, x1), (M.D2, x2)):
        lo, hi = M.xwindow(dev)
        if not (lo <= x <= hi):
            return PlainTextResponse(
                "{} x={} outside D5 window [{:.4g}, {:.4g}]".format(dev["id"], x, lo, hi),
                status_code=422)
    return None


def _GofI(br, i):
    """Interpolate branch conductance at a given current (None beyond endpoint)."""
    I, G = br["I"], br["G"]
    n = len(I) - 1
    asc = I[n] >= 0
    if (i > I[n]) if asc else (i < I[n]):
        return None
    lo, hi = 0, n
    while hi - lo > 1:
        m2 = (lo + hi) // 2
        if (I[m2] <= i) if asc else (I[m2] >= i):
            lo = m2
        else:
            hi = m2
    f = (i - I[lo]) / ((I[hi] - I[lo]) or 1)
    return G[lo] + f * (G[hi] - G[lo])


def _victim_probe_at(c1, c2, i):
    """Inverter victim probe on the solved series path: (v_out, i_v, n3_abs, vssr).
    n3 = clamp top (victim PMOS ref) = Vclamp + node A + RDD_dn1 강하; vssr = node A (NMOS ref)."""
    vssr = i * M.RVSS_RDL
    vc = M.VofI(c2["pos"], i)
    n3 = vc + vssr + i * M.RDD_DN1
    vio = i * (M.RIO_RDL + M.RDD_UN1 + M.RDD_DN1 + M.RVSS_RDL) + M.VofI(c1["pos"], i) + vc
    vo, iv = M.victim_probe(vio, n3, VICTIM["resd"], VICTIM["von"], VICTIM["ronj"])
    return vo, iv, n3, vssr


def _victim_cross(c1, c2, _unused=None):
    """Bisect the smallest I where the victim SOA/current fails (None if never)."""
    ifail = min(c1["e"]["ip"], c2["e"]["ip"])

    def ok(i):
        vo, iv, n3, vssr = _victim_probe_at(c1, c2, i)
        return _victim_soa(vo, n3, vssr)["u"] < 1.0 and iv <= VICTIM["ifail"]
    if ok(ifail):
        return None, ifail
    lo, hi = 0.0, ifail
    for _ in range(60):
        mid = (lo + hi) / 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2, ifail


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

    err = _window_error(x1, x2)
    if err:
        return err

    out = {"x1": x1, "x2": x2, "victim": dict(VICTIM),
           "rio": M.RIO, "rdd_un1": M.RDD_UN1, "rdd_dn1": M.RDD_DN1,
           "devices": {}, "soa": {}, "path": {}}
    out["victim"]["limN_term"] = VS.TERMINAL_VFAIL[VICTIM["nmos"]][VICTIM["topology"]]
    out["victim"]["limP_term"] = VS.TERMINAL_VFAIL[VICTIM["pmos"]][VICTIM["topology"]]
    cals = {}
    for dev, x in ((M.D1, x1), (M.D2, x2)):
        entry = {"x": x, "measured_range": dev["range"], "window": M.xwindow(dev)}
        for corner in ("worst", "best"):
            c = _cal(dev, x, corner)
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
        vios, vnds_l, iv_l, u_l = [], [], [], []
        for i in Is:
            vssr = i * M.RVSS_RDL
            vc = M.VofI(c2["pos"], i)
            n3 = vc + vssr + i * M.RDD_DN1
            vio_i = i * (M.RIO_RDL + M.RDD_UN1 + M.RDD_DN1 + M.RVSS_RDL) + M.VofI(c1["pos"], i) + vc
            vo, iv = M.victim_probe(vio_i, n3, VICTIM["resd"], VICTIM["von"], VICTIM["ronj"])
            vios.append(vio_i)
            vnds_l.append(vo)
            iv_l.append(iv)
            u_l.append(_victim_soa(vo, n3, vssr)["u"])
        icross = None
        for a, b in zip(range(59), range(1, 60)):
            if (u_l[a] - 1.0) * (u_l[b] - 1.0) <= 0 and u_l[a] != u_l[b]:
                icross = Is[a] + (1.0 - u_l[a]) * (Is[b] - Is[a]) / (u_l[b] - u_l[a])
                break
        out["path"][corner] = {
            "I": Is, "VIO": vios, "VNDS": vnds_l, "IV": iv_l, "U": u_l,
            "Ifail": ifail, "limiter": limiter,
            "hbm_kv": ifail / A_PER_KV, "victim_cross_I": icross,
        }

    _models_cache[key] = out
    return out


@app.get(PREFIX + "/api/circuit")
def circuit(x1: float = 2.56, x2: float = 1415.232, i: float = A_PER_KV, corner: str = "worst"):
    """Text circuit diagram + node/branch list + MNA matrix meta at an operating point."""
    err = _window_error(x1, x2)
    if err:
        return err
    if corner not in ("worst", "best"):
        return PlainTextResponse("corner must be worst|best", status_code=422)
    c1, c2 = _cal(M.D1, x1, corner), _cal(M.D2, x2, corner)
    ifail = min(c1["e"]["ip"], c2["e"]["ip"])
    op = None
    if 0 <= i <= ifail:
        v1, v2 = M.VofI(c1["pos"], i), M.VofI(c2["pos"], i)
        rdd = 0.5 * 350.0 / 350.0  # 기준 L=350 → RDD_un1 = RDD_dn1 = 0.5Ω (표시용)
        vssr = i * M.RVSS_RDL             # VSS rail node A (victim NMOS ref)
        n3b = vssr + i * M.RDD_DN1        # clamp bottom = node A + RDD_dn1 강하
        n3_abs = v2 + n3b                 # clamp top (victim PMOS source)
        vio_v = i * (M.RIO_RDL + M.RDD_UN1 + M.RDD_DN1 + M.RVSS_RDL) + v1 + v2
        vout, iv = M.victim_probe(vio_v, n3_abs, VICTIM["resd"], VICTIM["von"], VICTIM["ronj"])
        gD, gC = _GofI(c1["pos"], i), _GofI(c2["pos"], i)
        gRio, gRun1, gRdn1 = 1 / M.RIO_RDL, 1 / M.RDD_UN1, 1 / M.RDD_DN1
        gRe = 1.0 / VICTIM["resd"]
        gJ = (1.0 / VICTIM["ronj"]) if iv > 0 else 0.0  # PMOS drain junction (on/off)
        # unknowns: V(IO) V(N1) V(N2) V(N3=clamp top) V(N3B=clamp bottom) V(OUT); ref=VSS
        matrix = [
            [gRio + gRe, -gRio, 0, 0, 0, -gRe],
            [-gRio, gRio + gD, -gD, 0, 0, 0],
            [0, -gD, gD + gRun1, -gRun1, 0, 0],
            [0, 0, -gRun1, gRun1 + gC + gJ, -gC, -gJ],
            [0, 0, 0, -gC, gC + gRdn1, 0],
            [-gRe, 0, 0, -gJ, 0, gRe + gJ],
        ]
        op = {"i": i, "v_diode": v1, "v_clamp": v2, "v_io": vio_v,
              "v_out": vout, "i_victim": iv, "v_vssr": vssr, "v_n3b": n3b,
              "gD": gD, "gC": gC, "gRio": gRio, "gRun1": gRun1, "gRdn1": gRdn1,
              "gResd": gRe, "gJ": gJ,
              "matrix": matrix, "b": [i, 0, 0, 0, 0, 0]}
    ascii_lines = [
        " VDD ○────────○ N2 ──────/\\/\\/\\ RDD_un1 0.5Ω(≈350µm) ─────── ○ N3 ─────────○ VDD",
        "              ▲                                               │        ┌────┴─┐",
        "           D_up(x1)                                       Clamp(x2)    │ PMOS │ (source→VDD)",
        "              │                                               │        └──┬───┘ drain",
        "  IO ○──/\\/\\ Rio_rdl 0.1Ω ──○ N1                              ○ N3B        │",
        "   │          │                                               │   OUT ○───┤ ← Resd 500Ω ─── IO",
        "  (I_ESD ↑)   ▼                                       RDD_dn1 0.5Ω        ┌──┴───┐ drain",
        "           D_down(x1 미러, D2)                                 │        │ NMOS │ (source→VSS rail)",
        "              │                                       node A ○─┘        └──┬───┘",
        " VSS ○──/\\/\\ Rvss_rdl 0.1Ω ──○───────────────────────────────┴─────────────○ VSS (ref)",
        "",
        " victim = PMOS+NMOS inverter: IO ─Resd(500Ω)→ OUT(공통 drain). NMOS drain 스트레스 = V(OUT).",
        " 양(+) 스트레스: IO→Rio_rdl→D_up→RDD_un1→Clamp→RDD_dn1→Rvss_rdl→VSS 가 주 경로,",
        "                 OUT은 PMOS drain 접합 순방향으로 완화. clamp top(N3)=Vclamp+I·(RDD_dn1+Rvss_rdl).",
        " 음(−) 스트레스: IO→D_down 경로 (모델은 model1 미러 — D2).",
        " DD 금속(device-to-device) 규칙: 0.5Ω / 350µm, RDD_un1·RDD_dn1 공유 L (L만 설계변수, W 고정 — D7)",
    ]
    return {
        "ascii": ascii_lines,
        "x1": x1, "x2": x2, "corner": corner,
        "nodes": [
            {"name": "IO", "role": "PAD — stress 주입 node (current source)"},
            {"name": "N1", "role": "Rio_rdl 뒤 diode tap (D_up anode / D_down cathode)"},
            {"name": "N2", "role": "VDD rail — D_up cathode / RDD_un1 좌단"},
            {"name": "N3", "role": "VDD rail — Clamp top (victim PMOS source 인접)"},
            {"name": "N3B", "role": "VSS rail — Clamp bottom (RDD_dn1 → node A)"},
            {"name": "OUT", "role": "victim inverter 공통 drain (IO에서 Resd 경유)"},
            {"name": "VSS", "role": "기준(ref) node — MNA 미지수에서 제외 (node A ≈ VSS, Rvss_rdl 리턴)"},
        ],
        "branches": [
            {"name": "I_ESD", "type": "source", "nodes": "IO→VSS", "param": "spec 전류 (1kV↔1.33A)"},
            {"name": "Rio_rdl", "type": "device — R (RDL)", "nodes": "IO port–N1", "param": "0.1Ω"},
            {"name": "Rvdd_rdl", "type": "device — R (RDL)", "nodes": "VDD port–N2", "param": "0.1Ω (양(+) 스트레스 무전류)"},
            {"name": "Rvss_rdl", "type": "device — R (RDL)", "nodes": "node A–VSS port", "param": "0.1Ω (리턴 경로)"},
            {"name": "D_up", "type": "device — diode (model1)", "nodes": "N1→N2", "param": "x1={}".format(x1)},
            {"name": "D_down", "type": "device — diode (model1 미러, D2)", "nodes": "VSS→N1", "param": "x1 미러 — 음(−) 스트레스 경로"},
            {"name": "RDD_un1", "type": "device — R (DD 금속)", "nodes": "N2–N3", "param": "0.5Ω (≈350µm), up diode↔clamp, L 변수(D7)"},
            {"name": "RDD_dn1", "type": "device — R (DD 금속)", "nodes": "N3B–node A", "param": "0.5Ω (≈350µm), down diode↔clamp, 공유 L(D7)"},
            {"name": "Clamp", "type": "device — clamp (model2)", "nodes": "N3–N3B", "param": "x2={}".format(x2)},
            {"name": "Resd", "type": "device — R (ESD 직렬)", "nodes": "IO–OUT", "param": "500Ω (victim 보호)"},
            {"name": "PMOS drain 접합", "type": "device — FET 접합 (victim)", "nodes": "OUT→N3", "param": "Von 0.7 + Ron 10Ω, 양(+) 스트레스 시 순방향"},
            {"name": "NMOS drain 접합", "type": "device — FET (victim, SG 1stk_1rx SOA)", "nodes": "OUT→VSS", "param": "terminal 3.1V · oxide inv/acc 2.9/3.3V"},
            {"name": "Gate tie", "type": "wire", "nodes": "OUT–G(PMOS·NMOS)", "param": "diode-connected — V_G = V(OUT), oxide 검사 기준"},
        ],
        "mna": {
            "unknowns": ["V(IO)", "V(N1)", "V(N2)", "V(N3)", "V(N3B)", "V(OUT)"],
            "ref": "VSS", "size": "6×6", "nnz": "18 / 36",
            "form": "G(v)·Δv = −F(v)  (Newton 일반형, Phase 4)",
            "solve_mode": "현재: 주 경로는 전류구동 1D 역산, victim은 지배경로 근사 post-process probe "
                          "(Resd 500Ω ≫ 경로 저항이라 victim 전류 mA급 — 주 경로 교란 없음)",
        },
        "op": op, "ifail": ifail,
        "victim": dict(VICTIM),
    }


@app.get(PREFIX + "/api/spec")
def spec(x1: float = 2.56, x2: float = 1415.232):
    """ESD spec table: kV levels -> injected current (1kV=1.33A) -> PASS/FAIL per corner."""
    err = _window_error(x1, x2)
    if err:
        return err
    out = {"a_per_kv": A_PER_KV, "victim": dict(VICTIM), "x1": x1, "x2": x2,
           "rio": M.RIO, "rdd_un1": M.RDD_UN1, "rdd_dn1": M.RDD_DN1,
           "tiers": {"minimum": 1.0, "recommended": 1.2, "robust": 1.5},
           "levels": [], "summary": {}}
    cs, ipass = {}, {}
    for corner in ("worst", "best"):
        c1, c2 = _cal(M.D1, x1, corner), _cal(M.D2, x2, corner)
        cross, ifail = _victim_cross(c1, c2)
        cs[corner] = (c1, c2)
        ip = cross if cross is not None else ifail  # first-fail current (victim or device SOA)
        ipass[corner] = ip
        out["summary"][corner] = {
            "ifail": ifail,
            "limiter": "diode" if c1["e"]["ip"] < c2["e"]["ip"] else "clamp",
            "victim_cross_I": cross,
            "ipass": ip,
            "max_kv_victim": ip / A_PER_KV,
            "max_kv_soa": ifail / A_PER_KV,
            # 3-tier solution system (founding spec): M = Ipass / I_target
            "kv_minimum": ip / (1.0 * A_PER_KV),
            "kv_recommended": ip / (1.2 * A_PER_KV),
        }
    # robust tier: worst corner with M >= 1.5 (founding spec: worst-condition pass)
    ip_overall = min(ipass["worst"], ipass["best"])
    out["summary"]["overall"] = {
        "ipass": ip_overall,
        "kv_minimum": ip_overall / (1.0 * A_PER_KV),
        "kv_recommended": ip_overall / (1.2 * A_PER_KV),
        "kv_robust": ip_overall / (1.5 * A_PER_KV),
    }
    for kv in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        i = A_PER_KV * kv
        row = {"kv": kv, "i": i, "named_spec": kv == NAMED_SPEC_KV, "corners": {}}
        for corner in ("worst", "best"):
            c1, c2 = cs[corner]
            ifail = min(c1["e"]["ip"], c2["e"]["ip"])
            mm = ipass[corner] / i  # margin ratio M for this level
            tier = ("robust" if mm >= 1.5 else "recommended" if mm >= 1.2
                    else "minimum" if mm >= 1.0 else None)
            if i > ifail:
                row["corners"][corner] = {"status": "FAIL_SOA", "vio": None, "m": mm, "tier": tier,
                                          "note": "I > It2 (경로 파괴, Ifail={:.3f}A)".format(ifail)}
            else:
                v = M.series_vio(c1, c2, i)
                vnds, iv, n3_loc, vssr_loc = _victim_probe_at(c1, c2, i)
                soa = _victim_soa(vnds, n3_loc, vssr_loc)
                ok = soa["u"] < 1.0 and iv <= VICTIM["ifail"]
                row["corners"][corner] = {"status": "PASS" if ok else "FAIL_VICTIM", "vio": v,
                                          "vnds": vnds, "iv": iv,
                                          "u_soa": soa["u"], "worst_check": soa["worst"],
                                          "m": mm, "tier": tier,
                                          "usage_diode": i / c1["e"]["ip"], "usage_clamp": i / c2["e"]["ip"]}
        out["levels"].append(row)
    return out


@app.get(PREFIX + "/api/entities")
def entities():
    """Entity catalog (20 items) with implementation status and where to see each one."""
    IMPL, PART, PLAN = "구현", "부분", "계획"
    items = [
        (1, "DeviceModel", IMPL, "server/model.py · 화면: models", "diode/clamp Softplus+보정, 골든 50건이 직접 검증. R 계열(Rio_rdl/RDD_un1/RDD_dn1/Resd)도 device로 취급(사용자 규정) — #3이 R-device 담당"),
        (2, "SOAEnvelope & CornerPolicy", PART, "server/model.py · 화면: models §3, spec", "envelope 8종+양 corner(D3)+±50% 창(D5)+3단계 해(M=1.0/1.2/1.5, 창립 스펙); curve-endpoint 규약 문서화 예정"),
        (3, "MetalModel (R-device)", PART, "화면: circuit, optimize", "R 계열도 device(사용자 규정): Rio_rdl·RDD_un1/RDD_dn1(DD 금속, 0.5Ω/350µm·공유 L 변수)·Rvss_rdl·Resd(ESD 직렬 500Ω). EM/Joule/자원 SOA 보유"),
        (4, "VictimModel", IMPL, "server/victim_soa.py · docs/victim_soa_model.html · 화면: circuit, models §2, spec, optimize", "inverter(IO─Resd 500Ω→OUT) + 측정 SOA: SG NFET/PFET 1stk_1rx(터미널 3.1/3.3V, oxide inv/acc 2.9/3.3·3.3/3.8V), 부호 있는 VGS/VGD/VGB 검사, Uoverall=max. 음(−) 스트레스 대칭은 잔여"),
        (5, "CalibrationPipeline", PART, "server/calibtable.py · assets/calib_table.json", "β/scale·V(I) 사전계산 테이블(48격자×2corner, rel<5e-3) 구현; anchor 절차 코드화 잔여"),
        (6, "Netlist/Topology", PART, "화면: circuit", "강화 토폴로지: VDD/IO/VSS 레일 + up/down diode + clamp + victim inverter(노드 5+ref, MNA 5×5); 일반화는 Phase 5"),
        (7, "StressCase & ESDSpec", PART, "화면: spec", "HBM 양(+) 스트레스 1종, 1kV↔1.33A(사용자 확정)"),
        (8, "DesignVariableRegistry", PART, "api/models 422 가드", "x1/x2 + D5 ±50% 창; L 변수는 Phase 2. 창립 rule 비대칭: A/C min=가혹 FAIL(projection 금지), max=성능 준-rule, R min=공정한계/max=EM·Joule"),
        (9, "ProblemSchema (JSON/YAML)", PLAN, "Phase 1A~", "GUI↔solver 경계 계약"),
        (10, "TopologyCompiler", PLAN, "Phase 5", "flatten + hierarchy + Top Cell SOA 집계"),
        (11, "MNAAssembler", PART, "화면: circuit (심볼릭+수치 G 미리보기)", "실제 조립/solve는 Phase 4"),
        (12, "NewtonSolver", PART, "server/model.py VofI", "직렬 fast path(1D 역산)만 구현; 일반 Newton은 Phase 4"),
        (13, "SensitivityEngine", PLAN, "Phase 3", "완전 미분 체인(β/scale/endpoint 포함) — 공식 검증 완료"),
        (14, "LossFunction", PLAN, "Phase 3", "usage 정규화 + cost 승계"),
        (15, "Optimizer", PART, "server/optimizer.py · 화면: optimize", "테이블 기반 Adam(log-공간, 수치 gradient) + warm-start sweep + I>It2 C¹ 연장 + corner 양쪽 loss. 완전 미분 체인·2단계 loss·multi-start는 Phase 3 잔여"),
        (16, "PassFailEvaluator", PART, "화면: spec, models §2", "victim/SOA 판정, corner 양쪽"),
        (17, "ResultStore", PART, "server 메모리 캐시", "직렬화·파라미터 동봉 저장은 추후"),
        (18, "TopologyEditor GUI", PLAN, "Phase 5", ""),
        (19, "AnalysisReport GUI", PART, "화면: optimize, models, spec, circuit, meta", "optimize 화면이 v4 패리티(radar 5종·gauge·tightness·V-I map·iteration plot/table·scrubber) 달성"),
        (20, "RegressionHarness", IMPL, "tests/ · api/regression · 홈 버튼", "골든 50건 + 창립 벤치마크(3-node MNA, 다중해 toy), Python+JS 이중 러너"),
        (21, "RuleGenerator", PLAN, "창립 스펙 §10 · docs/ROADMAP.md", "최종 산출물: PDK table rule(Aup_min/Adown_min/Aclamp_min/Rpath_max) + pre-screen formula rule. Stage 2(SPICE/PERC sign-off)는 스코프 밖"),
    ]
    return {
        "service": {"version": "0.3.2", "grid_N": M.N, "golden_checks": 50,
                    "runtime": "python {} / fastapi".format(sys.version.split()[0])},
        "decisions": "D1 로컬작업+push · D2 down diode=model1 미러 · D3 corner 양쪽 · D4 Python+HTML · "
                     "D5 ±50% 창 · D6 원시데이터 없음 · D7 L만 변수 · D8 최소 UI · D9 1kV↔1.33A · "
                     "창립: rule 비대칭 · 3단계 해(M 1.0/1.2/1.5) · Top Cell port SOA · 2단계 loss · ground 명시 · "
                     "R 계열(Rio_rdl/RDD_un1/RDD_dn1/Rvss_rdl/Resd)도 device",
        "entities": [{"id": i, "name": n, "status": s, "where": w, "note": t}
                     for i, n, s, w, t in items],
    }


_opt_cache = {}


@app.get(PREFIX + "/api/optimize")
def optimize(request: Request):
    """v4-parity sweep optimizer backed by the precomputed calibration table."""
    try:
        from server.optimizer import run_sweep
        params = dict(request.query_params)
        key = json.dumps(params, sort_keys=True)
        if key not in _opt_cache:
            if len(_opt_cache) > 16:
                _opt_cache.clear()
            _opt_cache[key] = run_sweep(params)
        return _opt_cache[key]
    except FileNotFoundError:
        return PlainTextResponse(
            "calibration table missing — run: python -m server.calibtable", status_code=503)


@app.get(PREFIX + "/api/schematic")
def schematic(x1: float = 2.56, x2: float = 1415.232, L: float = 350.0,
              i: float = A_PER_KV, corner: str = "worst"):
    """Real schematic SVG (schemdraw) with optional operating-point annotations."""
    err = _window_error(x1, x2)
    if err:
        return err
    if corner not in ("worst", "best"):
        return PlainTextResponse("corner must be worst|best", status_code=422)
    op = None
    c1, c2 = _cal(M.D1, x1, corner), _cal(M.D2, x2, corner)
    ifail = min(c1["e"]["ip"], c2["e"]["ip"])
    if 0 < i <= ifail:
        rvdd = 0.5 * L / 350.0        # RDD_un1
        rdd_dn1 = rvdd                # RDD_dn1 (동일 규칙·공유 L)
        vssr = i * M.RVSS_RDL         # node A (victim NMOS ref)
        vd = M.VofI(c1["pos"], i)
        vc = M.VofI(c2["pos"], i)
        n3b = vssr + i * rdd_dn1      # clamp bottom
        n3v = vc + n3b                # clamp top (victim PMOS source)
        n2v = n3v + i * rvdd
        vio = n2v + vd + i * M.RIO_RDL
        vout, ivv = M.victim_probe(vio, n3v, VICTIM["resd"], VICTIM["von"], VICTIM["ronj"])
        op = {"IO": vio, "N1": n2v + vd, "N2": n2v, "N3": n3v, "N3B": n3b, "OUT": vout,
              "VSSR": vssr, "i": i, "iv": ivv}
    from server.schematic import build_svg
    return Response(build_svg(x1, x2, L, op), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@app.get(PREFIX + "/api/schematic/table")
def schematic_table(x1: float = 2.56, x2: float = 1415.232, L: float = 350.0,
                    corner: str = "worst", n: int = 81):
    """Node-voltage table over the current grid — 클라이언트 실시간 주석 갱신용."""
    err = _window_error(x1, x2)
    if err:
        return err
    if corner not in ("worst", "best"):
        return PlainTextResponse("corner must be worst|best", status_code=422)
    c1, c2 = _cal(M.D1, x1, corner), _cal(M.D2, x2, corner)
    ifail = min(c1["e"]["ip"], c2["e"]["ip"])
    rvdd = 0.5 * L / 350.0        # RDD_un1
    rdd_dn1 = rvdd                # RDD_dn1 (동일 규칙·공유 L)
    out = {"ifail": ifail, "I": [], "IO": [], "N1": [], "N2": [], "N3": [], "N3B": [],
           "OUT": [], "VSSR": [], "IV": []}
    n = max(2, min(401, int(n)))
    for k in range(n):
        i = ifail * k / (n - 1.0)
        vssr = i * M.RVSS_RDL         # node A
        vd = M.VofI(c1["pos"], i) if i > 0 else 0.0
        vc = M.VofI(c2["pos"], i) if i > 0 else 0.0
        n3b = vssr + i * rdd_dn1      # clamp bottom
        n3v = vc + n3b                # clamp top
        n2v = n3v + i * rvdd
        vio = n2v + vd + i * M.RIO_RDL
        vout, iv = M.victim_probe(vio, n3v, VICTIM["resd"], VICTIM["von"], VICTIM["ronj"])
        out["I"].append(i)
        out["IO"].append(vio)
        out["N1"].append(n2v + vd)
        out["N2"].append(n2v)
        out["N3"].append(n3v)
        out["N3B"].append(n3b)
        out["OUT"].append(vout)
        out["VSSR"].append(vssr)
        out["IV"].append(iv)
    return out


@app.get(PREFIX + "/api/schematic/library")
def schematic_library():
    """Subcircuit Set 목록 — cell별 id/이름/사용 가능 model list (canvas는 개별 SVG)."""
    from server.schematic import LIBRARY_CELLS
    return {"cells": [{"id": c["id"], "name": c["name"], "models": c["models"]}
                      for c in LIBRARY_CELLS]}


@app.get(PREFIX + "/api/schematic/library/{cell_id}")
def schematic_library_cell(cell_id: str):
    """라이브러리 cell 1개의 개별 canvas SVG."""
    from server.schematic import build_cell_svg
    svg = build_cell_svg(cell_id)
    if svg is None:
        return PlainTextResponse("unknown cell", status_code=404)
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get(PREFIX + "/api/schematic/mapping")
def schematic_mapping():
    """instance→cell 매핑 표 + 검증 결과 (cell 참조·model∈cell.models·params 바인딩)."""
    from server.schematic import validate_mapping
    return validate_mapping()


@app.get(PREFIX + "/api/schematic/layout")
def schematic_layout_get():
    from server import schematic as SCH
    layout, custom = SCH.load_layout()
    return {"layout": layout, "custom": custom}


@app.post(PREFIX + "/api/schematic/layout")
async def schematic_layout_save(request: Request):
    from server import schematic as SCH
    layout = await request.json()
    try:
        SCH.build_svg(2.56, 1415.232, 350.0, None, layout)  # validate by test render
    except Exception as ex:
        return PlainTextResponse("layout render 실패: {}".format(ex), status_code=422)
    SCH.save_layout(layout)
    return {"ok": True}


@app.delete(PREFIX + "/api/schematic/layout")
def schematic_layout_reset():
    from server import schematic as SCH
    SCH.reset_layout()
    return {"ok": True, "layout": SCH.DEFAULT_LAYOUT}


@app.post(PREFIX + "/api/schematic/preview")
async def schematic_preview(request: Request, x1: float = 2.56, x2: float = 1415.232,
                            L: float = 350.0, i: float = A_PER_KV, corner: str = "worst"):
    """Render a posted layout without saving (편집 미리보기)."""
    from server import schematic as SCH
    layout = await request.json()
    err = _window_error(x1, x2)
    if err:
        return err
    op = None
    c1, c2 = _cal(M.D1, x1, corner), _cal(M.D2, x2, corner)
    if 0 < i <= min(c1["e"]["ip"], c2["e"]["ip"]):
        rvdd = 0.5 * L / 350.0        # RDD_un1
        rdd_dn1 = rvdd                # RDD_dn1 (동일 규칙·공유 L)
        vssr = i * M.RVSS_RDL         # node A
        vd = M.VofI(c1["pos"], i)
        vc = M.VofI(c2["pos"], i)
        n3b = vssr + i * rdd_dn1      # clamp bottom
        n3v = vc + n3b                # clamp top
        n2v = n3v + i * rvdd
        vio = n2v + vd + i * M.RIO_RDL
        vout, ivv = M.victim_probe(vio, n3v, VICTIM["resd"], VICTIM["von"], VICTIM["ronj"])
        op = {"IO": vio, "N1": n2v + vd, "N2": n2v, "N3": n3v, "N3B": n3b, "OUT": vout,
              "VSSR": vssr, "i": i, "iv": ivv}
    try:
        svg = SCH.build_svg(x1, x2, L, op, layout)
    except Exception as ex:
        return PlainTextResponse("layout render 실패: {}".format(ex), status_code=422)
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get(PREFIX + "/models")
def models_page():
    return _page("models.html")


@app.get(PREFIX + "/optimize")
def optimize_page():
    return _page("optimize.html")


@app.get(PREFIX + "/circuit")
def circuit_page():
    return _page("circuit.html")


@app.get(PREFIX + "/spec")
def spec_page():
    return _page("spec.html")


@app.get(PREFIX + "/meta")
def meta_page():
    return _page("entities.html")


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
    """Main = v4-faithful optimizer (사용자 지정). 링크 허브는 /hub에 보존."""
    return _page("optimize.html")


@app.get(PREFIX + "/hub")
def hub_page():
    return _page("hub.html")


@app.get("/")
def root():
    return RedirectResponse(PREFIX + "/")
