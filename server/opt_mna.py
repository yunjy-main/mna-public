# -*- coding: utf-8 -*-
"""Schematic MNA 기반 optimizer — 궁극 목표의 마지막 조각 (사용자 지시 2026-07-28).

loss 평가기가 analytic 직렬 모델이 아니라 **회로도에서 추출한 netlist의 MNA**다:
candidate pset(자유 파라미터 dict)마다 실측 곡선을 재보정(저해상도 격자 n)해
선택 시나리오의 ±I_spec(HBM 레벨) 두 극성에서 solve하고, schematic 소자
프레임워크의 usage(soa_endpoints·victim monitor rule·IO cap 예산)로 penalty를 만든다.

  loss = cost(자원) + μSOA·Σ softplus(usage−target) + μRule·(창 위반)

설계변수는 이름 하드코딩이 아니라 **registry(schematic 발견+PARAM_META)에서 N-차원
자동 구성**된다 (이슈 #11 §2.5): 창=META rule(override 가능), cost 가중치=META cost_w,
rule 창 없는 파라미터는 변수화 불가 → 강제 고정(E3). 경사는 활성 변수만 forward
유한차분, 갱신은 Adam(정규화 좌표). calib은 (모델, size) 캐시를 호출 간 공유해
유한차분의 재보정을 회피한다. 최종 결과는 §1 MNA solving에 그대로 적용 가능한 pset이다.
"""
import math

from server import model as M
from server.netlist import (extract_netlist, assemble_and_solve, measured_context,
                            soa_endpoints, device_voltages,
                            device_currents, evaluate_soa_monitors,
                            io_cap_at_zero, params_registry, _pset)

OPT_N = 500     # loss 평가용 calib 격자 (판정·표시는 정밀 N=4000 경로 그대로)
FD_H = 2e-3     # 정규화 좌표 forward 차분 스텝
U_TARGET = 0.93  # penalty 목표 usage — 저해상도 평가 편향(~3%p) + 설계 guard band


def _softplus(z):
    if z > 30:
        return z
    if z < -30:
        return math.exp(z)
    return math.log1p(math.exp(z))


def _logbar(v, lo, hi, eps=1e-3):
    """내부 log barrier (max쪽, 사용자 확정 2026-07-28) — B = −ln((hi−v)/span).
    창 내부에서는 힘(μb/(hi−v))이 미미해 margin을 끝까지 소모하고, 벽에서 발산해
    limit 불가침. z-clip이 창 밖(v≥hi)을 허용하므로 u≤ε에서 C¹ 선형 연장."""
    span = hi - lo
    u = (hi - v) / span
    if u > eps:
        return -math.log(u)
    return -math.log(eps) + (eps - u) / eps


def _wallq(v, lo, hi, k=500.0):
    """창 밖 이차 복원벽 (μb-독립 백스톱) — 내부 힘 0(margin 소모 무방해),
    이탈 시 위반량에 비례한 복원력. ε-연장 기울기가 μb에 비례해 μb가 작으면
    이탈하던 결함(발견: μb=0.002에서 W=13.6) 교정."""
    u = (v - hi) / (hi - lo)
    return k * u * u if u > 0 else 0.0


def design_usages(nl, pset, corner, force, ground, i_spec, cap_lim,
                  warm=None, calib_cache=None, n=OPT_N):
    """candidate pset의 (usage dict, detail dict) — schematic 소자 전부(±I_spec) + cap.

    usage는 loss용 비율, detail은 표시용 절대값(사용자 지시: % 병기 절대값):
      detail[소자] = {size, vp/vn/ip/inn, V±/I± 원시값} · victim은 rule 수량별 stress[V].
      detail["cap(IO)"] = {value[F], lim[F]}.
    비수렴/monitor 무효는 큰 usage(3.0)로 penalty (해 신뢰 불가)."""
    ctx = measured_context(corner=corner, n=n, cache=calib_cache, pset=pset)
    eps = soa_endpoints(nl, corner=corner, pset=pset)
    out, detail = {}, {}
    warm = warm if warm is not None else {}
    for sgn, tag in ((1.0, "+"), (-1.0, "-")):
        sol = assemble_and_solve(nl, inject=force, ground=ground, I=sgn * i_spec,
                                 pset=pset, model_ctx=ctx, v0=warm.get(tag))
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
    # cap spec 정본 = io_cap_at_zero (contributor 집합 합, #15 §3.6)
    cap_total = io_cap_at_zero(nl, pset=pset)
    out["cap(IO)"] = cap_total / cap_lim
    # 집계 spec 항목은 usage 키와 동일 키로 detail 기록 (frontend 표의 동적 생성 원천)
    detail["cap(IO)"] = {"value": cap_total, "lim": cap_lim, "unit": "F", "kind": "spec"}
    return out, detail


def optimize_mna(layout, x1=None, x2=None, L=None, corner="worst", force="IO",
                 ground="VSS", hbm_kv=1.0, cap_lim=5e-12,
                 windows=None, weights=None,
                 mu_soa=12.0, mu_rule=20.0, lr=0.06, iters=30, n=OPT_N,
                 progress_cb=None, freeze=(), pset=None,
                 barrier="log", mu_bar=0.01):
    """승계된 초기조건 pset에서 spec(HBM 레벨·capLim) 하의 Adam 최적화 (N-차원 자동).

    설계변수 = registry supported 파라미터 (순서 = registry 정본 순서).
    windows/weights: {name: (lo,hi)}/{name: w} override — 미지정 시 META rule/cost_w.
    freeze: 고정 변수 이름들 — gradient 마스크(FD·update 생략, 값은 회로 평가의 상수).
    rule 창 없는 변수는 강제 고정(E3, lockable=false). x1/x2/L kwarg는 동결 legacy.
    barrier(max쪽 모양, 사용자 확정 2026-07-28 — min쪽은 항상 가혹 FAIL 급경사):
      "log"(기본) = 내부 log barrier μb·(−ln((hi−v)/span)) — margin 최대 소모,
        잔여 margin ≈ μb/F(SOA 힘), limit 발산 벽 불가침;
      "softplus" = 기존 준-rule 완경사 μRule·softplus((v−hi)/(0.05·span)).
    progress_cb(done, total): evaluate 1회=1단위 — 초기 1 + iter당 (활성변수+2)
    + 최종 정밀 재평가(격자 비율 가중)."""
    if barrier not in ("log", "softplus"):
        raise ValueError("barrier must be log|softplus")
    nl = extract_netlist(layout)
    reg = [r for r in params_registry(nl) if r["supported"]]
    p0 = _pset(pset, x1=x1, x2=x2, L=L)
    var_spec = []
    for r in reg:
        ov = (windows or {}).get(r["name"])
        lo, hi = ov if ov else (r["rule_lo"], r["rule_hi"])
        if lo is not None and hi is not None and not (hi > lo):
            raise ValueError("{} 창 무효: {} ~ {}".format(r["name"], lo, hi))
        forced = lo is None or hi is None  # E3: rule 창 없음 → 변수화 불가
        var_spec.append({"key": r["name"], "name": r["label"], "lo": lo, "hi": hi,
                         "unit": r["unit"], "dec": r["dec"], "kind": "rule",
                         "cost_w": (weights or {}).get(r["name"], r["cost_w"]),
                         "frozen": forced or (r["name"] in freeze),
                         "lockable": not forced})
    keys = [v["key"] for v in var_spec]
    for k in freeze:
        if k not in keys:
            raise ValueError("freeze 대상 아님: {} (가능: {})".format(k, "/".join(keys)))
    active = [i for i, v in enumerate(var_spec) if not v["frozen"]]
    if not active:
        raise ValueError("모든 설계변수가 고정 — 최적화 대상이 없습니다")
    i_spec = M.hbm_current(hbm_kv)
    warm, ccache = {}, {}
    w_final = max(1, round(M.N / max(1, n)))
    prog = {"done": 0, "total": 1 + iters * (len(active) + 2) + w_final}

    def _tick(k=1):
        prog["done"] += k
        if progress_cb:
            progress_cb(prog["done"], prog["total"])
    if progress_cb:
        progress_cb(0, prog["total"])

    def to_p(z):
        p = dict(p0)
        for i in active:
            v = var_spec[i]
            p[v["key"]] = max(v["lo"] + z[i] * (v["hi"] - v["lo"]), 1e-3)
        return p

    def evaluate(z, n_eval=n):
        pv = to_p(z)
        us, det = design_usages(nl, pv, corner, force, ground, i_spec, cap_lim,
                                warm=warm, calib_cache=ccache, n=n_eval)
        cost = sum(v["cost_w"] * pv[v["key"]] / v["hi"] for v in var_spec if v["hi"])
        pen = mu_soa * sum(_softplus(8.0 * (u - U_TARGET)) / 8.0 for u in us.values())
        rule = 0.0
        for i in active:
            v = var_spec[i]
            val, span = pv[v["key"]], v["hi"] - v["lo"]
            # min쪽은 항상 가혹 FAIL 급경사 (창립 비대칭 유지)
            rule += mu_rule * _softplus((v["lo"] - val) / (0.01 * span))
            if barrier == "log":  # max쪽: margin 최대 소모 + limit 벽
                # 내부 log(잔여 margin≈μb/F 제어) + 창 밖 이차 복원벽(μb-독립,
                # 내부 힘 0 — softplus 백스톱은 내부 꼬리가 소모를 막았음)
                rule += (mu_bar * _logbar(val, v["lo"], v["hi"])
                         + mu_rule * _wallq(val, v["lo"], v["hi"]))
            else:                 # max쪽: 기존 준-rule 완경사
                rule += mu_rule * _softplus((val - v["hi"]) / (0.05 * span))
        _tick()
        return cost + pen + rule, us, det

    def summarize(z, us):
        pv = to_p(z)
        worst_name = max(us, key=lambda k: us[k]) if us else None
        s = {v["key"]: pv[v["key"]] for v in var_spec}
        s.update({"worst": us.get(worst_name, 0.0), "worst_name": worst_name,
                  "cap_u": us.get("cap(IO)", 0.0),
                  "soa_pass": all(u < 1.0 for u in us.values()),
                  "usages": {k: round(u, 4) for k, u in
                             sorted(us.items(), key=lambda kv: -kv[1])[:8]}})
        return s

    def _hist(it, loss, s, us, det):
        row = {"it": it, "loss": loss, "worst": s["worst"],
               "usages": {k: round(u, 4) for k, u in us.items()}, "detail": det}
        for k in keys:
            row[k] = s[k]
        return row

    z = [0.0] * len(var_spec)
    for i, v in enumerate(var_spec):
        if v["lo"] is not None and v["hi"] is not None:
            z[i] = min(1.2, max(-0.2, (p0[v["key"]] - v["lo"]) / (v["hi"] - v["lo"])))
    f0, us0, det0 = evaluate(z)
    initial = summarize(z, us0)
    initial["loss"] = f0
    best_f, best_z, best_us, best_it = f0, list(z), us0, 0
    mom = [0.0] * len(var_spec)
    vel = [0.0] * len(var_spec)
    b1, b2, eps_ = 0.9, 0.999, 1e-9
    history = [_hist(0, f0, initial, us0, det0)]
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
        history.append(_hist(it, f_new, summarize(z, us_new), us_new, det_new))
    # 최종 후보를 정밀 격자(N)로 재평가 — 저해상도 편향 제거.
    # 탐색 중 이차 복원벽 안쪽의 미세 grazing(<0.002 창폭)이 있을 수 있어 창으로 클램프
    # — 납품 설계는 rule 창을 정확히 준수한다.
    for i in active:  # z=1.0 ⇔ v=hi
        best_z[i] = min(best_z[i], 1.0)
    us_final, det_final = design_usages(nl, to_p(best_z), corner, force, ground,
                                        i_spec, cap_lim, warm={}, calib_cache={}, n=M.N)
    _tick(w_final)
    final = summarize(best_z, us_final)
    final["loss"] = best_f
    final["detail"] = det_final
    return {"initial": initial, "final": final, "history": history,
            "best_it": best_it,  # 최적해 iteration — 마지막 step이 아닐 수 있음(Adam 관성)
            "pset": p0,
            # 설계변수 descriptor — AS-IS/TO-BE 표·§3 행 동적 생성 원천 (하드코딩 금지)
            "variables": [{"key": v["key"], "name": v["name"], "lo": v["lo"],
                           "hi": v["hi"], "unit": v["unit"], "dec": v["dec"],
                           "kind": v["kind"], "frozen": v["frozen"],
                           "lockable": v["lockable"]} for v in var_spec],
            "i_spec": i_spec, "hbm_kv": hbm_kv, "cap_lim": cap_lim,
            "force": force, "ground": ground, "corner": corner, "iters": iters,
            "barrier": barrier, "mu_bar": mu_bar}
