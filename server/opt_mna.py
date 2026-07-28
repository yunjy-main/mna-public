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
    """candidate 설계의 usage dict — schematic 소자 전부(±I_spec 두 극성) + cap.
    비수렴/monitor 무효는 큰 usage(3.0)로 penalty (해 신뢰 불가)."""
    ctx = measured_context(x1, x2, corner, n=n, cache=calib_cache)
    eps = soa_endpoints(nl, x1, x2, corner)
    caps = device_caps(nl, x1, x2)
    out = {}
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
        for m in evaluate_soa_monitors(nl, sol):
            if m["valid"] and m["checks"]:
                u = 0.0
                for c in m["checks"]:
                    v = c["value"]
                    u = max(u, v / c["max"] if v >= 0 else v / c["min"])
                out["{}·SOA{}".format(m["instance"], tag)] = u
            elif not m["valid"]:
                out["{}·invalid{}".format(m["instance"], tag)] = 3.0
    out["cap(IO)"] = sum(c["c0"] for c in caps.values() if c and c["on_io"]) / cap_lim
    return out


def optimize_mna(layout, x1, x2, L, corner="worst", force="IO", ground="VSS",
                 hbm_kv=1.0, cap_lim=5e-12,
                 x1min=0.64, x1max=3.84, x2min=1415.232, x2max=2628.288,
                 lmin=70.0, lmax=1400.0, wA=1.0, wC=1.0, wL=0.0,
                 mu_soa=12.0, mu_rule=20.0, lr=0.06, iters=30, n=OPT_N):
    """승계된 초기조건 (x1,x2,L)에서 spec(HBM 레벨·capLim) 하의 Adam 최적화."""
    nl = extract_netlist(layout)
    i_spec = M.hbm_current(hbm_kv)
    warm, ccache = {}, {}
    bounds = ((x1min, x1max), (x2min, x2max), (lmin, lmax))

    def to_x(z):
        v = [lo + zi * (hi - lo) for zi, (lo, hi) in zip(z, bounds)]
        return max(v[0], 1e-3), max(v[1], 1.0), max(v[2], 1.0)

    def evaluate(z, n_eval=n):
        xx1, xx2, ll = to_x(z)
        us = design_usages(nl, xx1, xx2, ll, corner, force, ground, i_spec, cap_lim,
                           warm=warm, calib_cache=ccache, n=n_eval)
        cost = wA * xx1 / x1max + wC * xx2 / x2max + wL * ll / lmax
        pen = mu_soa * sum(_softplus(8.0 * (u - U_TARGET)) / 8.0 for u in us.values())
        rule = 0.0
        for v, (lo, hi) in zip((xx1, xx2, ll), bounds):
            sc = 0.05 * (hi - lo)
            rule += _softplus((lo - v) / sc) + _softplus((v - hi) / sc)
        return cost + pen + mu_rule * 0.1 * rule, us

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
    f0, us0 = evaluate(z)
    initial = summarize(z, us0)
    initial["loss"] = f0
    best_f, best_z, best_us = f0, list(z), us0
    mom = [0.0] * 3
    vel = [0.0] * 3
    b1, b2, eps_ = 0.9, 0.999, 1e-9
    history = [{"it": 0, "loss": f0, "x1": initial["x1"], "x2": initial["x2"],
                "L": initial["L"], "worst": initial["worst"]}]
    for it in range(1, iters + 1):
        f_base, us_base = evaluate(z)
        grad = []
        for i in range(3):
            zp = list(z)
            zp[i] += FD_H
            fp, _ = evaluate(zp)
            grad.append((fp - f_base) / FD_H)
        for i in range(3):
            mom[i] = b1 * mom[i] + (1 - b1) * grad[i]
            vel[i] = b2 * vel[i] + (1 - b2) * grad[i] * grad[i]
            mh = mom[i] / (1 - b1 ** it)
            vh = vel[i] / (1 - b2 ** it)
            z[i] = min(1.2, max(-0.2, z[i] - lr * mh / (math.sqrt(vh) + eps_)))
        f_new, us_new = evaluate(z)
        if f_new < best_f:
            best_f, best_z, best_us = f_new, list(z), us_new
        s = summarize(z, us_new)
        history.append({"it": it, "loss": f_new, "x1": s["x1"], "x2": s["x2"],
                        "L": s["L"], "worst": s["worst"]})
    # 최종 후보를 정밀 격자(N)로 재평가 — 저해상도 편향 제거
    xb1, xb2, lb = to_x(best_z)
    us_final = design_usages(nl, xb1, xb2, lb, corner, force, ground, i_spec, cap_lim,
                             warm={}, calib_cache={}, n=M.N)
    final = summarize(best_z, us_final)
    final["loss"] = best_f
    return {"initial": initial, "final": final, "history": history,
            "i_spec": i_spec, "hbm_kv": hbm_kv, "cap_lim": cap_lim,
            "force": force, "ground": ground, "corner": corner, "iters": iters}
