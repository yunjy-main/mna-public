# -*- coding: utf-8 -*-
"""Constraint·feasibility 기반 optimizer (이슈 #12 수학, #13 가이드).

legacy(opt_mna.py: cost+softplus+barrier)와 별도 엔드포인트로 병행한다(사용자 확정).

  J_obj = α_rule·L_rule + α_SOA·L_SOA + α_spec·L_spec,  φ(g) = ½·max(0,g)²
  L_* = Σ φ(g_j) — 모든 조건은 표준형 g_j ≤ 0 : PASS 로 통일.

- L_rule: x1/x2/W/L의 min/max 창 위반 (span 정규화)
- L_SOA : (stress case, device, quantity)별 signed usage u_j, g = u_j − 1
- L_spec: 0V direct up/down diode cap 합(direct_io_cap) — ESD 해와 분리, x1만의 함수
- size/resource cost 없음, U_TARGET guard band 없음 (기준은 정확히 u ≤ 1)
- barrier 기본 off (탐색 중 design-rule 위반 허용 — hinge가 복원), final clamp 금지
- best_feasible / best_infeasible 분리, 비수렴은 solver status로 격리 (usage 혼합 금지)
- 최종 PASS = 모든 원래 constraint의 g_j ≤ 0 (objective 크기로 판정하지 않음)

gradient: grad="fd"(S1, forward FD — S5 대조 oracle) → S3에서 adjoint 추가 예정.
변수명 주의: L은 metal length — loss는 loss_*/J_obj로만 표기 (이슈 #13 원칙).
"""
import math

from server import model as M
from server.netlist import (extract_netlist, assemble_and_solve, measured_context,
                            soa_endpoints, device_voltages, device_currents,
                            evaluate_soa_monitors, direct_io_cap, params_registry, _pset)

FEAS_N = 500        # FD 탐색용 저해상 calib 격자 (best 후보는 정밀 N 재평가로 재판정)
FD_H = 2e-3         # 정규화 좌표 forward 차분 스텝
ALLOWED_VARS = ("x1", "x2", "W", "L")  # 이슈 #13: 자유도는 이 넷만 명시 사용


def _phi(g):
    """squared hinge — PASS(g≤0) 항목은 값·gradient 모두 0."""
    return 0.5 * g * g if g > 0.0 else 0.0


def evaluate_candidate(nl, pset, corner, force, ground, i_spec, cap_lim,
                       windows=None, alphas=(1.0, 1.0, 1.0),
                       warm=None, calib_cache=None, n=FEAS_N):
    """candidate pset의 constraint 전수 평가 (이슈 #13 4.1.A 스키마).

    반환: {solver, constraints{rule,soa,spec}, losses{rule,soa,spec,total},
           feasible, detail(legacy 표시 호환), usages(legacy 키 호환)}.
    비수렴 케이스는 SOA usage에 섞지 않고 solver status로만 기록 → feasible=False."""
    ctx = measured_context(corner=corner, n=n, cache=calib_cache, pset=pset)
    eps = soa_endpoints(nl, corner=corner, pset=pset)
    warm = warm if warm is not None else {}
    cons = {"rule": [], "soa": [], "spec": []}
    solver = {}
    detail = {}

    # ── rule (전 변수 — 판정에는 frozen 포함, gradient는 optimizer가 active만 사용)
    for name, (lo, hi) in (windows or {}).items():
        v, span = pset.get(name), (hi - lo) or 1.0
        cons["rule"].append({"key": "{}·min".format(name), "category": "rule",
                             "stress_case": None, "device": None, "quantity": name,
                             "value": v, "limit_min": lo, "limit_max": hi,
                             "usage": None, "g": (lo - v) / span, "passed": v >= lo})
        cons["rule"].append({"key": "{}·max".format(name), "category": "rule",
                             "stress_case": None, "device": None, "quantity": name,
                             "value": v, "limit_min": lo, "limit_max": hi,
                             "usage": None, "g": (v - hi) / span, "passed": v <= hi})

    # ── SOA (±spec 전류 MNA — 케이스별)
    for sgn, tag in ((1.0, "+"), (-1.0, "-")):
        sol = assemble_and_solve(nl, inject=force, ground=ground, I=sgn * i_spec,
                                 pset=pset, model_ctx=ctx, v0=warm.get(tag))
        solver[tag] = {"converged": sol["converged"], "residual": sol["residual_norm"],
                       "newton_iters": sol["newton_iters"]}
        if not sol["converged"]:
            continue  # usage 혼합 금지 — solver status가 infeasible을 만든다
        warm[tag] = [sol["v"][nm] for nm in sol["unknowns"]]
        dv = device_voltages(nl, sol)
        di = device_currents(nl, sol, model_ctx=ctx)
        for key, e in eps.items():
            if not e:
                continue
            V, I = dv[key], (di.get(key) or 0.0)
            uV = V / e["vp"] if V >= 0 else V / e["vn"]
            uI = I / e["ip"] if I >= 0 else I / e["inn"]
            cons["soa"].append({"key": "{}·V{}".format(key, tag), "category": "soa",
                                "stress_case": tag, "device": key, "quantity": "V",
                                "value": V, "limit_min": e["vn"], "limit_max": e["vp"],
                                "usage": uV, "g": uV - 1.0, "passed": uV <= 1.0})
            cons["soa"].append({"key": "{}·I{}".format(key, tag), "category": "soa",
                                "stress_case": tag, "device": key, "quantity": "I",
                                "value": I, "limit_min": e["inn"], "limit_max": e["ip"],
                                "usage": uI, "g": uI - 1.0, "passed": uI <= 1.0})
            dd = detail.setdefault(key, {"size": round(e["size"], 4),
                                         "vp": round(e["vp"], 3), "vn": round(e["vn"], 3),
                                         "ip": round(e["ip"], 4), "inn": round(e["inn"], 4)})
            dd["V" + tag] = round(V, 4)
            dd["I" + tag] = round(I, 4)
        for m in evaluate_soa_monitors(nl, sol):
            if not m["valid"]:
                solver[tag]["monitor_invalid"] = m["reason"]
                continue
            dd = detail.setdefault(m["instance"], {})
            for c in m["checks"]:
                val = c["value"]
                u = val / c["max"] if val >= 0 else val / c["min"]
                cons["soa"].append({"key": "{}·{}{}".format(m["instance"], c["quantity"], tag),
                                    "category": "soa", "stress_case": tag,
                                    "device": m["instance"], "quantity": c["quantity"],
                                    "value": val, "limit_min": c["min"], "limit_max": c["max"],
                                    "usage": u, "g": u - 1.0, "passed": u <= 1.0})
                dd[c["quantity"] + tag] = round(val, 4)

    # ── spec: 0V direct up/down cap (ESD 해와 분리 — x1만의 함수)
    c_io = direct_io_cap(nl, pset=pset)
    u_cap = c_io / cap_lim
    cons["spec"].append({"key": "cap(IO)", "category": "spec", "stress_case": None,
                         "device": None, "quantity": "C_IO", "value": c_io,
                         "limit_min": None, "limit_max": cap_lim,
                         "usage": u_cap, "g": u_cap - 1.0, "passed": u_cap <= 1.0})
    detail["cap(IO)"] = {"value": c_io, "lim": cap_lim, "unit": "F", "kind": "spec"}

    a_rule, a_soa, a_spec = alphas
    losses = {"rule": sum(_phi(c["g"]) for c in cons["rule"]),
              "soa": sum(_phi(c["g"]) for c in cons["soa"]),
              "spec": sum(_phi(c["g"]) for c in cons["spec"])}
    losses["total"] = a_rule * losses["rule"] + a_soa * losses["soa"] + a_spec * losses["spec"]
    all_cons = cons["rule"] + cons["soa"] + cons["spec"]
    feasible = (all(s["converged"] for s in solver.values())
                and "monitor_invalid" not in solver["+"]
                and "monitor_invalid" not in solver["-"]
                and all(c["passed"] for c in all_cons))
    usages = {c["key"]: c["usage"] for c in all_cons if c["usage"] is not None}
    return {"solver": solver, "constraints": cons, "losses": losses,
            "feasible": feasible, "detail": detail, "usages": usages}


def _violation_score(ev):
    """best_infeasible 비교 키 (이슈 #13 4.1.F): max 위반 → 총 위반 → residual."""
    all_c = ev["constraints"]["rule"] + ev["constraints"]["soa"] + ev["constraints"]["spec"]
    conv_pen = 0.0 if all(s["converged"] for s in ev["solver"].values()) else 1e6
    return (conv_pen + max([max(0.0, c["g"]) for c in all_c] or [0.0]),
            sum(max(0.0, c["g"]) ** 2 for c in all_c),
            max(s["residual"] for s in ev["solver"].values()))


def optimize_feas(layout, corner="worst", force="IO", ground="VSS",
                  hbm_kv=1.0, cap_lim=5e-12, windows=None,
                  alphas=(1.0, 1.0, 1.0), barrier="off", mu_bar=0.01, mu_rule=20.0,
                  lr=0.06, iters=30, n=FEAS_N, grad="fd",
                  freeze=(), pset=None, stop_on_feasible=False, progress_cb=None):
    """Feasibility optimizer 본체 (이슈 #13 §3·§4.1) — Adam + (S1) forward FD gradient.

    barrier: off(기본 — hinge만, 경계 통과 허용) | log | softplus (preference 옵션).
    stop_on_feasible: 기본 False(사용자 확정) — iters 완주하며 best_feasible 갱신
    (residual 최소 기준). final clamp 없음 — 실제 candidate의 feasibility를 보고."""
    if barrier not in ("off", "log", "softplus"):
        raise ValueError("barrier must be off|log|softplus")
    if grad not in ("fd",):  # adjoint는 S3에서 추가
        raise ValueError("grad must be fd (adjoint는 S3 예정)")
    nl = extract_netlist(layout)
    reg = [r for r in params_registry(nl)
           if r["supported"] and r["name"] in ALLOWED_VARS]
    p0 = _pset(pset)
    var_spec = []
    for r in reg:
        ov = (windows or {}).get(r["name"])
        lo, hi = ov if ov else (r["rule_lo"], r["rule_hi"])
        if lo is not None and hi is not None and not (hi > lo):
            raise ValueError("{} 창 무효: {} ~ {}".format(r["name"], lo, hi))
        forced = lo is None or hi is None
        var_spec.append({"key": r["name"], "name": r["label"], "lo": lo, "hi": hi,
                         "unit": r["unit"], "dec": r["dec"], "kind": "rule",
                         "frozen": forced or (r["name"] in freeze),
                         "lockable": not forced})
    keys = [v["key"] for v in var_spec]
    for k in freeze:
        if k not in keys:
            raise ValueError("freeze 대상 아님: {} (가능: {})".format(k, "/".join(keys)))
    active = [i for i, v in enumerate(var_spec) if not v["frozen"]]
    if not active:
        raise ValueError("모든 설계변수가 고정 — 최적화 대상이 없습니다")
    win = {v["key"]: (v["lo"], v["hi"]) for v in var_spec if v["lo"] is not None}
    i_spec = M.hbm_current(hbm_kv)
    warm, ccache = {}, {}
    w_final = max(1, round(M.N / max(1, n)))
    prog = {"done": 0, "total": 1 + iters * (len(active) + 2) + 2 * w_final}

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

    def barrier_term(pv):
        if barrier == "off":
            return 0.0
        from server.opt_mna import _logbar, _softplus, _wallq
        b = 0.0
        for i in active:
            v = var_spec[i]
            val, span = pv[v["key"]], v["hi"] - v["lo"]
            if barrier == "log":
                b += mu_bar * _logbar(val, v["lo"], v["hi"]) + mu_rule * _wallq(val, v["lo"], v["hi"])
            else:
                b += mu_rule * _softplus((val - v["hi"]) / (0.05 * span))
        return b

    def evaluate(z, n_eval=n):
        pv = to_p(z)
        ev = evaluate_candidate(nl, pv, corner, force, ground, i_spec, cap_lim,
                                windows=win, alphas=alphas,
                                warm=warm, calib_cache=ccache, n=n_eval)
        _tick()
        return ev["losses"]["total"] + barrier_term(pv), ev

    z = [0.0] * len(var_spec)
    for i, v in enumerate(var_spec):
        if v["lo"] is not None:
            z[i] = min(1.2, max(-0.2, (p0[v["key"]] - v["lo"]) / (v["hi"] - v["lo"])))
    best_feasible = None   # (z, ev) — residual 최소 갱신
    best_infeasible = None  # (z, ev, score) — 위반 사전식 최소
    history = []
    mom, vel = [0.0] * len(var_spec), [0.0] * len(var_spec)
    b1, b2, eps_ = 0.9, 0.999, 1e-9

    def _record(it, jv, ev, z_now, gradient):
        pv = to_p(z_now)
        worst_c = max((ev["constraints"]["soa"] + ev["constraints"]["spec"]) or [],
                      key=lambda c: (c["usage"] if c["usage"] is not None else -1e9),
                      default=None)
        row = {"it": it, "J_obj": jv, "loss": jv,  # loss=legacy 호환 별칭
               "losses": {k: round(x, 6) for k, x in ev["losses"].items()},
               "feasible": ev["feasible"], "soa_pass": ev["feasible"],
               "solver": {t: s["converged"] for t, s in ev["solver"].items()},
               "gradient": gradient,
               "worst": (worst_c["usage"] if worst_c else 0.0),
               "worst_name": (worst_c["key"] if worst_c else None),
               "cap_u": ev["usages"].get("cap(IO)", 0.0),
               "usages": {k: round(u, 4) for k, u in ev["usages"].items()},
               "detail": ev["detail"]}
        for k in keys:
            row[k] = pv[k]
        history.append(row)

    def _consider(z_now, ev):
        nonlocal best_feasible, best_infeasible
        if ev["feasible"]:
            # feasible 간 우열: margin 최대(max usage 최소) → residual — 저해상 평가의
            # 정밀 재판정 뒤집힘 위험을 최소화 (#13 4.1.F의 'robustness가 좋은 feasible')
            sc = (max([u for u in ev["usages"].values()] or [0.0]),
                  max(s["residual"] for s in ev["solver"].values()))
            if best_feasible is None or sc < best_feasible[2]:
                best_feasible = (list(z_now), ev, sc)
        else:
            sc = _violation_score(ev)
            if best_infeasible is None or sc < best_infeasible[2]:
                best_infeasible = (list(z_now), ev, sc)

    j0, ev0 = evaluate(z)
    _consider(z, ev0)
    _record(0, j0, ev0, z, None)
    stopped_feasible = False
    for it in range(1, iters + 1):
        if stop_on_feasible and best_feasible is not None:
            stopped_feasible = True
            break
        f_base, _ev = evaluate(z)
        gradient = {}
        for i in active:
            zp = list(z)
            zp[i] += FD_H
            fp, _e = evaluate(zp)
            gradient[var_spec[i]["key"]] = (fp - f_base) / FD_H
        for i in active:
            gi = gradient[var_spec[i]["key"]]
            mom[i] = b1 * mom[i] + (1 - b1) * gi
            vel[i] = b2 * vel[i] + (1 - b2) * gi * gi
            mh = mom[i] / (1 - b1 ** it)
            vh = vel[i] / (1 - b2 ** it)
            z[i] = min(1.2, max(-0.2, z[i] - lr * mh / (math.sqrt(vh) + eps_)))
        j_new, ev_new = evaluate(z)
        _consider(z, ev_new)
        _record(it, j_new, ev_new,
                z, {k: round(g, 6) for k, g in gradient.items()})

    # best 후보를 정밀 격자로 재평가·재판정 (저해상 편향으로 feasibility가 뒤집힐 수 있음.
    # clamp 없음 — 실제 candidate 그대로 보고, 이슈 #13 4.1.E)
    def _precise(entry):
        if entry is None:
            return None
        z_e = entry[0]
        pv = to_p(z_e)
        ev = evaluate_candidate(nl, pv, corner, force, ground, i_spec, cap_lim,
                                windows=win, alphas=alphas,
                                warm={}, calib_cache={}, n=M.N)
        _tick(w_final)
        return {"pset": pv, "losses": ev["losses"], "feasible": ev["feasible"],
                "constraints": ev["constraints"], "solver": ev["solver"],
                "usages": ev["usages"], "detail": ev["detail"],
                # legacy 표시 호환 필드
                "worst": max([u for u in ev["usages"].values()] or [0.0]),
                "worst_name": max(ev["usages"], key=lambda k: ev["usages"][k])
                if ev["usages"] else None,
                "cap_u": ev["usages"].get("cap(IO)", 0.0),
                "soa_pass": ev["feasible"],
                "loss": ev["losses"]["total"],
                **{k: pv[k] for k in keys}}
    fin_feas = _precise(best_feasible)
    fin_infeas = _precise(best_infeasible)
    if fin_feas is not None and not fin_feas["feasible"]:
        fin_infeas = fin_infeas if fin_infeas is not None else fin_feas
        fin_feas = None  # 정밀 재판정에서 뒤집힘 — PASS로 보고하지 않는다
    if fin_feas is None and fin_infeas is None:
        status = "SOLVER_ERROR"
    else:
        status = "PASS" if fin_feas is not None else "INFEASIBLE"
    final = fin_feas if fin_feas is not None else fin_infeas
    return {"status": status, "feasible": fin_feas is not None,
            "best_feasible": fin_feas, "best_infeasible": fin_infeas,
            "stopped_on_feasible": stopped_feasible,
            "history": history,
            # legacy 프론트 호환 (전환기 유지 — 이슈 #13 4.4)
            "initial": history[0] if history else None,
            "final": final,
            "best_it": max(range(len(history)),
                           key=lambda i: (history[i]["feasible"], -history[i]["J_obj"]))
            if history else 0,
            "variables": [{"key": v["key"], "name": v["name"], "lo": v["lo"],
                           "hi": v["hi"], "unit": v["unit"], "dec": v["dec"],
                           "kind": v["kind"], "frozen": v["frozen"],
                           "lockable": v["lockable"]} for v in var_spec],
            "pset": p0, "alphas": {"rule": alphas[0], "soa": alphas[1], "spec": alphas[2]},
            "barrier": barrier, "mu_bar": mu_bar, "grad": grad,
            "i_spec": i_spec, "hbm_kv": hbm_kv, "cap_lim": cap_lim,
            "force": force, "ground": ground, "corner": corner, "iters": iters}
