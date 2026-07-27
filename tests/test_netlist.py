# -*- coding: utf-8 -*-
"""schematic → netlist → MNA 자동 변환 검증.

- net 추출: 기대 net 이름·소속 pin 전수 대조 (회로도 기하가 유일한 원천)
- 조립·해석: KCL residual, 직렬 경로 전류 보존, 부동 net, Jacobian 대칭
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.schematic import DEFAULT_LAYOUT  # noqa: E402
from server.netlist import extract_netlist, assemble_and_solve  # noqa: E402

fails = []


def chk(name, cond, detail=""):
    if not cond:
        fails.append("{} {}".format(name, detail))


nl = extract_netlist(DEFAULT_LAYOUT)
names = nl["nets"]


def pins(instance):
    out = []
    for d in nl["devices"]:
        if d["instance"] == instance:
            if d["kind"] in ("pfet", "nfet"):
                out.append((d["kind"], names[d["drain"]], names[d["gate"]], names[d["source"]]))
            else:
                out.append((d["kind"], names[d["a"]], names[d["b"]]))
    return out


# 1) 기대 net 구성 — 회로도 topology 그대로인가
named = set(v for v in names.values() if not v.startswith("n"))
chk("named nets", named == {"VDD", "IO", "VSS", "MVSS", "VDD2", "IO2", "VSS2",
                            "N1", "N2", "N3", "N3B", "OUT", "IN", "VSSR"}, str(sorted(named)))
chk("XRio_rdl pins", pins("XRio_rdl") == [("resistor", "IO", "N1")], str(pins("XRio_rdl")))
chk("XRvss_rdl pins", pins("XRvss_rdl") == [("resistor", "VSS", "VSSR")], str(pins("XRvss_rdl")))
chk("XD_up pins", pins("XD_up") == [("diode", "N1", "N2")], str(pins("XD_up")))
chk("XD_down pins", pins("XD_down") == [("diode", "VSSR", "N1")], str(pins("XD_down")))
chk("XRDD_un1 pins", pins("XRDD_un1") == [("resistor", "N2", "N3")], str(pins("XRDD_un1")))
chk("XRDD_dn1 pins", pins("XRDD_dn1") == [("resistor", "VSSR", "N3B")], str(pins("XRDD_dn1")))
chk("XClamp pins", pins("XClamp") == [("zener", "N3B", "N3")], str(pins("XClamp")))
chk("XResd pins (gate-only)", pins("XResd") == [("resistor", "N1", "IN")], str(pins("XResd")))
chk("XD_up2 pins", pins("XD_up2") == [("diode", "IN", "N2")], str(pins("XD_up2")))
chk("XD_down2 pins", pins("XD_down2") == [("diode", "VSSR", "IN")], str(pins("XD_down2")))
b2bm = sorted(pins("XD_b2b_m"))
chk("XD_b2b_m 역병렬", b2bm == sorted([("diode", "MVSS", "N3B"), ("diode", "N3B", "MVSS")]), str(b2bm))
b2bm2 = sorted(pins("XD_b2b_m2"))
chk("XD_b2b_m2 역병렬", b2bm2 == sorted([("diode", "MVSS", "VSS2"), ("diode", "VSS2", "MVSS")]), str(b2bm2))
vic = sorted(pins("XVictim"))
chk("XVictim FETs", vic == sorted([("pfet", "OUT", "IN", "N2"), ("nfet", "OUT", "IN", "VSSR")]), str(vic))
opens = [d["instance"] for d in nl["devices"] if d["open"]]
chk("open 소자 6개(소스4+b2b가로2)", len(opens) == 6, str(opens))

# 2) 해석 — IO 주입 / VSS 접지
r = assemble_and_solve(nl, inject="IO", ground="VSS", I=1.33, L=350.0)
v = r["v"]
chk("Newton 수렴", r["residual"] < 1e-8, "res={}".format(r["residual"]))
i_rio = (v["IO"] - v["N1"]) / 0.1
i_run = (v["N2"] - v["N3"]) / 0.5
i_rdn = (v["N3B"] - v["VSSR"]) / 0.5
i_rvss = v["VSSR"] / 0.1  # VSS=ref(0)
chk("KCL I(Rio)=I", abs(i_rio - 1.33) < 1e-3, str(i_rio))
chk("리턴 전류 I(Rvss_rdl)=I", abs(i_rvss - 1.33) < 1e-3, str(i_rvss))
chk("직렬 보존 |I(RDDun)-I(RDDdn)| 소", abs(i_run - i_rdn) < 2e-3, "{} vs {}".format(i_run, i_rdn))
chk("경로 단조 IO>N1>N2>N3", v["IO"] > v["N1"] > v["N2"] > v["N3"] > 0, "")
chk("부동 net ≈0 (IO2/VDD2)", abs(v["IO2"]) < 1e-3 and abs(v["VDD2"]) < 1e-3, "")
chk("VDD=N2 (Rvdd_rdl 무전류)", abs(v["VDD"] - v["N2"]) < 1e-6, "")
G = r["G"]
sym = max(abs(G[i][j] - G[j][i]) for i in range(len(G)) for j in range(len(G)))
chk("Jacobian 대칭(2단자 소자만)", sym < 1e-9, str(sym))

# 3) 다른 시나리오도 수렴하는가 (VSS2 주입 / MVSS 접지 — b2b_m2 경유)
r2 = assemble_and_solve(nl, inject="VSS2", ground="MVSS", I=0.5)
chk("VSS2→MVSS 수렴", r2["converged"] and r2["residual"] < 1e-8, str(r2["residual"]))
chk("b2b 순방향 강하 ~0.75V", 0.6 < r2["v"]["VSS2"] < 1.0, str(r2["v"]["VSS2"]))

# 4) 검증 워크플로우 발견 회귀: 부동 net 주입도 수렴(적응형 damping) + converged 플래그
r3 = assemble_and_solve(nl, inject="IO2", ground="VSS", I=1.33)
chk("부동 net(IO2) 수렴", r3["converged"], "res={}".format(r3["residual"]))
chk("부동 net 진해 I/GMIN", abs(r3["v"]["IO2"] - 1.33e9) / 1.33e9 < 1e-3, str(r3["v"]["IO2"]))
chk("converged 키 존재", "converged" in r, "")
allc = all(assemble_and_solve(nl, inject=a, ground=b, I=1.33)["converged"]
           for a, b in (("VDD", "VSS"), ("MVSS", "VDD"), ("N3B", "VSS"), ("IO", "MVSS")))
chk("추가 시나리오 4종 수렴", allc, "")

if fails:
    print("FAIL: netlist/matrix ({}건)".format(len(fails)))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS: schematic→netlist→MNA (net 추출 15건 + 해석 9건)")
