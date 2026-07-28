# -*- coding: utf-8 -*-
"""Schematic MNA 기반 optimizer — 궁극 목표의 마지막 조각 (사용자 지시 2026-07-28).

loss 평가기가 analytic 직렬 모델이 아니라 **회로도에서 추출한 netlist의 MNA**다:
candidate (x1, x2, L)마다 실측 곡선을 재보정(저해상도 격자 n)해 선택 시나리오의
±I_spec(HBM 레벨) 두 극성에서 solve하고, schematic 소자 프레임워크의 usage
(soa_endpoints·victim monitor rule·IO cap 예산)로 penalty를 만든다.

  loss = cost(면적) + μSOA·Σ softplus(usage−1) + μRule·(창 위반)

경사는 forward 유한차분(3변수), 갱신은 Adam(정규화 좌표). calib은 (모델, size)
캐시를 호출 간 공유해 유한차분의 재보정을 회피한다. 최종 결과는 §1 MNA solving에
그대로 적용 가능한 (x1, x2, L)이다.
"""
import math

from server import model as M
from server.netlist import (extract_netlist, assemble_and_solve, measured_context,
                            soa_endpoints, device_caps, device_voltages,
                            device_currents, evaluate_soa_monitors)

OPT_N = 500     # loss 평가용 calib 격자 (판정·표시는 정밀 N=4000 경로 그대로)
FD_H = 2e-3     # 정규화 좌표 forward 차분 스텝
U_TARGET = 0.93  # penalty 목표 usage — 저해상도 평가 편향(~3%p) + 설계 guard band


def _softplus(z):
    if z > 30:
        return z
    if z < -30:
        return math.exp(z)
    return math.log1p(math.exp(z))


def design_usages(nl, x1, x2, L, corner, force, ground, i_spec, cap_lim,
                  warm=None, calib_cache=None, n=OPT_N):
    """candidate 설계의 (usage dict, detail dict) — schematic 소자 전부(±I_spec) + cap.

    usage는 loss용 비율, detail은 표시용 절대값(사용자 지시: % 병기 절대값):
      detail[소자] = {size, vp/vn/ip/inn, V±/I± 원시값} · victim은 rule 수량별 stress[V].
      detail["cap"] = {total[F], lim[F]}.
    비수렴/monitor 무효는 큰 usage(3.0)로 penalty (해 신뢰 불가)."""
    ctx = measured_context(x1, x2, corner, n=n, cache=calib_cache)
    eps = soa_endpoints(nl, x1, x2, corner)
    caps = device_caps(nl, x1, x2)
    out, detail = {}, {}
    warm = warm if warm is not None else {}
    for sgn, tag in ((1.0, "+"), (-1.0, "-")):
        sol = assemble_and_solve(nl, inject=force, ground=ground, I=sgn * i_spec, L=L,
                                 model_ctx=ctx, v0=warm.get(tag))
        if not sol["converged"]:
            out["nonconv" + tag] = 3.0
            continue
        warm[tag] = [sol["v"][nm] for nm in sol["unknowns"]]
        dv = device_voltages(nl, sol)
        di = device_currents(nl, sol, model_ctx=ctx)
        for key, e in eps.items():
            if not e:
                continue
            V, I = dv[key], (di.get(key) or 0.0)
            out["{}·V{}".format(key, tag)] = V / e["vp"] if V >= 0 else V / e["vn"]
            out["{}·I{}".format(key, tag)] = I / e["ip"] if I >= 0 else I / e["inn"]
            dd = detail.setdefault(key, {"size": round(e["size"], 4),
                                         "vp": round(e["vp"], 3), "vn": round(e["vn"], 3),
                                         "ip": round(e["ip"], 4), "inn": round(e["inn"], 4)})
            dd["V" + tag] = round(V, 4)
            dd["I" + tag] = round(I, 4)
        for m in evaluate_soa_monitors(nl, sol):
            if m["valid"] and m["checks"]:
                # rule 수량별로 기록 — radar·AS-IS/TO-BE 표가 축/행별로 추적
                dd = detail.setdefault(m["instance"], {})
                for c in m["checks"]:
                    v = c["value"]
                    out["{}·{}{}".format(m["instance"], c["quantity"], tag)] = (
                        v / c["max"] if v >= 0 else v / c["min"])
                    dd[c["quantity"] + tag] = round(v, 4)
            elif not m["valid"]:
                out["{}·invalid{}".format(m["instance"], tag)] = 3.0
    cap_total = sum(c["c0"] for c in caps.values() if c and c["on_io"])
    out["cap(IO)"] = cap_total / cap_lim
    # 집계 spec 항목은 usage 키와 동일 키로 detail 기록 (frontend 표의 동적 생성 원천)
    detail["cap(IO)"] = {"value": cap_total, "lim": cap_lim, "unit": "F", "kind": "spec"}
    return out, detail


def optimize_mna(layout, x1, x2, L, corner="worst", force="IO", ground="VSS",
                 hbm_kv=1.0, cap_lim=5e-12,
                 x1min=0.64, x1max=3.84, x2min=1415.232, x2max=2628.288,
                 lmin=70.0, lmax=1400.0, wA=1.0, wC=1.0, wL=0.0,
                 mu_soa=12.0, mu_rule=20.0, lr=0.06, iters=30, n=OPT_N,
                 progress_cb=None, freeze=()):
    """승계된 초기조건 (x1,x2,L)에서 spec(HBM 레벨·capLim) 하의 Adam 최적화.
    progress_cb(done, total): evaluate 1회=1단위 — 초기 1 + iter당 (활성변수+2)
    (기준+활성 FD+갱신) + 최종 정밀 재평가(저해상도 대비 격자 비율만큼 가중).
    freeze: 고정 변수 이름들 — gradient 마스크(FD 생략+update 생략, 값은 회로
    평가의 상수로 유지). 자유도별 lr이 아니라 마스크가 곧 lr=0과 동치."""
    var_keys = ("x1", "x2", "L")
    for k in freeze:
        if k not in var_keys:
            raise ValueError("freeze 대상 아님: {} (가능: {})".format(k, "/".join(var_keys)))
    active = [i for i, k in enumerate(var_keys) if k not in freeze]
    if not active:
        raise ValueError("모든 설계변수가 고정 — 최적화 대상이 없습니다")
    nl = extract_netlist(layout)
    i_spec = M.hbm_current(hbm_kv)
    warm, ccache = {}, {}
    bounds = ((x1min, x1max), (x2min, x2max), (lmin, lmax))
    w_final = max(1, round(M.N / max(1, n)))
    prog = {"done": 0, "total": 1 + iters * (len(active) + 2) + w_final}

    def _tick(k=1):
        prog["done"] += k
        if progress_cb:
            progress_cb(prog["done"], prog["total"])
    if progress_cb:
        progress_cb(0, prog["total"])

    def to_x(z):
        v = [lo + zi * (hi - lo) for zi, (lo, hi) in zip(z, bounds)]
        return max(v[0], 1e-3), max(v[1], 1.0), max(v[2], 1.0)

    def evaluate(z, n_eval=n):
        xx1, xx2, ll = to_x(z)
        us, det = design_usages(nl, xx1, xx2, ll, corner, force, ground, i_spec, cap_lim,
                                warm=warm, calib_cache=ccache, n=n_eval)
        cost = wA * xx1 / x1max + wC * xx2 / x2max + wL * ll / lmax
        pen = mu_soa * sum(_softplus(8.0 * (u - U_TARGET)) / 8.0 for u in us.values())
        rule = 0.0
        for v, (lo, hi) in zip((xx1, xx2, ll), bounds):
            span = hi - lo
            # 창립 rule 비대칭: min=가혹 FAIL(급경사), max=준-rule(완경사)
            rule += _softplus((lo - v) / (0.01 * span)) + _softplus((v - hi) / (0.05 * span))
        _tick()
        return cost + pen + mu_rule * rule, us, det

    def summarize(z, us):
        xx1, xx2, ll = to_x(z)
        worst_name = max(us, key=lambda k: us[k]) if us else None
        return {"x1": xx1, "x2": xx2, "L": ll,
                "worst": us.get(worst_name, 0.0), "worst_name": worst_name,
                "cap_u": us.get("cap(IO)", 0.0),
                "soa_pass": all(u < 1.0 for u in us.values()),
                "usages": {k: round(u, 4) for k, u in
                           sorted(us.items(), key=lambda kv: -kv[1])[:8]}}

    z = [min(1.2, max(-0.2, (v - lo) / (hi - lo)))
         for v, (lo, hi) in zip((x1, x2, L), bounds)]
    f0, us0, det0 = evaluate(z)
    initial = summarize(z, us0)
    initial["loss"] = f0
    best_f, best_z, best_us, best_it = f0, list(z), us0, 0
    mom = [0.0] * 3
    vel = [0.0] * 3
    b1, b2, eps_ = 0.9, 0.999, 1e-9
    def _round_us(us):
        return {k: round(u, 4) for k, u in us.items()}

    history = [{"it": 0, "loss": f0, "x1": initial["x1"], "x2": initial["x2"],
                "L": initial["L"], "worst": initial["worst"],
                "usages": _round_us(us0), "detail": det0}]
    for it in range(1, iters + 1):
        f_base, us_base, _d0 = evaluate(z)
        grad = {}  # 활성 변수만 FD — 고정 변수는 probe·update 모두 생략(마스크)
        for i in active:
            zp = list(z)
            zp[i] += FD_H
            fp, _u, _d = evaluate(zp)
            grad[i] = (fp - f_base) / FD_H
        for i in active:
            mom[i] = b1 * mom[i] + (1 - b1) * grad[i]
            vel[i] = b2 * vel[i] + (1 - b2) * grad[i] * grad[i]
            mh = mom[i] / (1 - b1 ** it)
            vh = vel[i] / (1 - b2 ** it)
            z[i] = min(1.2, max(-0.2, z[i] - lr * mh / (math.sqrt(vh) + eps_)))
        f_new, us_new, det_new = evaluate(z)
        if f_new < best_f:
            best_f, best_z, best_us, best_it = f_new, list(z), us_new, it
        s = summarize(z, us_new)
        history.append({"it": it, "loss": f_new, "x1": s["x1"], "x2": s["x2"],
                        "L": s["L"], "worst": s["worst"],
                        "usages": _round_us(us_new), "detail": det_new})
    # 최종 후보를 정밀 격자(N)로 재평가 — 저해상도 편향 제거
    xb1, xb2, lb = to_x(best_z)
    us_final, det_final = design_usages(nl, xb1, xb2, lb, corner, force, ground,
                                        i_spec, cap_lim, warm={}, calib_cache={}, n=M.N)
    _tick(w_final)
    final = summarize(best_z, us_final)
    final["loss"] = best_f
    final["detail"] = det_final
    return {"initial": initial, "final": final, "history": history,
            "best_it": best_it,  # 최적해 iteration — 마지막 step이 아닐 수 있음(Adam 관성)
            # 설계변수 descriptor — AS-IS/TO-BE 표의 동적 생성 원천 (하드코딩 금지)
            "variables": [
                {"key": "x1", "name": "x1 (diode size)", "lo": x1min, "hi": x1max,
                 "unit": "", "dec": 3, "kind": "rule", "frozen": "x1" in freeze},
                {"key": "x2", "name": "x2 (clamp size)", "lo": x2min, "hi": x2max,
                 "unit": "", "dec": 1, "kind": "rule", "frozen": "x2" in freeze},
                {"key": "L", "name": "L (RDD 금속)", "lo": lmin, "hi": lmax,
                 "unit": "µm", "dec": 1, "kind": "rule", "frozen": "L" in freeze},
            ],
            "i_spec": i_spec, "hbm_kv": hbm_kv, "cap_lim": cap_lim,
            "force": force, "ground": ground, "corner": corner, "iters": iters}
