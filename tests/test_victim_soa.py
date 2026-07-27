# -*- coding: utf-8 -*-
"""Victim SOA evaluator checks vs docs/victim_soa_model.html.

Reproduces the doc's interactive evaluator on hand cases and validates the
inverter mapping (SG NFET + SG PFET, 1stk_1rx — user selection).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.victim_soa import TERMINAL_VFAIL, OXIDE_LIMIT, eval_fet, inverter_victim  # noqa: E402

fails = []


def chk(name, got, want, tol=1e-12):
    if abs(got - want) > tol:
        fails.append("{}: got {!r}, want {!r}".format(name, got, want))


# canonical data spot checks (doc section 5)
chk("data/sgn_1stk", TERMINAL_VFAIL["SG_NFET"]["1stk_1rx"], 3.1)
chk("data/sgp_1stk", TERMINAL_VFAIL["SG_PFET"]["1stk_1rx"], 3.3)
chk("data/sgn_inv", OXIDE_LIMIT["SG_NFET"]["inversion"], 2.9)
chk("data/sgp_acc", OXIDE_LIMIT["SG_PFET"]["accumulation"], 3.8)

# doc default evaluator case: SG_NFET 1stk_1rx, vds=2.5, VG=1, VS=VD=VB=0
r = eval_fet("SG_NFET", "1stk_1rx", 2.5, 1.0, 0.0, 0.0, 0.0)
chk("doc/uterm", r["u_term"], 2.5 / 3.1)
chk("doc/uinv", r["u_inv"], 1.0 / 2.9)   # VGS=VGD=VGB=+1 -> inversion
chk("doc/uacc", r["u_acc"], 0.0)
chk("doc/u", r["u"], 2.5 / 3.1)

# PFET signed logic: SG_PFET, VG=-4 vs S=D=B=0 -> inversion stress 4/3.3 (FAIL)
r = eval_fet("SG_PFET", "1stk_1rx", 0.0, -4.0, 0.0, 0.0, 0.0)
chk("pfet/inv", r["u_inv"], 4.0 / 3.3)
chk("pfet/acc", r["u_acc"], 0.0)
if r["u"] < 1.0:
    fails.append("pfet/-4V gate should FAIL")

# inverter mapping (positive stress example: V_OUT=2.02, VDD_local=1.29, VG=0)
s = inverter_victim(2.02, 1.29, 0.0)
chk("inv/uN_term", s["uN_term"], 2.02 / 3.1)          # NMOS VDS = V_OUT
chk("inv/uP_term", s["uP_term"], (2.02 - 1.29) / 3.3)  # PMOS VDS = V_OUT - VDD
# NMOS oxide: VGS=0, VGD=-2.02, VGB=0 -> acc stress 2.02/3.3
chk("inv/uN_ox", s["uN_ox"], 2.02 / 3.3)
# PMOS oxide (G=0,S=B=1.29,D=2.02): inversion max(1.29,2.02,1.29)/3.3
chk("inv/uP_ox", s["uP_ox"], 2.02 / 3.3)
chk("inv/u", s["u"], 2.02 / 3.1)
if s["worst"] != "NMOS terminal":
    fails.append("inv/worst: got {}".format(s["worst"]))

# topology lookup effect: 2stk_2rx relaxes NMOS terminal 3.1 -> 5.7
s2 = inverter_victim(2.02, 1.29, 0.0, topology="2stk_2rx")
chk("inv/2stk_uN_term", s2["uN_term"], 2.02 / 5.7)

# diode-connected gate (사용자 지시: gate = OUT): VG = V_OUT
sd = inverter_victim(2.02, 1.29, 2.02)
# NFET: VGS=2.02, VGD=0, VGB=2.02 -> inversion 2.02/2.9 (터미널 2.02/3.1보다 큼 -> 지배)
chk("dc/uN_ox", sd["uN_ox"], 2.02 / 2.9)
chk("dc/u", sd["u"], 2.02 / 2.9)
if sd["worst"] != "NMOS ox inv":
    fails.append("dc/worst: got {}".format(sd["worst"]))
# PFET(G=2.02, S=B=1.29, D=2.02): acc = max(0.73, 0, 0.73)/3.8
chk("dc/uP_ox", sd["uP_ox"], 0.73 / 3.8)

if fails:
    for m in fails:
        print("FAIL " + m)
    sys.exit(1)
print("PASS: victim SOA evaluator (canonical data, doc case, signed oxide, inverter mapping)")
