# -*- coding: utf-8 -*-
"""Founding-conversation analytic benchmarks (from "HBM ESD 테스트 구조.html").

Two hand-verified toy problems from the founding dialogue, kept as regression
anchors for Phase 3 (gradient closure) and Phase 4 (MNA):

1. 3-node linear MNA example (lines 820~1084 of the founding doc)
   nodes V_P/V_U/V_C, I_HBM=1A, g_D=2S (Ron_up 0.5), g_R=5S (Rrail 0.2),
   g_C=1S (Ron_clamp 1.0), VON_D=0.7V, VON_C=1.5V.
   NOTE: deliberately different numbers from pad_to_vss_mna_backprop_demo.html
   (g_D=A/2, g_R=W, g_C=C/3) — do not mix the two golden sets.

2. A+C+W=10 multiple-solution toy (lines 1249~1458)
   V(A,C,W) = 2.2 + 2/A + 3/C + 1/W, SOA V <= 4.0, Cost = A+C+W.

Usage: python tests/founding_benchmarks.py   (exit 0 = PASS)
"""
import math
import sys

FAILS = []


def check(name, got, want, tol):
    ok = abs(got - want) <= tol
    if not ok:
        FAILS.append("{}: got {!r}, want {!r} (tol {})".format(name, got, want, tol))
    return ok


def solve3(A, b):
    """Tiny Gaussian elimination with partial pivoting (no numpy dependency)."""
    A = [row[:] for row in A]
    b = b[:]
    n = 3
    for k in range(n):
        p = max(range(k, n), key=lambda r: abs(A[r][k]))
        A[k], A[p] = A[p], A[k]
        b[k], b[p] = b[p], b[k]
        for r in range(k + 1, n):
            f = A[r][k] / A[k][k]
            for c in range(k, n):
                A[r][c] -= f * A[k][c]
            b[r] -= f * b[k]
    x = [0.0] * n
    for k in range(n - 1, -1, -1):
        x[k] = (b[k] - sum(A[k][c] * x[c] for c in range(k + 1, n))) / A[k][k]
    return x


# ---------- 1. 3-node linear MNA example ----------
I_HBM, gD, gR, gC, VON_D, VON_C = 1.0, 2.0, 5.0, 1.0, 0.7, 1.5
G = [[gD, -gD, 0.0],
     [-gD, gD + gR, -gR],
     [0.0, -gR, gR + gC]]
b = [I_HBM + gD * VON_D, -gD * VON_D, gC * VON_C]
V = solve3(G, b)
check("mna3/V_P", V[0], 3.9, 1e-12)
check("mna3/V_U", V[1], 2.7, 1e-12)
check("mna3/V_C", V[2], 2.5, 1e-12)
# closed-form series check: V_P = VON_D + I/gD + I/gR + VON_C + I/gC
check("mna3/closed_form", VON_D + 1 / gD + 1 / gR + VON_C + 1 / gC, V[0], 1e-12)
# hand-derived sensitivities dV_P/dg = -I/g^2 (founding golden: -0.25 / -0.04 / -1.0)
check("mna3/dVP_dgD", -I_HBM / gD ** 2, -0.25, 1e-12)
check("mna3/dVP_dgR", -I_HBM / gR ** 2, -0.04, 1e-12)
check("mna3/dVP_dgC", -I_HBM / gC ** 2, -1.0, 1e-12)
# finite-difference cross-check of the dominant sensitivity (clamp conductance)
h = 1e-7
VP = lambda gd, gr, gc: VON_D + 1 / gd + 1 / gr + VON_C + 1 / gc
check("mna3/fd_gC", (VP(gD, gR, gC + h) - VP(gD, gR, gC - h)) / (2 * h), -1.0, 1e-6)

# ---------- 2. A+C+W=10 multiple-solution toy ----------
VF = 4.0
Vt = lambda A, C, W: 2.2 + 2.0 / A + 3.0 / C + 1.0 / W
# three integer global optima at Cost=10
for (A, C, W), vexp in (((3, 4, 3), 3.95), ((3, 5, 2), 2.2 + 2 / 3 + 3 / 5 + 1 / 2), ((4, 4, 2), 3.95)):
    v = Vt(A, C, W)
    check("toy/V({},{},{})".format(A, C, W), v, vexp, 1e-12)
    if v > VF:
        FAILS.append("toy/({},{},{}) should PASS but V={}".format(A, C, W, v))
    if A + C + W != 10:
        FAILS.append("toy/({},{},{}) cost != 10".format(A, C, W))
# naive rounding of the continuous solution FAILS (founding: (3,4,2) -> 4.1167 > 4)
if Vt(3, 4, 2) <= VF:
    FAILS.append("toy/(3,4,2) should FAIL (rounding trap)")
check("toy/round_fail_V", Vt(3, 4, 2), 2.2 + 2 / 3 + 3 / 4 + 1 / 2, 1e-12)
# local trap (2,5,5): exactly on boundary at Cost=12; any single -1 step fails
check("toy/local_trap_V", Vt(2, 5, 5), 4.0, 1e-12)
for nb in ((1, 5, 5), (2, 4, 5), (2, 5, 4)):
    if Vt(*nb) <= VF:
        FAILS.append("toy/neighbor {} should FAIL".format(nb))
# KKT continuous optimum: A:C:W = sqrt2 : sqrt3 : 1, constraint active (V = 4.0)
t = (math.sqrt(2) + math.sqrt(3) + 1) / 1.8
A0, C0, W0 = math.sqrt(2) * t, math.sqrt(3) * t, t
check("toy/kkt_A", A0, 3.2576, 5e-4)
check("toy/kkt_C", C0, 3.9897, 5e-4)
check("toy/kkt_W", W0, 2.3035, 5e-4)
check("toy/kkt_active", Vt(A0, C0, W0), 4.0, 1e-12)
check("toy/kkt_cost", A0 + C0 + W0, 9.5509, 5e-4)

if FAILS:
    for m in FAILS:
        print("FAIL " + m)
    print("{} FAILURES".format(len(FAILS)))
    sys.exit(1)
print("PASS: founding benchmarks (3-node MNA + multi-solution toy, 20 checks)")
