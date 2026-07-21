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
        "version": "0.0.3",
        "phase": "0 — regression baseline + display screens (models/circuit/spec/meta)",
        "runtime": "python {} / fastapi".format(sys.version.split()[0]),
        "refs": _refs(),
    }


@app.get(PREFIX + "/api/regression")
def regression():
    outputs, code = [], 0
    for script in ("regression.py", "founding_benchmarks.py"):
        p = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tests", script)],
            capture_output=True, text=True, cwd=ROOT, timeout=300,
        )
        outputs.append("[{}] {}".format(script, (p.stdout + p.stderr).strip()))
        code = code or p.returncode
    return {"exit": code, "output": "\n".join(outputs)}


A_PER_KV = 1.33  # user-fixed spec rule (D9 revised): ESD 1 kV <-> 1.33 A
VICTIM = {"kV": 1.0, "vfail": 4.0}

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


def _victim_cross(c1, c2, vfail):
    """Bisect the smallest I where V_IO(I) = vfail (None if never reached)."""
    ifail = min(c1["e"]["ip"], c2["e"]["ip"])
    if M.series_vio(c1, c2, ifail) < vfail:
        return None, ifail
    lo, hi = 0.0, ifail
    for _ in range(60):
        mid = (lo + hi) / 2
        if M.series_vio(c1, c2, mid) < vfail:
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
           "rio": M.RIO, "rvdd": M.RVDD, "devices": {}, "soa": {}, "path": {}}
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
        gD, gC = _GofI(c1["pos"], i), _GofI(c2["pos"], i)
        gRio, gRvdd = 1 / M.RIO, 1 / M.RVDD
        matrix = [
            [gRio, -gRio, 0, 0],
            [-gRio, gRio + gD, -gD, 0],
            [0, -gD, gD + gRvdd, -gRvdd],
            [0, 0, -gRvdd, gRvdd + gC],
        ]
        op = {"i": i, "v_diode": v1, "v_clamp": v2,
              "v_io": i * (M.RIO + M.RVDD) + v1 + v2,
              "gD": gD, "gC": gC, "gRio": gRio, "gRvdd": gRvdd,
              "matrix": matrix, "b": [i, 0, 0, 0]}
    ascii_lines = [
        "        Rio 0.1Ω(≈70µm)     D_up: diode(x1)     Rvdd 0.5Ω(≈350µm)",
        " IO ○──────/\\/\\/\\──────○ N1 ─────────▶|───────── ○ N2 ──────/\\/\\/\\────── ○ N3",
        "  │                                                                        │",
        " (I_ESD ↑ spec 주입)                                                  Clamp(x2)",
        "  │                                                                        │",
        " VSS ○─────────────────────────────────────────────────────────────────────○",
        "  ┆",
        "  └╌╌╌▶|╌╌╌ D_down = model1 미러 (IO←VSS, 음(−) 스트레스 담당 — D2 결정, Phase 2에서 경로 계산 반영)",
        "",
        " 금속 규칙: 0.5Ω / 350µm (L만 설계변수, W 고정 — D7)",
    ]
    return {
        "ascii": ascii_lines,
        "x1": x1, "x2": x2, "corner": corner,
        "nodes": [
            {"name": "IO", "role": "stress 주입 node (current source)"},
            {"name": "N1", "role": "Rio–D_up 사이"},
            {"name": "N2", "role": "D_up–Rvdd 사이 (VDD rail 시작)"},
            {"name": "N3", "role": "Rvdd–Clamp 사이 (VDD rail 끝)"},
            {"name": "VSS", "role": "기준(ref) node — MNA 미지수에서 제외"},
        ],
        "branches": [
            {"name": "I_ESD", "type": "current source", "nodes": "IO→VSS", "param": "spec 전류 (1kV↔1.33A)"},
            {"name": "Rio", "type": "resistor", "nodes": "IO–N1", "param": "0.1Ω (≈70µm)"},
            {"name": "D_up", "type": "nonlinear (model1 diode)", "nodes": "N1–N2", "param": "x1={}".format(x1)},
            {"name": "Rvdd", "type": "resistor", "nodes": "N2–N3", "param": "0.5Ω (≈350µm)"},
            {"name": "Clamp", "type": "nonlinear (model2 clamp)", "nodes": "N3–VSS", "param": "x2={}".format(x2)},
            {"name": "D_down", "type": "nonlinear (model1 미러)", "nodes": "VSS→IO", "param": "Phase 2 반영 예정"},
        ],
        "mna": {
            "unknowns": ["V(IO)", "V(N1)", "V(N2)", "V(N3)"],
            "ref": "VSS", "size": "4×4", "nnz": "10 / 16 (tridiagonal)",
            "form": "G(v)·Δv = −F(v)  (Newton 일반형, Phase 4)",
            "solve_mode": "현재: 전류구동 직렬 경로 → V(I) 1D 역산 합성 (Newton 불필요, 검증된 fast path)",
        },
        "op": op, "ifail": ifail,
    }


@app.get(PREFIX + "/api/spec")
def spec(x1: float = 2.56, x2: float = 1415.232):
    """ESD spec table: kV levels -> injected current (1kV=1.33A) -> PASS/FAIL per corner."""
    err = _window_error(x1, x2)
    if err:
        return err
    out = {"a_per_kv": A_PER_KV, "victim": dict(VICTIM), "x1": x1, "x2": x2,
           "rio": M.RIO, "rvdd": M.RVDD,
           "tiers": {"minimum": 1.0, "recommended": 1.2, "robust": 1.5},
           "levels": [], "summary": {}}
    cs, ipass = {}, {}
    for corner in ("worst", "best"):
        c1, c2 = _cal(M.D1, x1, corner), _cal(M.D2, x2, corner)
        cross, ifail = _victim_cross(c1, c2, VICTIM["vfail"])
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
        row = {"kv": kv, "i": i, "named_spec": kv == VICTIM["kV"], "corners": {}}
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
                ok = v <= VICTIM["vfail"]
                row["corners"][corner] = {"status": "PASS" if ok else "FAIL_VICTIM", "vio": v,
                                          "m": mm, "tier": tier,
                                          "margin": VICTIM["vfail"] - v,
                                          "usage_diode": i / c1["e"]["ip"], "usage_clamp": i / c2["e"]["ip"]}
        out["levels"].append(row)
    return out


@app.get(PREFIX + "/api/entities")
def entities():
    """Entity catalog (20 items) with implementation status and where to see each one."""
    IMPL, PART, PLAN = "구현", "부분", "계획"
    items = [
        (1, "DeviceModel", IMPL, "server/model.py · 화면: models", "diode/clamp Softplus+보정, 골든 50건이 직접 검증"),
        (2, "SOAEnvelope & CornerPolicy", PART, "server/model.py · 화면: models §3, spec", "envelope 8종+양 corner(D3)+±50% 창(D5)+3단계 해(M=1.0/1.2/1.5, 창립 스펙); curve-endpoint 규약 문서화 예정"),
        (3, "MetalModel", PART, "화면: circuit", "Rio/Rvdd 상수 + 0.5Ω/350µm 규칙; L 변수화(D7)는 Phase 2"),
        (4, "VictimModel", PART, "화면: models §2, spec", "Vb=kV·V_IO (kV=1), Vfail=4V box"),
        (5, "CalibrationPipeline", PLAN, "Phase 1A", "anchor 절차 코드화 + β/scale 사전계산 테이블"),
        (6, "Netlist/Topology", PART, "화면: circuit", "고정 직렬 토폴로지(노드 4+ref); 일반화는 Phase 5"),
        (7, "StressCase & ESDSpec", PART, "화면: spec", "HBM 양(+) 스트레스 1종, 1kV↔1.33A(사용자 확정)"),
        (8, "DesignVariableRegistry", PART, "api/models 422 가드", "x1/x2 + D5 ±50% 창; L 변수는 Phase 2. 창립 rule 비대칭: A/C min=가혹 FAIL(projection 금지), max=성능 준-rule, R min=공정한계/max=EM·Joule"),
        (9, "ProblemSchema (JSON/YAML)", PLAN, "Phase 1A~", "GUI↔solver 경계 계약"),
        (10, "TopologyCompiler", PLAN, "Phase 5", "flatten + hierarchy + Top Cell SOA 집계"),
        (11, "MNAAssembler", PART, "화면: circuit (심볼릭+수치 G 미리보기)", "실제 조립/solve는 Phase 4"),
        (12, "NewtonSolver", PART, "server/model.py VofI", "직렬 fast path(1D 역산)만 구현; 일반 Newton은 Phase 4"),
        (13, "SensitivityEngine", PLAN, "Phase 3", "완전 미분 체인(β/scale/endpoint 포함) — 공식 검증 완료"),
        (14, "LossFunction", PLAN, "Phase 3", "usage 정규화 + cost 승계"),
        (15, "Optimizer", PLAN, "Phase 3", "Adam log-공간 + continuation sweep"),
        (16, "PassFailEvaluator", PART, "화면: spec, models §2", "victim/SOA 판정, corner 양쪽"),
        (17, "ResultStore", PART, "server 메모리 캐시", "직렬화·파라미터 동봉 저장은 추후"),
        (18, "TopologyEditor GUI", PLAN, "Phase 5", ""),
        (19, "AnalysisReport GUI", PART, "화면: models, spec, circuit, meta", "화면 4종 증분 확장 중"),
        (20, "RegressionHarness", IMPL, "tests/ · api/regression · 홈 버튼", "골든 50건 + 창립 벤치마크(3-node MNA, 다중해 toy), Python+JS 이중 러너"),
        (21, "RuleGenerator", PLAN, "창립 스펙 §10 · docs/ROADMAP.md", "최종 산출물: PDK table rule(Aup_min/Adown_min/Aclamp_min/Rpath_max) + pre-screen formula rule. Stage 2(SPICE/PERC sign-off)는 스코프 밖"),
    ]
    return {
        "service": {"version": "0.0.4", "grid_N": M.N, "golden_checks": 50,
                    "runtime": "python {} / fastapi".format(sys.version.split()[0])},
        "decisions": "D1 로컬작업+push · D2 down diode=model1 미러 · D3 corner 양쪽 · D4 Python+HTML · "
                     "D5 ±50% 창 · D6 원시데이터 없음 · D7 L만 변수 · D8 최소 UI · D9 1kV↔1.33A · "
                     "창립: rule 비대칭 · 3단계 해(M 1.0/1.2/1.5) · Top Cell port SOA · 2단계 loss · ground 명시",
        "entities": [{"id": i, "name": n, "status": s, "where": w, "note": t}
                     for i, n, s, w, t in items],
    }


@app.get(PREFIX + "/models")
def models_page():
    return FileResponse(os.path.join(ROOT, "frontend", "models.html"))


@app.get(PREFIX + "/circuit")
def circuit_page():
    return FileResponse(os.path.join(ROOT, "frontend", "circuit.html"))


@app.get(PREFIX + "/spec")
def spec_page():
    return FileResponse(os.path.join(ROOT, "frontend", "spec.html"))


@app.get(PREFIX + "/meta")
def meta_page():
    return FileResponse(os.path.join(ROOT, "frontend", "entities.html"))


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
