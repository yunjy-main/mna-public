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
import math
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
    env = dict(os.environ, PYTHONIOENCODING="utf-8")  # 콘솔 cp949에서 테스트 출력 인코딩 고정
    for script in ("regression.py", "founding_benchmarks.py", "test_calibtable.py",
                   "test_victim_probe.py", "test_victim_soa.py", "test_netlist.py"):
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tests", script)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=ROOT, timeout=300, env=env,
        )
        outputs.append("[{}] {}".format(script, (p.stdout + p.stderr).strip()))
        code = code or p.returncode
    return {"exit": code, "output": "\n".join(outputs)}


A_PER_KV = M.A_PER_KV  # 원천은 model.py (D9: ESD 1 kV <-> 1.33 A)
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


def _params_registry(nl):
    """자유 파라미터 레지스트리 — 정본은 netlist.params_registry (이슈 #11)."""
    from server.netlist import params_registry
    return params_registry(nl)


def _pset_from_query(q, registry):
    """query dict → pset (이슈 #11 §2.4). 미지정=META default, 값은 min_valid 초과
    필수(E5 — 0-나눗셈 등 무효값 차단). META 미정의 기호는 싣지 않음(E2).
    반환 (pset, 오류응답|None)."""
    p = {}
    for it in registry:
        name = it["name"]
        meta = M.PARAM_META.get(name)
        raw = q.get(name)
        if raw is None or raw == "":
            if meta is None:
                continue
            v = meta["default"]
        else:
            try:
                v = float(raw)
            except ValueError:
                return None, PlainTextResponse("{}={} 숫자 아님".format(name, raw),
                                               status_code=422)
        mv = (meta or {}).get("min_valid", 0.0)
        if not math.isfinite(v) or not (v > mv):
            return None, PlainTextResponse(
                "{}={} 무효 — finite·> {} 필요 (이슈 #11 E5/#14 §8)".format(name, v, mv),
                status_code=422)
        p[name] = v
    return p, None


def _feas_input_error(hbm_kv, cap_lim_pf, alphas, lr, mu_bar, mu_rule, iters):
    """신규 optimizer 수치 입력 검증 (#14 §8) — 위반 시 메시지 반환(422용)."""
    for name, v, kind in (("hbm_kv", hbm_kv, "pos"), ("cap_lim_pf", cap_lim_pf, "pos"),
                          ("lr", lr, "pos"), ("alpha_rule", alphas[0], "nn"),
                          ("alpha_soa", alphas[1], "nn"), ("alpha_spec", alphas[2], "nn"),
                          ("mu_bar", mu_bar, "nn"), ("mu_rule", mu_rule, "nn")):
        if not math.isfinite(v):
            return "{}={} — finite 필요".format(name, v)
        if kind == "pos" and v <= 0:
            return "{}={} — > 0 필요".format(name, v)
        if kind == "nn" and v < 0:
            return "{}={} — ≥ 0 필요".format(name, v)
    if alphas[0] == alphas[1] == alphas[2] == 0:
        return "alpha 전부 0 — objective가 비어 있음"
    if not (1 <= iters <= 200):
        return "iters∈[1,200] 필요"
    return None


@app.get(PREFIX + "/api/params")
def params_api():
    """자유 파라미터 레지스트리 단일 엔드포인트 — 전 페이지 입력 렌더의 원천 (이슈 #11)."""
    from server.schematic import load_layout
    from server.netlist import extract_netlist
    return {"params": _params_registry(extract_netlist(load_layout()[0]))}


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
        rdd = M.rdd_r(350.0)  # 기준 L=350 → RDD_un1 = RDD_dn1 = 0.5Ω (표시용, 정본=model)
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
            {"name": "IO", "role": "PAD — stress 주입 node (XRio_rdl 뒤 diode tap)"},
            {"name": "N1", "role": "diode tap (XD_up anode / XD_down cathode) — 회로도 IO node와 동일 열"},
            {"name": "N2", "role": "VDD rail — XD_up cathode / XRDD_un1 좌단"},
            {"name": "N3", "role": "VDD rail — XClamp top (victim PMOS source 인접)"},
            {"name": "N3B", "role": "XClamp bottom — XRDD_dn1로 node A 연결"},
            {"name": "(OUT→N2)", "role": "victim NMOS drain — 상단 port 경유 VDD rail(N2) 직결(이슈 #10 사용자 지시)로 별도 OUT 노드 삭제, monitor D 단자=N2"},
            {"name": "VSS", "role": "기준(ref) node — node A(=I·Rvss_rdl) 경유 VSS port 리턴"},
            {"name": "MVSS", "role": "Main VSS rail — VSS와 XD_b2b_m, VSS2와 XD_b2b_m2로 연결"},
        ],
        "branches": [
            {"name": "XI_ESD ×4", "type": "cell: i_esd (open)", "nodes": "IO→VDD/IO→VSS/GND→VSS/GND→MVSS", "param": "I=I_sweep (1kV↔1.33A) — 현재 회로도 표기는 전부 open"},
            {"name": "XRio_rdl", "type": "cell: r · model metal", "nodes": "IO port–N1", "param": "R=0.1Ω"},
            {"name": "XRvdd_rdl", "type": "cell: r · model metal", "nodes": "VDD port–N2", "param": "R=0.1Ω (양(+) 스트레스 무전류)"},
            {"name": "XRvss_rdl", "type": "cell: r · model metal", "nodes": "node A–VSS port", "param": "R=0.1Ω (리턴 경로)"},
            {"name": "XD_up", "type": "cell: d_up · model esdvpnp", "nodes": "N1→N2", "param": "size=x1={}".format(x1)},
            {"name": "XD_down", "type": "cell: d_down · model esdndsx", "nodes": "VSS→N1", "param": "size=x1 (음(−) 스트레스 경로, solver=model1 미러 D2)"},
            {"name": "XRDD_un1", "type": "cell: r · model metal", "nodes": "N2–N3", "param": "R=rdd(L,W), up diode↔clamp, L·W 변수(D7)"},
            {"name": "XRDD_dn1", "type": "cell: r · model metal", "nodes": "N3B–node A", "param": "R=rdd(L,W), down diode↔clamp, 공유 L·W(D7)"},
            {"name": "XClamp", "type": "cell: clamp · model nfet_clamp", "nodes": "N3–N3B", "param": "size=x2={}".format(x2)},
            {"name": "XResd", "type": "cell: r · model rmres", "nodes": "IO–gate(IN)", "param": "R=500Ω (victim 보호)"},
            {"name": "XD_up2 / XD_down2", "type": "cell: d_up/d_down (2차 보호, 미바인딩)", "nodes": "IN열–VDD rail / VSS rail–IN열", "param": "esdvpnp / esdndsx"},
            {"name": "XD_b2b_m / XD_b2b_m2", "type": "cell: d_b2b (vertical) · essvpnp ×2", "nodes": "N3B–MVSS / VSS2–MVSS", "param": "역병렬 쌍"},
            {"name": "XD_b2b", "type": "cell: d_b2b (horizontal, open) · essvpnp ×2", "nodes": "N3B연장–VSS2", "param": "비활성"},
            {"name": "XVictim", "type": "cell: victim_n · SG_NFET 1stk_1rx", "nodes": "D=N2(VDD rail)·G=IN·S/B=VSSR", "param": "SOA monitor · equation 없음 — 행렬 미기여, solve 후 terminal 전압만 관측"},
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
def schematic(request: Request, i: float = A_PER_KV, corner: str = "worst"):
    """Real schematic SVG (schemdraw) with optional operating-point annotations.
    자유 파라미터는 registry 기반 pset (이슈 #11 — 기존 query 이름 호환)."""
    from server.schematic import load_layout, build_svg
    from server.netlist import extract_netlist
    p, err = _pset_from_query(dict(request.query_params),
                              _params_registry(extract_netlist(load_layout()[0])))
    if err:
        return err
    x1, x2, L = p.get("x1", 2.56), p.get("x2", 1415.232), p.get("L", 350.0)
    err = _window_error(x1, x2)
    if err:
        return err
    if corner not in ("worst", "best"):
        return PlainTextResponse("corner must be worst|best", status_code=422)
    op = None
    c1, c2 = _cal(M.D1, x1, corner), _cal(M.D2, x2, corner)
    ifail = min(c1["e"]["ip"], c2["e"]["ip"])
    if 0 < i <= ifail:
        rvdd = M.rdd_r(L, p.get("W", M.RDD_W0))  # RDD_un1 (정본=model.rdd_r)
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
    return Response(build_svg(op=op, pset=p), media_type="image/svg+xml",
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
    rvdd = M.rdd_r(L)             # RDD_un1 (정본=model.rdd_r)
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


def _model_ctx_or_err(model_mode, pset, corner):
    """model_mode 파라미터 → (model_ctx, 오류응답). measured면 D5 창·corner 검증.
    pset: 자유 파라미터 dict (이슈 #11 — 이름 인자 threading 폐지)."""
    from server.netlist import measured_context
    if model_mode == "placeholder":
        return None, None
    if model_mode != "measured":
        return None, PlainTextResponse("model_mode must be measured|placeholder", status_code=422)
    if corner not in ("worst", "best"):
        return None, PlainTextResponse("corner must be worst|best", status_code=422)
    err = _window_error(pset.get("x1", M.PARAM_META["x1"]["default"]),
                        pset.get("x2", M.PARAM_META["x2"]["default"]))
    if err:
        return None, err
    return measured_context(corner=corner, pset=pset), None


@app.get(PREFIX + "/api/schematic/matrix")
def schematic_matrix(inject: str = "IO", ground: str = "VSS", i: float = 1.33, L: float = 350.0,
                     x1: float = 2.56, x2: float = 1415.232, corner: str = "worst",
                     model_mode: str = "measured"):
    """회로도 → netlist → MNA 자동 변환·해석.

    기하 연결성에서 net 추출, instance(cell/model/params)와 결합해 조립.
    model_mode=measured(기본): d_up/d_down=Device1·clamp=Device2 실측 곡선(사용자 궁극 목표),
    b2b는 실측 미제공이라 placeholder. model_mode=placeholder: 전부 softplus 계열.
    inject/ground = net 이름(IO/VDD/VSS/MVSS/VSS2...), open 소자는 미조립."""
    from server.schematic import load_layout
    from server.netlist import extract_netlist, assemble_and_solve, evaluate_soa_monitors
    ctx, err = _model_ctx_or_err(model_mode, {"x1": x1, "x2": x2}, corner)
    if err:
        return err
    nl = extract_netlist(load_layout()[0])  # R15: 표시 중인 회로도(custom 포함)가 원천
    try:
        sol = assemble_and_solve(nl, inject=inject, ground=ground, I=i, L=L, model_ctx=ctx)
    except ValueError as ex:
        return PlainTextResponse(str(ex), status_code=422)
    names = nl["nets"]
    monitors = evaluate_soa_monitors(nl, sol)
    from server.netlist import parse_binding, eval_binding, binding_ok
    devs = []
    for d in nl["devices"]:
        if d["kind"] in ("pfet", "nfet"):
            pins = "d={} g={} s={}".format(names[d["drain"]], names[d["gate"]], names[d["source"]])
        else:
            pins = "{} – {}".format(names[d["a"]], names[d["b"]])
        ent = {"instance": d["instance"], "cell": d["cell"], "kind": d["kind"],
               "model": d["model"], "open": d["open"], "pins": pins,
               "params": d.get("params", {}), "role": d.get("role")}
        R = (d.get("params") or {}).get("R")
        if d["kind"] == "resistor" and isinstance(R, str):  # 바인딩 → 해석값 (파서 평가)
            pb = parse_binding(R)
            ent["R"] = eval_binding(pb, sol["pset"]) if (pb and binding_ok(R)) else None
        devs.append(ent)
    return {"nets": sorted(names.values()),
            "n_nets": len(names), "n_wires": nl["n_wires"], "devices": devs,
            "global_ground_nets": [names[g] for g in nl["global_ground_nets"]],
            "local_ground_nets": [names[g] for g in nl["local_ground_nets"]],
            "name_conflicts": nl["name_conflicts"],
            "assoc_conflicts": nl["assoc_conflicts"],
            "monitors": monitors,
            "solution": sol}


# sweep 진행률 (단일 사용자 표시용 — 0.01A 고해상도 sweep의 실시간 %)
_SWEEP_PROG = {"done": 0, "total": 0}


@app.get(PREFIX + "/api/analysis/sweep/progress")
def analysis_sweep_progress():
    t = _SWEEP_PROG["total"]
    return {"done": _SWEEP_PROG["done"], "total": t,
            "pct": (100.0 * _SWEEP_PROG["done"] / t) if t else 0.0}


def _slug(name):
    """instance/cell명 → 앵커 id (영숫자·한글 외 '_') — frontend와 동일 규칙."""
    import re
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(name))


@app.get(PREFIX + "/api/instance/info")
def instance_info(request: Request = None, corner: str = "worst"):
    """instance/subcircuit 페이지 원천 — 전 소자(저항·open 포함) 메타 + model 시각화
    데이터(실측 I-V 곡선·SOA endpoint·cap). sweep 없이 소자 정보만 (경량).
    자유 파라미터는 레지스트리 기반 pset (이슈 #11 — 기존 query 이름 호환)."""
    from server.schematic import load_layout, LIBRARY_CELLS
    from server.netlist import (extract_netlist, soa_endpoints, device_caps,
                                device_curves, size_expr_of, soa_rules_for, device_keys,
                                parse_binding, eval_binding, binding_ok)
    if corner not in ("worst", "best"):
        return PlainTextResponse("corner must be worst|best", status_code=422)
    nl = extract_netlist(load_layout()[0])
    p, err = _pset_from_query(dict(request.query_params) if request is not None else {},
                              _params_registry(nl))
    if err:
        return err
    err = _window_error(p["x1"], p["x2"])
    if err:
        return err
    names = nl["nets"]
    eps = soa_endpoints(nl, corner=corner, pset=p)
    caps = device_caps(nl, pset=p)
    curves = device_curves(nl, corner=corner, pset=p)
    key_of = {}
    for k, d in device_keys(nl):
        key_of[id(d)] = k
    instances = {}
    for d in nl["devices"]:
        inst = d.get("instance") or d["kind"]
        ent = instances.setdefault(inst, {
            "instance": inst, "slug": _slug(inst), "cell": d.get("cell"),
            "model": d.get("model"), "role": d.get("role"), "open": d["open"],
            "params": d.get("params", {}), "size_expr": size_expr_of(d),
            "elements": [], "soa": None, "cap": None, "curve": None, "rules": None})
        if d["kind"] in ("pfet", "nfet"):
            pins = "d={} g={} s={}".format(names[d["drain"]], names[d["gate"]],
                                           names[d["source"]])
        else:
            pins = "{} – {}".format(names[d["a"]], names[d["b"]])
        ent["elements"].append({"kind": d["kind"], "pins": pins})
        k = key_of.get(id(d))
        if k is not None and ent["soa"] is None:
            ent["soa"] = eps.get(k)
            ent["cap"] = caps.get(k)
            ent["curve"] = curves.get(k)
        if d.get("role") == "soa_monitor" and d.get("model"):
            ent["rules"] = soa_rules_for(d["model"])
        if d["kind"] == "resistor":
            R = (d.get("params") or {}).get("R")
            if isinstance(R, str):  # 바인딩 식 — 파서 평가 (문자열 비교 하드코딩 폐지)
                pb = parse_binding(R)
                ent["R"] = eval_binding(pb, p) if (pb and binding_ok(R)) else None
                ent["R_expr"] = R.replace(" ", "")
                if pb and pb["kind"] == "func":  # metal model 식 정본 = 함수 docstring
                    fn = M.BINDING_FUNCS.get(pb["fn"])
                    ent["R_desc"] = ((fn.__doc__ or "").strip().splitlines() or [None])[0] \
                        if fn else None
                    ent["R_args"] = {s: p.get(s) for s in pb["symbols"]}
            else:
                ent["R"] = R
    # cell별 바인딩 식 집계 (subcircuit 페이지의 model 표시 원천)
    cell_binds = {}
    for d in nl["devices"]:
        cid = d.get("cell")
        if not cid:
            continue
        e = size_expr_of(d)
        if e:
            cell_binds.setdefault(cid, set()).add("size=" + e)
        R = (d.get("params") or {}).get("R")
        if isinstance(R, str):
            cell_binds.setdefault(cid, set()).add("R=" + R.replace(" ", ""))
    cells = [{"id": c["id"], "name": c["name"], "models": c["models"],
              "bindings": sorted(cell_binds.get(c["id"], [])),
              "instances": [i["instance"] for i in instances.values()
                            if i["cell"] == c["id"]]}
             for c in LIBRARY_CELLS]
    # 바인딩 함수 model 식 (정본 = 함수 docstring 1행)
    bind_docs = {k: ((v.__doc__ or "").strip().splitlines() or [""])[0]
                 for k, v in M.BINDING_FUNCS.items()}
    return {"pset": p, "x1": p.get("x1"), "x2": p.get("x2"), "L": p.get("L"),
            "corner": corner, "instances": list(instances.values()), "cells": cells,
            "binding_funcs": bind_docs}


@app.get(PREFIX + "/api/analysis/sweep")
def analysis_sweep(request: Request, imax: float = 2.0, n: int = 21,
                   corner: str = "worst",
                   model_mode: str = "measured", imin: float = 0.0,
                   cap_lim_pf: float = None, hbm_kv: float = None, slim: int = 0):
    """6종 ordered rail 시나리오 × I=imin→Imax continuation sweep + 매 point SOA 평가
    (이슈 #10 §5 + 사용자 궁극 목표: 실측 model 연계, point마다 저항 제외 device_v).
    imin<0이면 양극 sweep(0에서 바깥쪽 두 갈래 continuation).
    자유 파라미터(x1/x2/L/…)는 레지스트리 기반 pset으로 query에서 수집 —
    이름 박힌 인자 폐지 (이슈 #11 §2.4, 기존 query 이름 호환).
    상태: non_convergence / unresolved_monitor_terminal / soa_fail / pass."""
    from server.schematic import load_layout
    from server.netlist import extract_netlist, sweep_scenario, RAIL_SCENARIOS
    if not (0 < imax <= 100) or not (2 <= n <= 801) or not (-100 <= imin < imax):
        return PlainTextResponse("imax∈(0,100], n∈[2,801], imin∈[-100,imax) 필요", status_code=422)
    from server.netlist import (device_keys, soa_endpoints, soa_rules_for, device_curves,
                                device_caps, size_expr_of)
    nl = extract_netlist(load_layout()[0])
    params = _params_registry(nl)
    p, err = _pset_from_query(dict(request.query_params), params)
    if err:
        return err
    ctx, err = _model_ctx_or_err(model_mode, p, corner)
    if err:
        return err
    _SWEEP_PROG["done"], _SWEEP_PROG["total"] = 0, n * len(RAIL_SCENARIOS)

    def _tick():
        _SWEEP_PROG["done"] += 1
    scenarios = []
    for force, ground in RAIL_SCENARIOS:
        try:
            scenarios.append(sweep_scenario(nl, force, ground, imax=imax, n=n, pset=p,
                                            model_ctx=ctx, imin=imin,
                                            progress_cb=_tick, slim=bool(slim)))
        except ValueError as ex:
            scenarios.append({"force": force, "ground": ground, "error": str(ex)})
    # 소자 리스트 = frontend 시각화의 단일 원천 (key는 device_v/device_i와 동일)
    eps = soa_endpoints(nl, corner=corner, pset=p)
    curves = device_curves(nl, corner=corner, pset=p)
    caps = device_caps(nl, pset=p)
    devices = [{"key": k, "instance": d.get("instance"), "cell": d.get("cell"),
                "model": d.get("model"), "kind": d["kind"], "role": d.get("role"),
                "params": d.get("params", {}), "size_expr": size_expr_of(d),
                "soa": eps.get(k), "curve": curves.get(k), "cap": caps.get(k)}
               for k, d in device_keys(nl)]
    monitor_rules = {}
    for k, d in device_keys(nl):
        if d.get("role") == "soa_monitor" and d.get("model"):
            monitor_rules[d["model"]] = soa_rules_for(d["model"])
    # cap spec 정본 = io_cap_at_zero (0V contributor 집합 합, 이슈 #15 §3.6).
    # role 무결성 오류는 silent 0이 아니라 422 (이슈 #14 §3)
    from server.netlist import io_cap_at_zero
    try:
        io_cap_total = io_cap_at_zero(nl, pset=p)
    except ValueError as ex:
        return PlainTextResponse(str(ex), status_code=422)
    # spec 입력(UI) 반영 — 미지정 시 model 기본값 (capLim 5pF, HBM 1kV)
    cap_lim = (cap_lim_pf * 1e-12) if (cap_lim_pf and cap_lim_pf > 0) else M.IO_CAP_LIM
    spec_kv = hbm_kv if (hbm_kv and hbm_kv > 0) else M.HBM_DEFAULT_KV
    # pset echo가 정본 — 개별 키(x1/x2/L)는 전환기 호환(E6, S4에서 제거)
    return {"imax": imax, "imin": imin, "n": n, "pset": p,
            "L": p.get("L"), "x1": p.get("x1"), "x2": p.get("x2"),
            "params": params,
            "corner": corner, "model_mode": model_mode, "devices": devices,
            "cap_lim": cap_lim, "io_cap_total": io_cap_total,
            "cap_pass": io_cap_total <= cap_lim,
            "esd_spec": {"a_per_kv": M.A_PER_KV,
                         "default_kv": spec_kv,
                         "default_amp": M.hbm_current(spec_kv),
                         "levels": [{"kv": kv, "amp": M.hbm_current(kv)}
                                    for kv in M.HBM_LEVELS_KV]},
            "monitor_rules": monitor_rules, "scenarios": scenarios}


_OPT_PROG = {"done": 0, "total": 0}  # MNA optimizer 실시간 진행률 (sweep과 동일 패턴)

RUNS_DIR = os.path.join(ROOT, "artifacts", "optimizer_runs")


def _save_opt_run(kind, query, result):
    """optimizer 실행 자동 기록 (사용자 지시 2026-07-29: 앞으로 데이터를 기록) —
    요청 query+응답 전체를 artifacts/optimizer_runs/에 저장(리뷰·재현 아티팩트).
    응답에 run_file 경로를 넣어 UI에서 확인 가능. 기록 실패는 API에 영향 없음."""
    try:
        import datetime
        os.makedirs(RUNS_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        status = result.get("status") or (
            "PASS" if (result.get("final") or {}).get("soa_pass") else "FAIL")
        fn = "{}_{}_{}.json".format(ts, kind, status)
        with open(os.path.join(RUNS_DIR, fn), "w", encoding="utf-8") as fh:
            json.dump({"kind": kind, "query": dict(query), "saved_at": ts,
                       "response": result}, fh, ensure_ascii=False)
        result["run_file"] = "artifacts/optimizer_runs/" + fn
    except OSError:
        pass
    return result


@app.get(PREFIX + "/api/optimize/mna/progress")
def optimize_mna_progress():
    t = _OPT_PROG["total"]
    return {"done": _OPT_PROG["done"], "total": t,
            "mode": _OPT_PROG.get("mode"),  # adjoint|fd|fd-legacy (#14 §10.1)
            "live": _OPT_LIVE["rows"],  # 실시간 그래프 피드 (2026-07-29)
            # pool 정밀 재평가(#15 §4)로 추정 total을 넘을 수 있어 100% 클램프
            "pct": min(100.0, 100.0 * _OPT_PROG["done"] / t) if t else 0.0}


def _opt_tick(done, total):
    _OPT_PROG["done"], _OPT_PROG["total"] = done, total


_OPT_LIVE = {"rows": []}  # 실시간 그래프 피드 (사용자 지시 2026-07-29)


def _opt_live_push(row):
    """optimizer iteration마다 호출 — 그래프에 필요한 요약만 보관 (detail 제외)."""
    try:
        losses = row.get("losses") or {}
        _OPT_LIVE["rows"].append({
            "it": row.get("it"),
            "objective": losses.get("objective", row.get("loss")),
            "loss_rule": losses.get("rule"), "loss_soa": losses.get("soa"),
            "loss_spec": losses.get("spec"),
            "worst": row.get("worst"),
            "cap_u": row.get("cap_u", (row.get("usages") or {}).get("cap(IO)")),
            "vars": {k: row.get(k) for k in ("x1", "x2", "W", "L")
                     if row.get(k) is not None},
            "r_metal": (M.rdd_r(row["L"], row.get("W", M.RDD_W0))
                        if row.get("L") is not None else None),
            "feasible": row.get("feasible")})
    except (TypeError, KeyError, ValueError):
        pass


@app.get(PREFIX + "/api/optimize/mna")
def optimize_feas_api(request: Request, corner: str = "worst", force: str = "IO",
                      ground: str = "VSS", hbm_kv: float = 1.0, cap_lim_pf: float = 0.7,
                      alpha_rule: float = 1.0, alpha_soa: float = 1.0,
                      alpha_spec: float = 1.0,
                      barrier: str = "off", mu_bar: float = 0.01, mu_rule: float = 20.0,
                      lr: float = 0.06, iters: int = 30, freeze: str = None,
                      stop_on_feasible: int = 0, grad: str = "adjoint",
                      feasible_policy: str = "max_margin"):
    """Constraint·feasibility optimizer (이슈 #12/#13) — 기본 엔드포인트.
    J_obj = α·(L_rule+L_SOA+L_spec) squared hinge, PASS=전 g_j≤0, barrier 기본 off,
    best_feasible/best_infeasible 분리, final clamp 없음. legacy는 /legacy."""
    from server.schematic import load_layout
    from server.opt_feas import optimize_feas
    from server.netlist import extract_netlist
    if corner not in ("worst", "best"):
        return PlainTextResponse("corner must be worst|best", status_code=422)
    verr = _feas_input_error(hbm_kv, cap_lim_pf, (alpha_rule, alpha_soa, alpha_spec),
                             lr, mu_bar, mu_rule, iters)
    if verr:
        return PlainTextResponse(verr, status_code=422)
    layout = load_layout()[0]
    reg = _params_registry(extract_netlist(layout))
    q = dict(request.query_params)
    p, err = _pset_from_query(q, reg)
    if err:
        return err
    windows = {}
    for r in reg:
        if not r["supported"]:
            continue
        lo, hi = q.get(r["name"] + "_min"), q.get(r["name"] + "_max")
        try:
            if lo is not None and hi is not None:
                windows[r["name"]] = (float(lo), float(hi))
                if not (math.isfinite(windows[r["name"]][0])
                        and math.isfinite(windows[r["name"]][1])):
                    return PlainTextResponse("{} 창 finite 필요".format(r["name"]),
                                             status_code=422)
        except ValueError:
            return PlainTextResponse("{} 창 숫자 아님".format(r["name"]), status_code=422)
    if freeze is None:
        fz = tuple(r["name"] for r in reg if r["supported"] and r["freeze_default"])
    else:
        fz = tuple(s for s in (t.strip() for t in freeze.split(",")) if s)
    _OPT_PROG["done"], _OPT_PROG["total"], _OPT_PROG["mode"] = 0, 0, grad
    _OPT_LIVE["rows"] = []
    try:
        return _save_opt_run("feas", request.query_params, optimize_feas(
            layout, corner=corner, force=force, ground=ground,
            hbm_kv=hbm_kv, cap_lim=cap_lim_pf * 1e-12,
            windows=windows,
            alphas=(alpha_rule, alpha_soa, alpha_spec),
            barrier=barrier, mu_bar=mu_bar, mu_rule=mu_rule,
            lr=lr, iters=iters, freeze=fz, pset=p,
            stop_on_feasible=bool(stop_on_feasible), grad=grad,
            feasible_policy=feasible_policy,
            progress_cb=_opt_tick, live_cb=_opt_live_push))
    except ValueError as ex:
        return PlainTextResponse(str(ex), status_code=422)


@app.get(PREFIX + "/api/optimize/mna/legacy")
def optimize_mna_api(request: Request, corner: str = "worst", force: str = "IO",
                     ground: str = "VSS", hbm_kv: float = 1.0, cap_lim_pf: float = 0.7,
                     mu_soa: float = 12.0, mu_rule: float = 20.0,
                     lr: float = 0.06, iters: int = 30, freeze: str = None,
                     barrier: str = "log", mu_bar: float = 0.01):
    """Legacy optimizer (cost+softplus+barrier+FD) — 별도 엔드포인트 병행 보존
    (사용자 확정 2026-07-29, 기능 삭제 금지). S5 adjoint 검증의 oracle 겸용."""
    from server.schematic import load_layout
    from server.opt_mna import optimize_mna
    from server.netlist import extract_netlist
    if corner not in ("worst", "best"):
        return PlainTextResponse("corner must be worst|best", status_code=422)
    if not (1 <= iters <= 200):
        return PlainTextResponse("iters∈[1,200] 필요", status_code=422)
    layout = load_layout()[0]
    reg = _params_registry(extract_netlist(layout))
    q = dict(request.query_params)
    # 전환기 legacy 별칭 (S4 frontend 신규약 전환 후 제거, E6)
    _LEGACY = {"x1min": "x1_min", "x1max": "x1_max", "x2min": "x2_min", "x2max": "x2_max",
               "lmin": "L_min", "lmax": "L_max", "wA": "w_x1", "wC": "w_x2", "wL": "w_L"}
    for old, new in _LEGACY.items():
        if old in q and new not in q:
            q[new] = q[old]
    p, err = _pset_from_query(q, reg)
    if err:
        return err
    windows, weights = {}, {}
    for r in reg:
        if not r["supported"]:
            continue
        lo, hi = q.get(r["name"] + "_min"), q.get(r["name"] + "_max")
        w = q.get("w_" + r["name"])
        try:
            if lo is not None and hi is not None:
                windows[r["name"]] = (float(lo), float(hi))
            if w is not None:
                weights[r["name"]] = float(w)
        except ValueError:
            return PlainTextResponse("{} 창/가중치 숫자 아님".format(r["name"]), status_code=422)
    if freeze is None:  # 미지정 → META freeze_default (L·W 등 layout 결정 물리량)
        fz = tuple(r["name"] for r in reg if r["supported"] and r["freeze_default"])
    else:
        fz = tuple(s for s in (t.strip() for t in freeze.split(",")) if s)
    _OPT_PROG["done"], _OPT_PROG["total"], _OPT_PROG["mode"] = 0, 0, "fd-legacy"
    _OPT_LIVE["rows"] = []
    try:
        return _save_opt_run("legacy", request.query_params, optimize_mna(
            layout, corner=corner, force=force, ground=ground,
            hbm_kv=hbm_kv, cap_lim=cap_lim_pf * 1e-12,
            windows=windows, weights=weights,
            mu_soa=mu_soa, mu_rule=mu_rule, lr=lr, iters=iters,
            progress_cb=_opt_tick, freeze=fz, pset=p,
            barrier=barrier, mu_bar=mu_bar, live_cb=_opt_live_push))
    except ValueError as ex:
        return PlainTextResponse(str(ex), status_code=422)


@app.post(PREFIX + "/api/schematic/matrix/preview")
async def schematic_matrix_preview(request: Request, inject: str = "IO", ground: str = "VSS",
                                   i: float = 1.33, L: float = 350.0,
                                   x1: float = 2.56, x2: float = 1415.232,
                                   corner: str = "worst", model_mode: str = "measured"):
    """POST된 layout(저장 전)을 netlist→MNA로 해석 — 편집 중 topology 확인용 (이슈 #9 P0).
    matrix와 동일하게 model_mode=measured 기본 (주어진 schematic+model → 동적 조립)."""
    from server.netlist import extract_netlist, assemble_and_solve, evaluate_soa_monitors
    ctx, err = _model_ctx_or_err(model_mode, {"x1": x1, "x2": x2}, corner)
    if err:
        return err
    layout = await request.json()
    try:
        nl = extract_netlist(layout)
        sol = assemble_and_solve(nl, inject=inject, ground=ground, I=i, L=L, model_ctx=ctx)
    except (ValueError, KeyError, TypeError) as ex:
        return PlainTextResponse("netlist/solve 실패: {}".format(ex), status_code=422)
    names = nl["nets"]
    return {"nets": sorted(names.values()), "n_nets": len(names),
            "global_ground_nets": [names[g] for g in nl["global_ground_nets"]],
            "local_ground_nets": [names[g] for g in nl["local_ground_nets"]],
            "name_conflicts": nl["name_conflicts"],
            "assoc_conflicts": nl["assoc_conflicts"],
            "monitors": evaluate_soa_monitors(nl, sol), "solution": sol}


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
    # 저장 전 netlist 무결성 검증 (이슈 #9 P0): 이름 충돌이 있으면 거부
    from server.netlist import extract_netlist
    try:
        nl = extract_netlist(layout)
    except Exception as ex:
        return PlainTextResponse("netlist 추출 실패: {}".format(ex), status_code=422)
    if nl["name_conflicts"]:
        return PlainTextResponse("net 이름 충돌: {}".format("; ".join(nl["name_conflicts"])),
                                 status_code=422)
    if nl["assoc_conflicts"]:
        return PlainTextResponse("instance 귀속 충돌: {}".format("; ".join(nl["assoc_conflicts"])),
                                 status_code=422)
    # cap spec role 무결성 (이슈 #14 §3.4 권장안): 저장 시 강제 검증 — silent 0 방지
    from server.netlist import validate_io_cap_contributors
    role_chk = validate_io_cap_contributors(nl)
    if not role_chk["valid"]:
        return PlainTextResponse("IO cap contributor 오류: "
                                 + "; ".join(role_chk["errors"]), status_code=422)
    SCH.save_layout(layout)
    return {"ok": True, "n_nets": len(nl["nets"])}


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
        rvdd = M.rdd_r(L)             # RDD_un1 (정본=model.rdd_r)
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


@app.get(PREFIX + "/subcircuit")
def subcircuit_page():
    return _page("subcircuit.html")


@app.get(PREFIX + "/instance")
def instance_page():
    return _page("instance.html")


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
