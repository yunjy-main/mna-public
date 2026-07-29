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

gradient 기본 = adjoint(±케이스당 전치 선형해 1회, central FD oracle 대조 검증);
grad="fd"는 검증 oracle 겸 보존 옵션 (#14 §10.2). candidate 상태 3분법
(VALID|SOLVER_ERROR|MONITOR_ERROR)·rollback/retry·feasible_policy는 이슈 #14.
변수명 주의: L은 metal length — loss는 loss_*/J_obj로만 표기 (이슈 #13 원칙).
"""
import math

from server import model as M
from server.netlist import (extract_netlist, assemble_and_solve, measured_context,
                            soa_endpoints, device_voltages, device_keys,
                            evaluate_soa_monitors, direct_io_cap, params_registry,
                            solve_linear, residual_param_derivatives,
                            _pset, _clamp_iv, _diode_iv)

# victim stress quantity → (양(+) 단자, 음(−) 단자) — ∂q/∂v 계수 조립용
_VICTIM_TERMS = {"VGS": ("g", "s"), "VGD": ("g", "d"), "VDS": ("d", "s"),
                 "VGB": ("g", "b")}

FEAS_N = 500        # FD 탐색용 저해상 calib 격자 (best 후보는 정밀 N 재평가로 재판정)
FD_H = 2e-3         # 정규화 좌표 forward 차분 스텝
ALLOWED_VARS = ("x1", "x2", "W", "L")  # 이슈 #13: 자유도는 이 넷만 명시 사용


def _phi(g):
    """squared hinge — PASS(g≤0) 항목은 값·gradient 모두 0."""
    return 0.5 * g * g if g > 0.0 else 0.0


def evaluate_candidate(nl, pset, corner, force, ground, i_spec, cap_lim,
                       windows=None, alphas=(1.0, 1.0, 1.0),
                       warm=None, calib_cache=None, n=FEAS_N, keep_aux=False):
    """candidate pset의 constraint 전수 평가 (이슈 #13 4.1.A 스키마).

    반환: {solver, constraints{rule,soa,spec}, losses{rule,soa,spec,total},
           feasible, detail(legacy 표시 호환), usages(legacy 키 호환)[, aux]}.
    비수렴 케이스는 SOA usage에 섞지 않고 solver status로만 기록 → feasible=False.
    keep_aux=True면 adjoint 조립용 부가정보(해 객체·record별 node/g_d/한계) 포함."""
    ctx = measured_context(corner=corner, n=n, cache=calib_cache, pset=pset)
    eps = soa_endpoints(nl, corner=corner, pset=pset)
    kd = dict(device_keys(nl))
    warm = warm if warm is not None else {}
    cons = {"rule": [], "soa": [], "spec": []}
    solver = {}
    detail = {}
    aux = {"sols": {}}

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
        if keep_aux:
            aux["sols"][tag] = sol
        names = nl["nets"]
        dv = device_voltages(nl, sol)
        for key, e in eps.items():
            if not e:
                continue
            d = kd[key]
            V = dv[key]
            meas = ctx(d)
            if meas is not None:
                I, g_d = meas(V)
            elif d["kind"] == "zener":
                I, g_d = _clamp_iv(V)
            else:
                I, g_d = _diode_iv(V)
            uV = V / e["vp"] if V >= 0 else V / e["vn"]
            uI = I / e["ip"] if I >= 0 else I / e["inn"]
            nodes = (names[d["a"]], names[d["b"]])
            rv = {"key": "{}·V{}".format(key, tag), "category": "soa",
                  "stress_case": tag, "device": key, "quantity": "V",
                  "value": V, "limit_min": e["vn"], "limit_max": e["vp"],
                  "usage": uV, "g": uV - 1.0, "passed": uV <= 1.0}
            ri = {"key": "{}·I{}".format(key, tag), "category": "soa",
                  "stress_case": tag, "device": key, "quantity": "I",
                  "value": I, "limit_min": e["inn"], "limit_max": e["ip"],
                  "usage": uI, "g": uI - 1.0, "passed": uI <= 1.0}
            if keep_aux:
                rv["_aux"] = {"kind": "V", "nodes": nodes, "dev_key": key,
                              "limit_active": e["vp"] if V >= 0 else e["vn"], "V": V}
                ri["_aux"] = {"kind": "I", "nodes": nodes, "dev_key": key, "g_d": g_d,
                              "limit_active": e["ip"] if I >= 0 else e["inn"], "V": V}
            cons["soa"].append(rv)
            cons["soa"].append(ri)
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
            tnet = {t: info["net"] for t, info in m["terminals"].items()}
            for c in m["checks"]:
                val = c["value"]
                u = val / c["max"] if val >= 0 else val / c["min"]
                rec = {"key": "{}·{}{}".format(m["instance"], c["quantity"], tag),
                       "category": "soa", "stress_case": tag,
                       "device": m["instance"], "quantity": c["quantity"],
                       "value": val, "limit_min": c["min"], "limit_max": c["max"],
                       "usage": u, "g": u - 1.0, "passed": u <= 1.0}
                if keep_aux and c["quantity"] in _VICTIM_TERMS:
                    hi_t, lo_t = _VICTIM_TERMS[c["quantity"]]
                    rec["_aux"] = {"kind": "victim",
                                   "nodes": (tnet[hi_t], tnet[lo_t]), "dev_key": None,
                                   "limit_active": c["max"] if val >= 0 else c["min"]}
                cons["soa"].append(rec)
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
    losses["constraint_total"] = losses["total"]  # 명시 이름 (#14 §6.2 — total은 별칭)
    all_cons = cons["rule"] + cons["soa"] + cons["spec"]
    # candidate 상태 3분법 (이슈 #14 §2.2) — 비수렴 candidate의 J=0을 정상
    # infeasible로 오인하지 않도록 feasibility와 평가 유효성을 분리한다.
    solver_valid = all(s["converged"] for s in solver.values())
    constraints_valid = not any("monitor_invalid" in s for s in solver.values())
    if not solver_valid:
        candidate_status = "SOLVER_ERROR"
    elif not constraints_valid:
        candidate_status = "MONITOR_ERROR"
    else:
        candidate_status = "VALID"
    # category별 PASS 분리 (#14 §7) — soa_pass가 rule/spec FAIL을 흡수하지 않도록
    pass_cat = {"rule": all(c["passed"] for c in cons["rule"]),
                "soa": all(c["passed"] for c in cons["soa"]),
                "spec": all(c["passed"] for c in cons["spec"])}
    pass_cat["all"] = (candidate_status == "VALID" and pass_cat["rule"]
                       and pass_cat["soa"] and pass_cat["spec"])
    feasible = pass_cat["all"]
    usages = {c["key"]: c["usage"] for c in all_cons if c["usage"] is not None}
    out = {"solver": solver, "constraints": cons, "losses": losses,
           "candidate_status": candidate_status, "solver_valid": solver_valid,
           "constraints_valid": constraints_valid, "pass": pass_cat,
           "feasible": feasible, "detail": detail, "usages": usages}
    if keep_aux:
        out["aux"] = aux
    return out


def adjoint_gradient(nl, pset, ev, param_keys, windows, alphas, cap_lim,
                     corner="worst", n=FEAS_N, cache=None):
    """dJ_hat/dp (barrier 제외) — 직접 경로 + stress case별 adjoint (이슈 #12 §5·§6).

      J_sᵀψ_s = ∂J_obj/∂v_s  (케이스당 1회 전치 선형해)
      dJ/dp = ∂J/∂p − Σ_s ψ_sᵀ·∂F_s/∂p

    직접 경로: rule hinge(해석), cap(스칼라 FD), SOA limit의 size 의존(−q·dlim/lim²)
    과 고정 V에서의 전류 size 의존(dI/dp|V / lim). MNA 경유는 residual stamp.
    hinge 특성상 PASS(g≤0) 항목은 기여 0 — evaluate_candidate(keep_aux=True) 결과 필요."""
    a_rule, a_soa, a_spec = alphas
    grad = {p: 0.0 for p in param_keys}
    hs = {p: 1e-4 * max(1.0, abs(pset.get(p, 1.0))) for p in param_keys}

    # ── 직접: rule hinge (해석)
    for name, (lo, hi) in (windows or {}).items():
        if name not in grad:
            continue
        v, span = pset[name], (hi - lo) or 1.0
        g_min, g_max = (lo - v) / span, (v - hi) / span
        if g_min > 0:
            grad[name] += a_rule * g_min * (-1.0 / span)
        if g_max > 0:
            grad[name] += a_rule * g_max * (1.0 / span)

    # ── 직접: spec (0V cap — ESD 해 무관, 스칼라 중심차분)
    for c in ev["constraints"]["spec"]:
        if c["g"] <= 0:
            continue
        for p in param_keys:
            pp, pm = dict(pset), dict(pset)
            pp[p] += hs[p]
            pm[p] -= hs[p]
            dC = (direct_io_cap(nl, pset=pp) - direct_io_cap(nl, pset=pm)) / (2 * hs[p])
            grad[p] += a_spec * c["g"] * dC / cap_lim

    # ── SOA: 위반 항목만 (hinge) — 필요한 섭동 컨텍스트 준비
    act = [c for c in ev["constraints"]["soa"] if c["g"] > 0 and "_aux" in c]
    if act:
        kd = dict(device_keys(nl))
        eps_pm, ctx_pm = {}, {}
        for p in param_keys:
            pp, pm = dict(pset), dict(pset)
            pp[p] += hs[p]
            pm[p] -= hs[p]
            eps_pm[p] = (soa_endpoints(nl, corner=corner, pset=pp),
                         soa_endpoints(nl, corner=corner, pset=pm))
            ctx_pm[p] = (measured_context(corner=corner, n=n, cache=cache, pset=pp),
                         measured_context(corner=corner, n=n, cache=cache, pset=pm))
        _branch = {"V": lambda e, val: e["vp"] if val >= 0 else e["vn"],
                   "I": lambda e, val: e["ip"] if val >= 0 else e["inn"]}
        for c in act:
            ax = c["_aux"]
            w = a_soa * c["g"]  # dφ/du = g (g>0)
            lim = ax["limit_active"]
            if ax["kind"] == "victim":
                continue  # victim limit은 상수·전류항 없음 — 직접 경로 기여 0
            q = c["value"]
            for p in param_keys:
                ep, em = eps_pm[p][0].get(ax["dev_key"]), eps_pm[p][1].get(ax["dev_key"])
                dlim = ((_branch[ax["kind"]](ep, q) - _branch[ax["kind"]](em, q))
                        / (2 * hs[p])) if (ep and em) else 0.0
                term = -q * dlim / (lim * lim)
                if ax["kind"] == "I":
                    d = kd[ax["dev_key"]]
                    fp_, fm_ = ctx_pm[p][0](d), ctx_pm[p][1](d)
                    if fp_ is not None and fm_ is not None:
                        term += ((fp_(ax["V"])[0] - fm_(ax["V"])[0]) / (2 * hs[p])) / lim
                grad[p] += w * term

    # ── MNA 경유: 케이스별 adjoint solve + residual stamp
    for tag in ("+", "-"):
        sol = ev.get("aux", {}).get("sols", {}).get(tag)
        if sol is None:
            continue
        pos = {nm: i for i, nm in enumerate(sol["unknowns"])}
        rhs = [0.0] * len(pos)
        for c in ev["constraints"]["soa"]:
            if c["stress_case"] != tag or c["g"] <= 0 or "_aux" not in c:
                continue
            ax = c["_aux"]
            w = a_soa * c["g"]
            coef = (ax["g_d"] if ax["kind"] == "I" else 1.0) / ax["limit_active"]
            na, nb = ax["nodes"]
            if na in pos:
                rhs[pos[na]] += w * coef
            if nb in pos:
                rhs[pos[nb]] -= w * coef
        if not any(rhs):
            continue
        jt = [list(col) for col in zip(*sol["jacobian"])]
        psi = solve_linear(jt, rhs)
        dF = residual_param_derivatives(nl, sol, pset, corner=corner, n=n, cache=cache,
                                        params=tuple(param_keys))
        for p in param_keys:
            grad[p] -= sum(ps * df for ps, df in zip(psi, dF[p]))
    return grad


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
                  lr=0.06, iters=30, n=FEAS_N, grad="adjoint",
                  freeze=(), pset=None, stop_on_feasible=False,
                  feasible_policy="max_margin", progress_cb=None):
    """Feasibility optimizer 본체 (이슈 #13 §3·§4.1) — Adam + adjoint gradient(기본).

    grad: adjoint(기본 — ± 케이스당 전치 선형해 1회로 전 변수 gradient)
          | fd(forward 유한차분 — S5 대조 oracle 겸 보존 옵션).
    barrier: off(기본 — hinge만, 경계 통과 허용) | log | softplus (preference 옵션).
    stop_on_feasible: 기본 False(사용자 확정) — iters 완주하며 best_feasible 갱신
    (margin 최대 기준). final clamp 없음 — 실제 candidate의 feasibility를 보고."""
    if barrier not in ("off", "log", "softplus"):
        raise ValueError("barrier must be off|log|softplus")
    if grad not in ("adjoint", "fd"):
        raise ValueError("grad must be adjoint|fd")
    # feasible 간 selection policy 명시 (#14 §5, 기본 max_margin=완주 — 사용자 확정).
    # stop_on_feasible(구 옵션)은 first의 별칭으로 통합.
    if stop_on_feasible:
        feasible_policy = "first"
    if feasible_policy not in ("max_margin", "first", "min_residual"):
        raise ValueError("feasible_policy must be max_margin|first|min_residual")
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
    per_it = 2 if grad == "adjoint" else (len(active) + 2)
    prog = {"done": 0, "total": 1 + iters * per_it + 2 * w_final}

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

    def evaluate(z, n_eval=n, keep_aux=False):
        pv = to_p(z)
        ev = evaluate_candidate(nl, pv, corner, force, ground, i_spec, cap_lim,
                                windows=win, alphas=alphas, keep_aux=keep_aux,
                                warm=warm, calib_cache=ccache, n=n_eval)
        _tick()
        return ev["losses"]["total"] + barrier_term(pv), ev

    def barrier_grad(pv):
        """barrier preference 항의 해석 gradient (활성 변수 자신에만)."""
        gb = {var_spec[i]["key"]: 0.0 for i in active}
        if barrier == "off":
            return gb
        for i in active:
            v = var_spec[i]
            valv, span = pv[v["key"]], v["hi"] - v["lo"]
            if barrier == "log":
                u = (v["hi"] - valv) / span
                gb[v["key"]] += mu_bar * (1.0 / (v["hi"] - valv) if u > 1e-3
                                          else 1.0 / (1e-3 * span))
                uo = (valv - v["hi"]) / span
                if uo > 0:
                    gb[v["key"]] += mu_rule * 1000.0 * uo / span  # _wallq k=500
            else:
                t = (valv - v["hi"]) / (0.05 * span)
                sig = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, t))))
                gb[v["key"]] += mu_rule * sig / (0.05 * span)
        return gb

    z = [0.0] * len(var_spec)
    for i, v in enumerate(var_spec):
        if v["lo"] is not None:
            z[i] = min(1.2, max(-0.2, (p0[v["key"]] - v["lo"]) / (v["hi"] - v["lo"])))
    # candidate 통일 스키마 (이슈 #14 4.2): {"it","z","ev","score"} — 상태별 3분리(§2.3)
    best_feasible = None
    best_infeasible = None
    best_solver_error = None
    history = []
    mom, vel = [0.0] * len(var_spec), [0.0] * len(var_spec)
    b1, b2, eps_ = 0.9, 0.999, 1e-9
    MAX_SOLVER_RETRIES = 4  # 비수렴 trial rollback·절반 step 재시도 횟수 (#14 §2.4)

    def _record(it, jv, ev, z_now, gradient):
        pv = to_p(z_now)
        worst_c = max((ev["constraints"]["soa"] + ev["constraints"]["spec"]) or [],
                      key=lambda c: (c["usage"] if c["usage"] is not None else -1e9),
                      default=None)
        bt = jv - ev["losses"]["constraint_total"]  # barrier 항 (#14 §6 — 표시=실사용)
        losses_row = {k: round(x, 6) for k, x in ev["losses"].items()}
        losses_row["barrier"] = round(bt, 6)
        losses_row["objective"] = round(jv, 6)
        row = {"it": it, "J_obj": jv, "loss": jv,  # loss=legacy 호환 별칭
               "losses": losses_row,
               "feasible": ev["feasible"], "soa_pass": ev["pass"]["soa"],
               "pass": ev["pass"],  # category별 (#14 §7)
               "candidate_status": ev["candidate_status"],
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

    def _round_gd(gd):
        return {sec: {k: round(v, 6) for k, v in m.items()} for sec, m in gd.items()}

    def _consider(it_now, z_now, ev):
        nonlocal best_feasible, best_infeasible, best_solver_error
        if ev["candidate_status"] != "VALID":
            # solver/monitor error는 physical infeasible과 분리 저장 (#14 §2.3)
            sc = (0 if ev["solver_valid"] else 1,
                  max((s["residual"] for s in ev["solver"].values()),
                      default=float("inf")))
            if best_solver_error is None or sc < best_solver_error["score"]:
                best_solver_error = {"it": it_now, "z": list(z_now), "ev": ev, "score": sc}
            return
        if ev["feasible"]:
            # feasible 간 우열 = 명시 policy (#14 §5): first는 최초 보존,
            # max_margin은 max usage 최소(정밀 재판정 뒤집힘 위험 최소),
            # min_residual은 solver residual 최소
            if feasible_policy == "first":
                if best_feasible is None:
                    best_feasible = {"it": it_now, "z": list(z_now), "ev": ev,
                                     "score": (it_now,)}
                return
            if feasible_policy == "min_residual":
                sc = (max(s["residual"] for s in ev["solver"].values()),)
            else:
                sc = (max([u for u in ev["usages"].values()] or [0.0]),
                      max(s["residual"] for s in ev["solver"].values()))
            if best_feasible is None or sc < best_feasible["score"]:
                best_feasible = {"it": it_now, "z": list(z_now), "ev": ev, "score": sc}
        else:
            sc = _violation_score(ev)
            if best_infeasible is None or sc < best_infeasible["score"]:
                best_infeasible = {"it": it_now, "z": list(z_now), "ev": ev, "score": sc}

    j0, ev0 = evaluate(z)
    _consider(0, z, ev0)
    _record(0, j0, ev0, z, None)
    stopped_feasible = False
    solver_terminated = ev0["candidate_status"] != "VALID"  # 초기부터 무효 → 진행 불가
    it = 0
    while not solver_terminated and it < iters:
        it += 1
        if feasible_policy == "first" and best_feasible is not None:
            stopped_feasible = True  # first policy = 자동 조기 종료 (#14 §5.2)
            break
        # gradient 기준점 — 수락 로직이 z를 항상 VALID로 유지 (warm-start 변화 대비 방어)
        if grad == "adjoint":
            f_base, ev_base = evaluate(z, keep_aux=True)
            _consider(it - 1, z, ev_base)
            if ev_base["candidate_status"] != "VALID":
                solver_terminated = True
                break
            pv = to_p(z)
            act_keys = tuple(var_spec[i]["key"] for i in active)
            spans = {var_spec[i]["key"]: var_spec[i]["hi"] - var_spec[i]["lo"]
                     for i in active}
            ga = adjoint_gradient(nl, pv, ev_base, act_keys, win, alphas, cap_lim,
                                  corner=corner, n=n, cache=ccache)
            gb = barrier_grad(pv)
            # Adam은 정규화 좌표(z)에서 동작 — 물리 gradient × span으로 좌표 일치.
            # constraint/barrier 분리 기록 (#14 §6.3)
            g_con = {k: ga[k] * spans[k] for k in act_keys}
            g_bar = {k: gb[k] * spans[k] for k in act_keys}
            gradient = {k: g_con[k] + g_bar[k] for k in act_keys}
            gradient_detail = {"constraint": g_con, "barrier": g_bar, "total": gradient}
        else:
            f_base, ev_base = evaluate(z)
            _consider(it - 1, z, ev_base)
            if ev_base["candidate_status"] != "VALID":
                solver_terminated = True
                break
            gradient = {}
            for i in active:
                zp = list(z)
                zp[i] += FD_H
                fp, ev_p = evaluate(zp)
                gradient[var_spec[i]["key"]] = (
                    0.0 if ev_p["candidate_status"] != "VALID"
                    else (fp - f_base) / FD_H)  # 무효 probe는 기여 제외
            gradient_detail = {"total": dict(gradient)}
        # Adam 제안 (미커밋 — #14 §2.4: 비수렴 trial에는 상태를 갱신하지 않는다)
        prop = {}
        for i in active:
            gi = gradient[var_spec[i]["key"]]
            m2 = b1 * mom[i] + (1 - b1) * gi
            v2 = b2 * vel[i] + (1 - b2) * gi * gi
            mh = m2 / (1 - b1 ** it)
            vh = v2 / (1 - b2 ** it)
            prop[i] = (m2, v2, lr * mh / (math.sqrt(vh) + eps_))
        accepted, scale = False, 1.0
        j_new, ev_new, z_trial = None, None, list(z)
        for _retry in range(MAX_SOLVER_RETRIES):
            z_trial = list(z)
            for i in active:
                z_trial[i] = min(1.2, max(-0.2, z[i] - scale * prop[i][2]))
            j_new, ev_new = evaluate(z_trial)
            _consider(it, z_trial, ev_new)
            if ev_new["candidate_status"] == "VALID":
                for i in active:  # 수락 시에만 Adam 상태 커밋
                    mom[i], vel[i] = prop[i][0], prop[i][1]
                z = z_trial
                _record(it, j_new, ev_new, z, _round_gd(gradient_detail))
                accepted = True
                break
            scale *= 0.5  # rollback + 절반 step 재시도
        if not accepted:  # 재시도 소진 — solver error로 기록하고 종료 (#14 §2.4)
            _record(it, j_new, ev_new, z_trial, _round_gd(gradient_detail))
            solver_terminated = True

    # best 후보를 정밀 격자로 재평가·재판정 (저해상 편향으로 feasibility가 뒤집힐 수 있음.
    # clamp 없음 — 실제 candidate 그대로 보고, 이슈 #13 4.1.E)
    def _precise(entry):
        if entry is None:
            return None
        pv = to_p(entry["z"])
        ev = evaluate_candidate(nl, pv, corner, force, ground, i_spec, cap_lim,
                                windows=win, alphas=alphas,
                                warm={}, calib_cache={}, n=M.N)
        _tick(w_final)
        bt = barrier_term(pv)
        losses_p = dict(ev["losses"])
        losses_p["barrier"] = bt
        losses_p["objective"] = losses_p["constraint_total"] + bt  # 표시=실사용 (#14 §6)
        return {"pset": pv, "losses": losses_p, "feasible": ev["feasible"],
                "candidate_status": ev["candidate_status"],
                "source_it": entry["it"],  # UI ★best·slider·[적용] 일치 (#14 §4.2)
                "constraints": ev["constraints"], "solver": ev["solver"],
                "usages": ev["usages"], "detail": ev["detail"],
                "pass": ev["pass"],  # category별 (#14 §7)
                # legacy 표시 호환 필드 — soa_pass는 실제 SOA만 의미 (#14 §7.2)
                "worst": max([u for u in ev["usages"].values()] or [0.0]),
                "worst_name": max(ev["usages"], key=lambda k: ev["usages"][k])
                if ev["usages"] else None,
                "cap_u": ev["usages"].get("cap(IO)", 0.0),
                "soa_pass": ev["pass"]["soa"],
                "loss": ev["losses"]["total"],
                **{k: pv[k] for k in keys}}
    valid_seen = (best_feasible is not None) or (best_infeasible is not None)
    fin_feas = _precise(best_feasible)
    fin_infeas = _precise(best_infeasible)
    if fin_feas is not None and not fin_feas["feasible"]:
        fin_infeas = fin_infeas if fin_infeas is not None else fin_feas
        fin_feas = None  # 정밀 재판정에서 뒤집힘 — PASS로 보고하지 않는다
    if not valid_seen:
        status = "SOLVER_ERROR"  # VALID candidate가 한 번도 없음 (#14 §2.3)
    elif fin_feas is not None:
        status = "PASS"
    else:
        status = "INFEASIBLE"
    final = fin_feas if fin_feas is not None else fin_infeas
    return {"status": status, "feasible": fin_feas is not None,
            "best_feasible": fin_feas, "best_infeasible": fin_infeas,
            "best_solver_error": ({"it": best_solver_error["it"],
                                   "pset": to_p(best_solver_error["z"]),
                                   "solver": best_solver_error["ev"]["solver"],
                                   "candidate_status":
                                       best_solver_error["ev"]["candidate_status"]}
                                  if best_solver_error is not None else None),
            "solver_terminated": solver_terminated,
            "stopped_on_feasible": stopped_feasible,
            # selection policy 명시 (#14 §5.3)
            "feasible_policy": feasible_policy,
            "secondary_objective_used": (feasible_policy != "first"
                                         and best_feasible is not None),
            "secondary_score": (best_feasible["score"][0]
                                if (feasible_policy != "first"
                                    and best_feasible is not None) else None),
            "history": history,
            # legacy 프론트 호환 (전환기 유지 — 이슈 #13 4.4)
            "initial": history[0] if history else None,
            "final": final,
            "best_it": (final["source_it"] if final is not None
                        else (len(history) - 1 if history else 0)),
            "variables": [{"key": v["key"], "name": v["name"], "lo": v["lo"],
                           "hi": v["hi"], "unit": v["unit"], "dec": v["dec"],
                           "kind": v["kind"], "frozen": v["frozen"],
                           "lockable": v["lockable"]} for v in var_spec],
            "pset": p0, "alphas": {"rule": alphas[0], "soa": alphas[1], "spec": alphas[2]},
            "barrier": barrier, "mu_bar": mu_bar, "grad": grad,
            "i_spec": i_spec, "hbm_kv": hbm_kv, "cap_lim": cap_lim,
            "force": force, "ground": ground, "corner": corner, "iters": iters}
