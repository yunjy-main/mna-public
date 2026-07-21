# -*- coding: utf-8 -*-
"""Victim SOA model — canonical data and evaluator from docs/victim_soa_model.html.

Structure (per the doc):
  A. Stack terminal SOA: Uterm = |VDS_stack| / Vfail(device_class, topology)
  B. Gate oxide SOA (signed, per-FET):
       NFET: Uinv = max(VGS,VGD,VGB,0)/Vinv ; Uacc = max(-VGS,-VGD,-VGB,0)/Vacc
       PFET: Uinv = max(-VGS,-VGD,-VGB,0)/Vinv ; Uacc = max(VGS,VGD,VGB,0)/Vacc
  Uoverall = max(Uterm, Uinv, Uacc)

User selection (2026-07-21): inverter victim uses SG_NFET + SG_PFET, 1stk_1rx.
"""

TERMINAL_VFAIL = {
    "SG_NFET": {"1stk_1rx": 3.1, "2stk_2rx": 5.7, "2stk_1rx": 5.8},
    "SG_PFET": {"1stk_1rx": 3.3, "2stk_2rx": 5.2, "2stk_1rx": 5.4},
    "EGU_NFET": {"1stk_1rx": 5.3, "2stk_2rx": 6.2, "2stk_1rx": 5.9},
    "EGU_PFET": {"1stk_1rx": 5.1, "2stk_2rx": 7.0, "2stk_1rx": 7.1},
}

OXIDE_LIMIT = {
    "SG_NFET": {"type": "nfet", "inversion": 2.9, "accumulation": 3.3},
    "SG_PFET": {"type": "pfet", "inversion": 3.3, "accumulation": 3.8},
    "EGU_NFET": {"type": "nfet", "inversion": 6.8, "accumulation": 8.2},
    "EGU_PFET": {"type": "pfet", "inversion": 9.1, "accumulation": 8.4},
}

TOPOLOGIES = ("1stk_1rx", "2stk_2rx", "2stk_1rx")


def eval_fet(dev_class, topology, vds_stack, vg, vs, vd, vb):
    """Doc evaluator for one FET: returns dict of utilizations (u < 1 = PASS)."""
    term_limit = TERMINAL_VFAIL[dev_class][topology]
    ox = OXIDE_LIMIT[dev_class]
    vgs, vgd, vgb = vg - vs, vg - vd, vg - vb
    u_term = abs(vds_stack) / term_limit
    if ox["type"] == "nfet":
        inv = max(vgs, vgd, vgb, 0.0)
        acc = max(-vgs, -vgd, -vgb, 0.0)
    else:
        inv = max(-vgs, -vgd, -vgb, 0.0)
        acc = max(vgs, vgd, vgb, 0.0)
    u_inv = inv / ox["inversion"]
    u_acc = acc / ox["accumulation"]
    return {"u_term": u_term, "u_inv": u_inv, "u_acc": u_acc,
            "u": max(u_term, u_inv, u_acc), "term_limit": term_limit}


def inverter_victim(v_out, vdd_local, vg=0.0,
                    nmos="SG_NFET", pmos="SG_PFET", topology="1stk_1rx"):
    """Apply the victim SOA to the inverter (common drain OUT, IO -Resd-> OUT).

    ESD condition (unpowered): shared input gate at vg (default 0 = VSS),
    NMOS S=B=VSS(0), PMOS S=B=VDD_local. Terminal stress: NMOS VDS = V_OUT,
    PMOS VDS = V_OUT - VDD_local.
    """
    n = eval_fet(nmos, topology, v_out, vg, 0.0, v_out, 0.0)
    p = eval_fet(pmos, topology, v_out - vdd_local, vg, vdd_local, v_out, vdd_local)
    checks = [
        ("NMOS terminal", n["u_term"]), ("NMOS ox inv", n["u_inv"]), ("NMOS ox acc", n["u_acc"]),
        ("PMOS terminal", p["u_term"]), ("PMOS ox inv", p["u_inv"]), ("PMOS ox acc", p["u_acc"]),
    ]
    worst = max(checks, key=lambda c: c[1])
    return {
        "u": worst[1], "worst": worst[0],
        "uN": n["u"], "uP": p["u"],
        "uN_term": n["u_term"], "uN_ox": max(n["u_inv"], n["u_acc"]),
        "uP_term": p["u_term"], "uP_ox": max(p["u_inv"], p["u_acc"]),
        "limN_term": n["term_limit"], "limP_term": p["term_limit"],
    }
