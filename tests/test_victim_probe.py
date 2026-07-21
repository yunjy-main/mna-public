# -*- coding: utf-8 -*-
"""Victim inverter probe checks (IO -Resd-> OUT, PMOS drain junction to VDD).

Closed-form: junction on  ->  V_OUT = (Rj*V_IO + Resd*(Vdd+Von)) / (Rj+Resd),
I_v = (V_IO - V_OUT)/Resd. Off when V_IO <= Vdd + Von.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.model import victim_probe  # noqa: E402

fails = []


def chk(name, got, want, tol=1e-12):
    if abs(got - want) > tol:
        fails.append("{}: got {!r}, want {!r}".format(name, got, want))


# off: V_IO below Vdd_local + Von -> no conduction, OUT follows IO exactly
v, i = victim_probe(2.0, 1.5, 500.0, 0.7, 10.0)
chk("off/vout", v, 2.0)
chk("off/iv", i, 0.0)

# on: hand-computed example (V_IO=3.85, Vdd_local=1.29)
v, i = victim_probe(3.85, 1.29, 500.0, 0.7, 10.0)
chk("on/vout", v, (10 * 3.85 + 500 * 1.99) / 510.0)
chk("on/iv", i, (3.85 - (10 * 3.85 + 500 * 1.99) / 510.0) / 500.0)
# KCL consistency: current through Resd equals current through junction
chk("on/kcl", (3.85 - v) / 500.0, (v - 1.29 - 0.7) / 10.0, 1e-12)
# mitigation: drain stress must sit strictly between clamp-side and pad voltage
if not (1.99 < v < 3.85):
    fails.append("on/range: vout {} not in (1.99, 3.85)".format(v))

# continuity at turn-on threshold
v1, _ = victim_probe(2.19999999, 1.5, 500.0, 0.7, 10.0)
v2, _ = victim_probe(2.20000001, 1.5, 500.0, 0.7, 10.0)
chk("continuity", v1, v2, 1e-6)

# monotonicity in V_IO
prev = 0.0
for k in range(20):
    vio = 2.0 + 0.2 * k
    v, _ = victim_probe(vio, 1.5, 500.0, 0.7, 10.0)
    if v < prev:
        fails.append("monotone: vout decreased at vio={}".format(vio))
    prev = v

if fails:
    for m in fails:
        print("FAIL " + m)
    sys.exit(1)
print("PASS: victim inverter probe (closed-form, KCL, continuity, monotonicity)")
