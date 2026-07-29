# -*- coding: utf-8 -*-
"""schematic → netlist → MNA 자동 변환 검증.

- net 추출: 기대 net 이름·소속 pin 전수 대조 (회로도 기하가 유일한 원천)
- 조립·해석: KCL residual, 직렬 경로 전류 보존, 부동 net, Jacobian 대칭
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.schematic import DEFAULT_LAYOUT  # noqa: E402
from server.netlist import extract_netlist, assemble_and_solve  # noqa: E402

fails = []
n_checks = [0]


def chk(name, cond, detail=""):
    n_checks[0] += 1
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
chk("named nets (OUT은 #10에서 N2로 합류)", named == {"VDD", "IO", "VSS", "MVSS", "VDD2",
                                                     "IO2", "VSS2", "N1", "N2", "N3",
                                                     "N3B", "IN", "VSSR"}, str(sorted(named)))
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
vic = pins("XVictim")
chk("XVictim = NMOS 1stk 단일 (이슈 #10, D=VDD rail)", vic == [("nfet", "N2", "IN", "VSSR")],
    str(vic))
chk("PFET 없음", not any(d["kind"] == "pfet" for d in nl["devices"]), "")
opens = [d["instance"] for d in nl["devices"] if d["open"]]
chk("open 소자 5개(소스3+b2b가로2 — IO→VSS 소스는 활성)", len(opens) == 5, str(opens))
chk("IO→VSS forcing 소스 활성", any(d["instance"] == "XI_ESD (IO→VSS)" and not d["open"]
                                     for d in nl["devices"]), "")

# 1b) 이슈 #9 P0 semantics
chk("이름 충돌 없음", nl["name_conflicts"] == [], str(nl["name_conflicts"]))
chk("global ground 없음(현 회로도)", nl["global_ground_nets"] == [], str(nl["global_ground_nets"]))
chk("local ground 5개(전류원 4 + VSS 표현)", len(nl["local_ground_nets"]) == 5
    and "VSS" in [names[g] for g in nl["local_ground_nets"]],
    str([names[g] for g in nl["local_ground_nets"]]))
chk("VSS ground 표현은 ref 강제 아님(6 시나리오 보전)", True, "")  # 아래 6종 sweep이 검증

# enabled가 semantics, color는 표시 전용 (P0-3)
import copy  # noqa: E402
L2 = copy.deepcopy(DEFAULT_LAYOUT)
for e in L2["elements"]:
    if e.get("instance") == "XClamp":
        e["color"] = "#b0b6bf"
chk("색만 회색 → open 아님", not [d for d in extract_netlist(L2)["devices"]
                                  if d["instance"] == "XClamp"][0]["open"], "")
for e in L2["elements"]:
    if e.get("instance") == "XClamp":
        e["enabled"] = False
chk("enabled:False → open", [d for d in extract_netlist(L2)["devices"]
                             if d["instance"] == "XClamp"][0]["open"], "")

# net 이름은 좌표가 아닌 layout 선언에서 (P0-4): port net 키 제거 시 이름 소실
L3 = copy.deepcopy(DEFAULT_LAYOUT)
for e in L3["elements"]:
    if e.get("type") == "port" and e.get("net") == "IO":
        del e["net"]
n3names = set(extract_netlist(L3)["nets"].values())
chk("IO 이름은 port 선언 원천", "IO" not in n3names, str(sorted(n3names)))

# 이름 충돌 감지: 같은 net에 두 이름 선언
L4 = copy.deepcopy(DEFAULT_LAYOUT)
L4["elements"].append({"type": "port", "at": [-3.0, 3.0], "text": "", "net": "IO_ALT"})
nl4 = extract_netlist(L4)
chk("이름 충돌 감지", len(nl4["name_conflicts"]) == 1, str(nl4["name_conflicts"]))

# global ground 인식
L5 = copy.deepcopy(DEFAULT_LAYOUT)
L5["elements"].append({"type": "ground", "at": [-3.0, -3.0], "global": True})
nl5 = extract_netlist(L5)
chk("global ground=MVSS 인식", [nl5["nets"][g] for g in nl5["global_ground_nets"]] == ["MVSS"],
    str(nl5["global_ground_nets"]))

# 1c) P0-6: instance_id 명시 귀속 — 기본 레이아웃은 충돌 0, 전 소자 귀속
chk("귀속 충돌 없음", nl["assoc_conflicts"] == [], str(nl["assoc_conflicts"]))
chk("전 소자 instance 귀속(22)", len(nl["devices"]) == 22
    and all(d["instance"] for d in nl["devices"]),
    str([d for d in nl["devices"] if not d["instance"]]))

# instance_id가 권위: 기하와 불일치하면 instance_id를 따르고 충돌 보고
L6 = copy.deepcopy(DEFAULT_LAYOUT)
for e in L6["elements"]:
    if e.get("instance_id") == "XResd":
        e["instance_id"] = "XD_up"  # 존재하지만 기하상 다른 상자
nl6 = extract_netlist(L6)
resd_dev = [d for d in nl6["devices"] if d["kind"] == "resistor"
            and nl6["nets"][d["a"]] == "N1" and nl6["nets"][d["b"]] == "IN"][0]
chk("불일치 시 instance_id 우선", resd_dev["instance"] == "XD_up", str(resd_dev["instance"]))
chk("불일치 충돌 보고", len(nl6["assoc_conflicts"]) == 1, str(nl6["assoc_conflicts"]))

# 미정의 instance_id → 충돌 보고 + 기하 귀속 fallback
L7 = copy.deepcopy(DEFAULT_LAYOUT)
for e in L7["elements"]:
    if e.get("instance_id") == "XResd":
        e["instance_id"] = "X없는상자"
nl7 = extract_netlist(L7)
resd7 = [d for d in nl7["devices"] if d["kind"] == "resistor"
         and nl7["nets"][d["a"]] == "N1" and nl7["nets"][d["b"]] == "IN"][0]
chk("미정의 id → 기하 fallback", resd7["instance"] == "XResd", str(resd7["instance"]))
chk("미정의 id 충돌 보고", len(nl7["assoc_conflicts"]) == 1, str(nl7["assoc_conflicts"]))

# 1d) P0-5: fet_anchors — 렌더러(schemdraw)와 추출기의 공유 기하
from server.schematic import fet_anchors  # noqa: E402

for kind, sgn in (("pfet", 1.0), ("nfet", -1.0)):
    a = fet_anchors(kind, (5.1, 3.0), rot=180, flip=True, scale=0.64)
    ok = (abs(a["source"][0] - 5.1) < 1e-3 and abs(a["source"][1] - (3.0 + 0.96 * sgn)) < 1e-3
          and abs(a["gate"][0] - 4.225) < 1e-3 and abs(a["gate"][1] - (3.0 + 0.48 * sgn)) < 1e-3)
    chk("fet_anchors {} = 검증된 상수".format(kind), ok, str(a))

# 검증 워크플로우 발견 회귀 4건 (2026-07-28):
# (a) theta 상속 차단 — 오염된 Drawing(직전 요소가 방향을 남김)에서도 rot 생략 FET가
#     fet_anchors(rot=0)와 동일 기하로 배치되는가
import schemdraw  # noqa: E402
import schemdraw.elements as selm  # noqa: E402
from server.schematic import _fet_element  # noqa: E402

dd = schemdraw.Drawing(show=False)
dd.add(selm.Line().at((0.0, 0.0)).to((0.0, -1.0)))  # dwgtheta=270 오염
qq = dd.add(_fet_element("pfet", 0, True, True).at((5.1, 3.0)).anchor('drain').scale(0.64))
aa0 = fet_anchors("pfet", (5.1, 3.0), rot=0, flip=True, scale=0.64, bulk=True)
theta_ok = all(abs(qq.absanchors[n].x - aa0[n][0]) < 1e-9
               and abs(qq.absanchors[n].y - aa0[n][1]) < 1e-9
               for n in ("drain", "source", "gate"))
chk("rot 생략 시 theta 상속 차단(렌더=추출)", theta_ok,
    str({n: (qq.absanchors[n].x, qq.absanchors[n].y) for n in ("source", "gate")}))

# (b) 구형 layout(symbol_scale 없음, scale=1.0): gate 배선이 명시 지오메트리(#10에서
#     gates helper 삭제)이므로 렌더·추출 **일치되게** 끊긴다 — gate는 부동 net으로
#     정직하게 보고되고 monitor 평가가 unresolved g를 잡는다 (무경고 오추출 없음).
L8 = copy.deepcopy(DEFAULT_LAYOUT)
del L8["symbol_scale"]
nl8 = extract_netlist(L8)
g8 = [nl8["nets"][d["gate"]] for d in nl8["devices"] if d["kind"] == "nfet"][0]
chk("scale=1.0 gate는 부동 net(시각과 일치)", g8 != "IN" and g8.startswith("n"), g8)
from server.netlist import evaluate_soa_monitors  # noqa: E402
r8 = assemble_and_solve(nl8, inject="IO", ground="VSS", I=1.33)
m8 = evaluate_soa_monitors(nl8, r8)[0]
chk("scale=1.0 monitor가 g 미해석 보고", m8["reason"] == "unresolved_monitor_terminal"
    and any(u["terminal"] == "g" for u in m8["unresolved_terminals"]),
    str(m8["unresolved_terminals"]))

# (c) 상자 겹침: midpoint가 자기 instance_id 상자 안이면 충돌 아님
L9 = copy.deepcopy(DEFAULT_LAYOUT)
for e in L9["elements"]:
    if e.get("instance") == "XD_up":
        e["corner1"], e["corner2"] = [-0.9, 2.5], [2.0, 5.1]  # XResd 상자를 덮게 확장
nl9 = extract_netlist(L9)
resd9 = [d for d in nl9["devices"] if d["kind"] == "resistor"
         and nl9["nets"][d["a"]] == "N1" and nl9["nets"][d["b"]] == "IN"][0]
chk("겹침 시 자기상자 포함 → 충돌 아님", nl9["assoc_conflicts"] == [], str(nl9["assoc_conflicts"]))
chk("겹침 시 귀속 유지", resd9["instance"] == "XResd", str(resd9["instance"]))

# (d) instance 중복 정의: 첫 정의 우선 + 충돌 보고
L10 = copy.deepcopy(DEFAULT_LAYOUT)
L10["elements"].append({"type": "rect", "corner1": [20.0, 20.0], "corner2": [21.0, 21.0],
                        "instance": "XResd", "cell": "r", "enabled": False})
nl10 = extract_netlist(L10)
resd10 = [d for d in nl10["devices"] if d["kind"] == "resistor"
          and nl10["nets"][d["a"]] == "N1" and nl10["nets"][d["b"]] == "IN"][0]
chk("중복 정의 첫 정의 우선(open 미상속)", not resd10["open"], str(resd10["open"]))
chk("중복 정의 충돌 보고", any("중복" in c for c in nl10["assoc_conflicts"]),
    str(nl10["assoc_conflicts"]))

# 회전 회귀: rot 0/90/180/270×flip에서 추출기 pin 좌표 = schemdraw anchor 좌표
#   (port를 anchor 좌표에 직접 두면 pin과 같은 net이어야 이름이 붙는다)
for rot in (0, 90, 180, 270):
    for flip in (False, True):
        aa = fet_anchors("nfet", (0.0, 0.0), rot=rot, flip=flip, scale=0.64)
        Lr = {"symbol_scale": 0.64, "nodes": {}, "elements": [
            {"type": "nfet", "drain": [0.0, 0.0], "rot": rot, "flip": flip},
            {"type": "port", "at": list(aa["drain"]), "net": "D"},
            {"type": "port", "at": list(aa["source"]), "net": "S"},
            {"type": "port", "at": list(aa["gate"]), "net": "G"},
        ]}
        nr = extract_netlist(Lr)
        fdev = [d for d in nr["devices"] if d["kind"] == "nfet"][0]
        got = (nr["nets"][fdev["drain"]], nr["nets"][fdev["source"]], nr["nets"][fdev["gate"]])
        chk("rot={} flip={} anchor 일치".format(rot, flip), got == ("D", "S", "G"), str(got))

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

# 5) 이슈 #9 P0-2: 시나리오 유효성 — inject==ground / inject∈reference 거부
try:
    assemble_and_solve(nl, inject="VSS", ground="VSS", I=1.0)
    chk("inject==ground 거부", False, "예외 없음")
except ValueError:
    pass
try:
    assemble_and_solve(nl5, inject="MVSS", ground="VSS", I=1.0)  # MVSS는 global ground
    chk("inject∈global-ground 거부", False, "예외 없음")
except ValueError:
    pass
# local ground는 reference가 아니므로 그 net 주입은 허용되어야 함 (전류원 내부 stub 선택)
lg0 = [nl["nets"][g] for g in nl["local_ground_nets"] if nl["nets"][g].startswith("n")][0]
chk("local ground net 주입 허용", assemble_and_solve(nl, inject=lg0, ground="VSS", I=0.1)["converged"],
    lg0)

# 6) 이슈 #10 — NMOS 1stk SOA monitor
from server.netlist import evaluate_soa_monitors, soa_rules_for, sweep_scenario, RAIL_SCENARIOS  # noqa: E402

vic_dev = [d for d in nl["devices"] if d["instance"] == "XVictim"][0]
chk("monitor role 보존", vic_dev["role"] == "soa_monitor", str(vic_dev["role"]))
chk("monitor equation 없음", vic_dev["equation"] is None, str(vic_dev["equation"]))
chk("monitor model 단일 문자열", vic_dev["model"] == "SG_NFET 1stk_1rx", str(vic_dev["model"]))
tm = vic_dev["terminals"]
chk("terminal map D/G/S/B", (names[tm["d"]], names[tm["g"]], names[tm["s"]]) == ("N2", "IN", "VSSR"),
    str({k: names[v] for k, v in tm.items()}))
chk("B=S short 유지", tm["b"] == tm["s"], "")

# matrix 불변: monitor 제거 전후 active 해 동일 (0 기여)
L11 = copy.deepcopy(DEFAULT_LAYOUT)
L11["elements"] = [e for e in L11["elements"]
                   if not (e.get("instance_id") == "XVictim" or e.get("instance") == "XVictim")]
r11 = assemble_and_solve(extract_netlist(L11), inject="IO", ground="VSS", I=1.33)
common = set(r["v"]) & set(r11["v"])
chk("monitor 제거 시 해 불변", max(abs(r["v"][k] - r11["v"][k]) for k in common) < 1e-12, "")

# role 없는 nfet은 여전히 stamp됨 (equation is None만으로 monitor 간주 금지)
def _mon_layout(role, drain_y=0.0):
    a = fet_anchors("nfet", (0.0, drain_y), rot=180, flip=True, scale=0.64)
    rect = {"type": "rect", "corner1": [-2.0, -1.6], "corner2": [0.6, 0.8],
            "instance": "XMON", "cell": "victim", "model": "SG_NFET 1stk_1rx", "params": {}}
    if role:
        rect["role"] = role
    return {"symbol_scale": 0.64, "nodes": {}, "elements": [
        {"type": "nfet", "drain": [0.0, drain_y], "rot": 180, "flip": True, "instance_id": "XMON"},
        rect,
        {"type": "line", "from": list(a["gate"]), "to": [a["gate"][0], 0.0]},
        {"type": "line", "from": [a["gate"][0], 0.0], "to": [0.0, 0.0]},
        {"type": "line", "from": [0.0, 0.0], "to": [1.0, 0.0]},
        {"type": "port", "at": [1.0, 0.0], "net": "X"},
        {"type": "resistor", "from": [1.0, 0.0], "to": [3.0, 0.0]},
        {"type": "line", "from": [3.0, 0.0], "to": [4.0, 0.0]},
        {"type": "port", "at": [4.0, 0.0], "net": "Y"},
        {"type": "line", "from": list(a["source"]), "to": [0.0, -2.0]},
        {"type": "line", "from": [0.0, -2.0], "to": [4.0, -2.0]},
        {"type": "line", "from": [4.0, -2.0], "to": [4.0, 0.0]},
    ]}

# nfet 접합 diode는 source→drain — Y(=source측) 주입에서 도통
nl_act = extract_netlist(_mon_layout(None))
r_act = assemble_and_solve(nl_act, inject="Y", ground="X", I=1.0)
nl_mon = extract_netlist(_mon_layout("soa_monitor"))
r_mon = assemble_and_solve(nl_mon, inject="Y", ground="X", I=1.0)
chk("role 없는 nfet stamp됨(접합 diode 도통)", r_act["v"]["Y"] < 0.9 * r_mon["v"]["Y"],
    "act={} mon={}".format(r_act["v"]["Y"], r_mon["v"]["Y"]))
chk("monitor는 R만 남아 V=I·R", abs(r_mon["v"]["Y"] - 1.0) < 1e-3, str(r_mon["v"]["Y"]))

# 기본 회로도: drain이 VDD rail(N2)에 연결(사용자 지시) → 전 terminal 해석 가능,
# IO/VSS 1.33A에서 SOA FAIL (VGS=IN−VSSR=5.843V > +2.9V, worst)
mons = evaluate_soa_monitors(nl, r)
m0 = mons[0]
chk("monitor 유효(전 단자 해석)", m0["valid"] is True and m0["reason"] is None,
    str((m0["valid"], m0["reason"])))
chk("1.33A SOA FAIL·worst=VGS", m0["passed"] is False and m0["worst_quantity"] == "VGS",
    str((m0["passed"], m0["worst_quantity"])))
chk("worst margin ≈ −2.943", abs(m0["worst_margin"] + 2.943) < 5e-3, str(m0["worst_margin"]))
chk("VGD는 PASS", [c for c in m0["checks"] if c["quantity"] == "VGD"][0]["passed"], "")

# unresolved terminal: drain→rail 배선을 끊은 변형 — d가 부동 → 무효 보고 (GMIN 전압 미사용)
L12 = copy.deepcopy(DEFAULT_LAYOUT)
L12["elements"] = [e for e in L12["elements"]
                   if not (e.get("type") == "line" and e.get("from") == [5.1, 3.0])]
nl12 = extract_netlist(L12)
r12 = assemble_and_solve(nl12, inject="IO", ground="VSS", I=1.33)
m12 = evaluate_soa_monitors(nl12, r12)[0]
chk("drain 절단 시 unresolved 보고", m12["valid"] is False
    and m12["reason"] == "unresolved_monitor_terminal", str((m12["valid"], m12["reason"])))
chk("unresolved terminal=d", [u["terminal"] for u in m12["unresolved_terminals"]] == ["d"],
    str(m12["unresolved_terminals"]))
chk("GMIN 전압 미사용(voltage None)", m12["terminals"]["d"]["voltage"] is None, "")
chk("unresolved는 PASS 아님", m12["passed"] is None and m12["checks"] == [], "")

# SOA rule (victim_soa 실측 유도) + 경계 golden: VGS 한계 +2.9V (직전/경계/직후)
rules = soa_rules_for("SG_NFET 1stk_1rx")
chk("rule 4종(VDS/VGS/VGD/VGB)", [x["quantity"] for x in rules] == ["VDS", "VGS", "VGD", "VGB"]
    and rules[0]["max"] == 3.1 and rules[1] == {"quantity": "VGS", "min": -3.3, "max": 2.9},
    str(rules))
for i_in, want_pass in ((2.89, True), (2.9, True), (2.95, False)):
    r_g = assemble_and_solve(nl_mon, inject="X", ground="Y", I=i_in)
    mg = evaluate_soa_monitors(nl_mon, r_g)[0]
    chk("경계 golden I={} → {}".format(i_in, "PASS" if want_pass else "FAIL"),
        mg["valid"] and mg["passed"] is want_pass,
        str((mg["valid"], mg["passed"], mg["worst_quantity"], mg["worst_margin"])))
r_g = assemble_and_solve(nl_mon, inject="X", ground="Y", I=2.95)
mg = evaluate_soa_monitors(nl_mon, r_g)[0]
chk("worst=VGS(2.9)이지 VDS(3.1) 아님", mg["worst_quantity"] == "VGS", str(mg["worst_quantity"]))
chk("fail margin 음수", mg["worst_margin"] < 0, str(mg["worst_margin"]))
chk("stress 전체 pair 보존", set(mg["stress"]) == {"VGS", "VGD", "VDS", "VGB", "VDB", "VSB"},
    str(mg["stress"]))

# sweep: 연결된 monitor에서 first fail·limiter, 기본 회로도에서 6종 schema 일관
sw = sweep_scenario(nl_mon, "X", "Y", imax=4.0, n=41)
chk("sweep first_soa_fail ≈ 3.0A", sw["first_soa_fail"] is not None
    and abs(sw["first_soa_fail"]["current"] - 3.0) < 1e-9,
    str(sw["first_soa_fail"]))
chk("active_limiter=XMON:VGS", sw["active_limiter"] == "XMON:VGS", str(sw["active_limiter"]))
chk("SOA fail ≠ solve 실패(해 저장)", all(p["converged"] for p in sw["points"])
    and any(p["status"] == "soa_fail" for p in sw["points"]), "")
chk("sweep 상태 단조 pass→fail", [p["status"] for p in sw["points"]]
    == ["pass"] * 30 + ["soa_fail"] * 11, str([p["status"] for p in sw["points"][28:33]]))
KEYS = {"force", "ground", "imax", "imin", "n", "points",
        "first_soa_fail", "first_soa_fail_neg", "last_converged", "last_converged_neg",
        "active_limiter", "active_limiter_neg"}
STATES = {"non_convergence", "unresolved_monitor_terminal", "soa_fail", "pass"}
ok6 = True
limiters = {}
for fc, gd in RAIL_SCENARIOS:
    s6 = sweep_scenario(nl, fc, gd, imax=1.33, n=5)
    if set(s6) != KEYS or len(s6["points"]) != 5 \
       or any(p["status"] not in STATES for p in s6["points"]):
        ok6 = False
    limiters["{}→{}".format(fc, gd)] = s6["active_limiter"]
chk("6종 rail 시나리오 schema 일관", ok6, "")
chk("시나리오별 limiter 구분(VGS/VGD/VDS)", limiters["IO→VSS"] == "XVictim:VGS"
    and limiters["VDD→IO"] == "XVictim:VGD" and limiters["VDD→VSS"] == "XVictim:VDS"
    and limiters["VSS→IO"] is None, str(limiters))

# 7) 실측 model 연계 (사용자 궁극 목표): MNA measured vs series 해석해 golden
from server.netlist import measured_context, device_voltages  # noqa: E402
from server import model as M  # noqa: E402

ctx = measured_context(2.56, 1415.232, "worst")
rm = assemble_and_solve(nl, inject="IO", ground="VSS", I=1.33, model_ctx=ctx)
c1w, c2w = M.calib(M.D1, 2.56, "worst"), M.calib(M.D2, 1415.232, "worst")
vio_series = M.series_vio(c1w, c2w, 1.33)
chk("measured V(IO) = series 해석해", rm["converged"]
    and abs(rm["v"]["IO"] - vio_series) < 2e-3,
    "MNA={} series={}".format(rm["v"]["IO"], vio_series))
chk("measured diode 강하 = VofI(D1)", abs((rm["v"]["N1"] - rm["v"]["N2"])
                                          - M.VofI(c1w["pos"], 1.33)) < 2e-3, "")
chk("measured clamp 강하 = VofI(D2)", abs((rm["v"]["N3"] - rm["v"]["N3B"])
                                          - M.VofI(c2w["pos"], 1.33)) < 1e-3, "")

# device_v: 저항 제외 전 device 양단 전압 (동적 그래프 원천)
dv = device_voltages(nl, rm)
chk("device_v 11종(저항 제외)", len(dv) == 11 and "XD_up" in dv and "XClamp" in dv
    and "XI_ESD (IO→VSS)" in dv and not any(k.startswith("XR") for k in dv), str(sorted(dv)))
chk("device_v XD_up = diode 강하", abs(dv["XD_up"] - (rm["v"]["N1"] - rm["v"]["N2"])) < 1e-12, "")

# 실측 sweep: first-fail 전류가 물리 스케일 (IO→VSS 0.9A VGS —
# secondary x1/10·b2b esdvpnp 바인딩 후 IN 전압 상승으로 1.0→0.9A, 2026-07-28)
swm = sweep_scenario(nl, "IO", "VSS", imax=2.0, n=21, model_ctx=ctx)
chk("measured sweep first fail I=0.9 VGS", swm["first_soa_fail"] is not None
    and abs(swm["first_soa_fail"]["current"] - 0.9) < 1e-9
    and swm["first_soa_fail"]["quantity"] == "VGS", str(swm["first_soa_fail"]))

# 주어진 모델 바인딩 규칙: b2b=esdvpnp(D1) 동일 곡선, secondary=면적 1/10
by_inst = {d["instance"]: d for d in nl["devices"]}
chk("b2b→esdvpnp 곡선 공유", ctx(by_inst["XD_b2b_m"]) is ctx(by_inst["XD_up"]), "")
chk("secondary 면적 1/10 (전류 감소)", ctx(by_inst["XD_up2"])(1.5)[0] < 0.25 * ctx(by_inst["XD_up"])(1.5)[0],
    "p={} s={}".format(ctx(by_inst["XD_up"])(1.5)[0], ctx(by_inst["XD_up2"])(1.5)[0]))
chk("down diode 동일 모델(D1)", ctx(by_inst["XD_down"]) is ctx(by_inst["XD_up"]), "")
chk("measured sweep 전 point 수렴", all(p["converged"] for p in swm["points"]), "")
chk("sweep point에 device_v 포함", all("device_v" in p and len(p["device_v"]) == 11
                                       for p in swm["points"]), "")

# 소자별 SOA endpoint (element 좌표계): size 스케일 + clamp 방향 반전
from server.netlist import soa_endpoints  # noqa: E402
eps = soa_endpoints(nl, 2.56, 1415.232, "worst")
e_up, e_up2, e_cl = eps["XD_up"], eps["XD_up2"], eps["XClamp"]
chk("endpoint: secondary size=x1/10", abs(e_up2["size"] - 0.256) < 1e-12
    and e_up2["ip"] < 0.5 * e_up["ip"], str((e_up2["size"], e_up2["ip"], e_up["ip"])))
e_d2 = M.ep(M.D2, 1415.232, "worst")
chk("endpoint: clamp element 좌표계 반전(주 도통=음방향)",
    abs(e_cl["vn"] + e_d2["vp"]) < 1e-12 and abs(e_cl["inn"] + e_d2["ip"]) < 1e-12
    and abs(e_cl["vp"] + e_d2["vn"]) < 1e-12, str(e_cl))
chk("endpoint: 전류원·monitor는 None", eps["XI_ESD (IO→VSS)"] is None and eps["XVictim"] is None, "")
chk("endpoint: b2b도 D1 endpoint", abs(eps["XD_b2b_m"]["ip"] - e_up["ip"]) < 1e-12, "")

# device_i: KCL — 주입 2A = D_up + D_up2 분담, monitor/전류원 None
sw2 = sweep_scenario(nl, "IO", "VSS", imax=2.0, n=3, model_ctx=ctx)
pi = sw2["points"][-1]["device_i"]
chk("device_i KCL(2A 분담)", abs(pi["XD_up"] + pi["XD_up2"] - 2.0) < 2e-3,
    str((pi["XD_up"], pi["XD_up2"])))
chk("device_i monitor/전류원 None", pi["XVictim"] is None and pi["XI_ESD (IO→VSS)"] is None, "")

# capacitance spec (사용자 지시 2026-07-28): model.CAP 물리 생성 모델, EM 제외
from server.netlist import device_caps  # noqa: E402

caps = device_caps(nl, 2.56, 1415.232)
chk("cap: 기준 diode C0=250fF", abs(caps["XD_up"]["c0"] - 250e-15) < 1e-18,
    str(caps["XD_up"]))
chk("cap: 기준 clamp C0=2.1pF", abs(caps["XClamp"]["c0"] - 2.1e-12) < 1e-15, "")
chk("cap: secondary 면적 1/10 → C/10", abs(caps["XD_up2"]["c0"] - 25e-15) < 1e-18,
    str(caps["XD_up2"]["c0"]))
chk("cap: b2b=D1 cap 공유", abs(caps["XD_b2b_m"]["c0"] - caps["XD_up"]["c0"]) < 1e-20, "")
chk("cap: 전류원/monitor None", caps["XI_ESD (IO→VSS)"] is None and caps["XVictim"] is None, "")
on_io = sorted(k for k, c in caps.items() if c and c["on_io"])
chk("cap: IO에서 보이는 소자 4종", on_io == ["XD_down", "XD_down2", "XD_up", "XD_up2"],
    str(on_io))
# cap spec 정본 = direct up/down 0V 합 (이슈 #13 완전 교체) — on_io는 페이지 표시 정보로만
from server.netlist import direct_io_cap  # noqa: E402

io_total = direct_io_cap(nl)
chk("cap 정본: direct up/down 합 500fF ≤ capLim 5pF (up2/down2·b2b·clamp 제외)",
    abs(io_total - 500e-15) < 1e-18 and io_total < M.IO_CAP_LIM
    and abs(direct_io_cap(nl, pset={"x2": 2628.0}) - io_total) < 1e-20, str(io_total))
chk("I_esd spec: HBM 1kV=1.33A, 2kV=2.66A (D9)", abs(M.hbm_current(1) - 1.33) < 1e-12
    and abs(M.hbm_current(2) - 2.66) < 1e-12 and 2.0 in M.HBM_LEVELS_KV, "")
chk("HBM default = 1kV (1.33A)", M.HBM_DEFAULT_KV == 1.0
    and abs(M.hbm_current(M.HBM_DEFAULT_KV) - 1.33) < 1e-12, "")
c_rev = M.cap_of(M.D1, 2.56, -5.0)   # 역바이어스 감소
c_fwd = M.cap_of(M.D1, 2.56, 0.5)    # 순방향 증가 (FC 상한)
chk("cap: C-V 단조(역감소·순증가)", c_rev < 250e-15 < c_fwd
    and abs(M.cap_of(M.D1, 2.56, 5.0) - M.cap_of(M.D1, 2.56, 0.375)) < 1e-20,
    "rev={} fwd={}".format(c_rev, c_fwd))

# 양극 sweep (사용자 지시 2026-07-28): I=-2→+2, 0에서 두 갈래 continuation
swb = sweep_scenario(nl, "IO", "VSS", imax=2.0, n=41, imin=-2.0, model_ctx=ctx)
bI = [p["I"] for p in swb["points"]]
chk("양극 sweep 41점 오름차순", len(bI) == 41 and bI == sorted(bI)
    and abs(bI[0] + 2.0) < 1e-12 and abs(bI[-1] - 2.0) < 1e-12, str((bI[0], bI[-1], len(bI))))
chk("양극 sweep I=0 포함", any(abs(i) < 1e-12 for i in bI), "")
chk("양극 sweep 전 point 수렴", all(p["converged"] for p in swb["points"]), "")
chk("양극 first fail 극성별 보고", swb["first_soa_fail"] is not None
    and abs(swb["first_soa_fail"]["current"] - 0.9) < 1e-9
    and "first_soa_fail_neg" in swb, str((swb["first_soa_fail"], swb["first_soa_fail_neg"])))
neg_pt = swb["points"][0]  # I=-2: 음(-) 스트레스 — down diode가 자기 좌표계 순방향 도통
chk("음극에서 down diode 순방향 도통(+2A)", neg_pt["device_i"]["XD_down"] > 1.5,
    str(neg_pt["device_i"]["XD_down"]))
chk("음극 V(IO) 음수", neg_pt["v"]["IO"] < -1.0, str(neg_pt["v"]["IO"]))

# pwl kink 진동 회귀 (2026-07-28 발견): 병렬 실측 diode도 backtracking으로 수렴
Lp = copy.deepcopy(DEFAULT_LAYOUT)
Lp["elements"].append({"type": "diode", "from": "N1", "to": "N2"})
rp = assemble_and_solve(extract_netlist(Lp), inject="IO", ground="VSS", I=1.33, model_ctx=ctx)
chk("병렬 실측 diode 수렴", rp["converged"], "res={}".format(rp["residual"]))
chk("병렬 시 diode 강하 감소", 0.5 < (rp["v"]["N1"] - rp["v"]["N2"]) < M.VofI(c1w["pos"], 1.33),
    str(rp["v"]["N1"] - rp["v"]["N2"]))

# 8) MNA 기반 optimizer (궁극 목표 마지막 조각): loss 평가기 = schematic MNA
from server.opt_mna import optimize_mna  # noqa: E402

prog = []
ro = optimize_mna(DEFAULT_LAYOUT, 2.56, 1415.232, 350.0, iters=4, n=200,
                  progress_cb=lambda d, t: prog.append((d, t)))
chk("opt: 초기 HBM 1kV FAIL(victim 지배)", ro["initial"]["soa_pass"] is False
    and "XVictim" in str(ro["initial"]["worst_name"]), str(ro["initial"]["worst_name"]))
chk("opt: worst usage 감소 방향", ro["final"]["worst"] < ro["initial"]["worst"],
    "{} -> {}".format(ro["initial"]["worst"], ro["final"]["worst"]))
chk("opt: history/schema", len(ro["history"]) == 5
    and all(k in ro["final"] for k in ("x1", "x2", "L", "worst", "soa_pass", "usages")), "")
chk("opt: 탐색 범위 유지", 0.3 < ro["final"]["x1"] < 4.7 and ro["final"]["L"] >= 1.0,
    str((ro["final"]["x1"], ro["final"]["L"])))
# 진행률 콜백 (사용자 지시 2026-07-28): evaluate 단위, 초기 0 → 단조증가 → done==total
_tot = 1 + 4 * 6 + max(1, round(M.N / 200))  # 활성 4(L,W,x1,x2)+2
chk("opt: progress 단조증가·완료 done==total", prog[0] == (0, _tot)
    and all(prog[i][0] < prog[i + 1][0] for i in range(len(prog) - 1))
    and prog[-1] == (_tot, _tot) and all(t == _tot for _, t in prog), str(prog[:3] + prog[-2:]))

# freeze (사용자 확정 2026-07-28): gradient 마스크 — L 불변 + FD 생략(iter당 4 eval)
prog_f = []
rf = optimize_mna(DEFAULT_LAYOUT, 2.56, 1415.232, 350.0, iters=2, n=200,
                  freeze=("L",), progress_cb=lambda dn, t: prog_f.append((dn, t)))
chk("opt freeze: L 전 iteration 불변", all(abs(h["L"] - 350.0) < 1e-9 for h in rf["history"])
    and abs(rf["final"]["L"] - 350.0) < 1e-9, str([h["L"] for h in rf["history"]]))
chk("opt freeze: x1/x2는 여전히 이동", any(abs(h["x1"] - 2.56) > 1e-6 for h in rf["history"]), "")
chk("opt freeze: descriptor frozen 플래그 (registry 순서, W=rule 창 있어 자유)",
    [(v["key"], v["frozen"]) for v in rf["variables"]]
    == [("L", True), ("W", False), ("x1", False), ("x2", False)],
    str([(v["key"], v["frozen"]) for v in rf["variables"]]))
_tot_f = 1 + 2 * 5 + max(1, round(M.N / 200))  # 활성 3(W,x1,x2)+2
chk("opt freeze: 진행률 total = 1+iters×(활성+2)+가중", prog_f[-1] == (_tot_f, _tot_f),
    str(prog_f[-1]))
for _bad_fz, _msg in ((("x1", "x2", "L", "W"), "전 변수 고정"), (("bogus",), "미지 변수")):
    try:
        optimize_mna(DEFAULT_LAYOUT, 2.56, 1415.232, 350.0, iters=1, freeze=_bad_fz)
        chk("opt freeze: {} 거부".format(_msg), False, "예외 없음")
    except ValueError:
        chk("opt freeze: {} 거부".format(_msg), True, "")

# 9) instance/subcircuit 정본 페이지 원천 (사용자 지시 2026-07-28): /api/instance/info
from server.main import instance_info, _slug  # noqa: E402
from server.schematic import LIBRARY_CELLS  # noqa: E402

ii = instance_info()
chk("info: 19 instances 전수(저항·open 포함)", len(ii["instances"]) == 19
    and sum(1 for i in ii["instances"] if i["open"]) == 4, str(len(ii["instances"])))
chk("info: slug 앵커 규칙(영숫자·한글 외 '_')", _slug("XI_ESD (IO→VSS)") == "XI_ESD_IO_VSS_"
    and all(i["slug"] == _slug(i["instance"]) for i in ii["instances"]), "")
by_i = {i["instance"]: i for i in ii["instances"]}
chk("info: diode에 soa/cap/curve 병합", by_i["XD_up"]["soa"] is not None
    and by_i["XD_up"]["cap"] is not None and len(by_i["XD_up"]["curve"]["V"]) > 10, "")
chk("info: monitor에 SOA rules", by_i["XVictim"]["rules"] is not None
    and any(r["quantity"] == "VDS" for r in by_i["XVictim"]["rules"]), "")
chk("info: rdd(L) 저항 resolve", abs(by_i["XRDD_un1"]["R"] - 0.5) < 1e-12,
    str(by_i["XRDD_un1"].get("R")))
chk("info: cells=LIBRARY_CELLS 전수 + instance 역링크", len(ii["cells"]) == len(LIBRARY_CELLS)
    and "XVictim" in next(c for c in ii["cells"] if c["id"] == "victim_n")["instances"], "")

# 10) PSET 파이프라인 S1 (이슈 #11): 바인딩 파서(발견=평가 공유) + pset 단일 운반
from server.netlist import parse_binding, eval_binding, free_params  # noqa: E402

pb = parse_binding("rdd(L,W)")
chk("파서: func_expr 기호 추출", pb["kind"] == "func" and pb["symbols"] == ["L", "W"], str(pb))
chk("파서: size_expr 분수 평가", parse_binding("x1/10")["symbols"] == ["x1"]
    and abs(eval_binding(parse_binding("x1/10"), {"x1": 2.56}) - 0.256) < 1e-12, "")
chk("파서: 상수/해석불가 구분", parse_binding("2.5")["kind"] == "const"
    and parse_binding("a+b") is None, "")
chk("파서: rdd(L,W) 평가 = model.rdd_r", abs(eval_binding(pb, {"L": 350.0, "W": 10.0}) - 0.25) < 1e-12, "")
try:
    eval_binding(parse_binding("foo(T)"), {"T": 1.0})
    chk("파서: 미지 바인딩 함수 거부 (E1)", False, "예외 없음")
except ValueError:
    chk("파서: 미지 바인딩 함수 거부 (E1)", True, "")

r_w5 = assemble_and_solve(nl, inject="IO", ground="VSS", I=1.33, model_ctx=ctx)
r_w10 = assemble_and_solve(nl, inject="IO", ground="VSS", I=1.33, model_ctx=ctx,
                           pset={"W": 10.0})
chk("pset: 결과 echo (기본 W=5)", r_w5["pset"]["W"] == 5.0 and r_w10["pset"]["W"] == 10.0
    and r_w5["pset"]["L"] == 350.0, str(r_w5["pset"]))

# S5: 기본 schematic 바인딩 = rdd(L,W) — W가 발견·평가 전 층에 흐른다
fpw = {p["name"] for p in free_params(nl)}
chk("발견: 기본 바인딩 rdd(L,W) → W 자동 발견", fpw == {"L", "W", "x1", "x2"}, str(fpw))
chk("평가: W=10 → RDD 절반 → ΔV(IO)=1.33×0.5Ω",
    r_w10["converged"] and abs((r_w5["v"]["IO"] - r_w10["v"]["IO"]) - 1.33 * 0.5) < 0.05,
    str((r_w5["v"]["IO"], r_w10["v"]["IO"])))
Lw = copy.deepcopy(DEFAULT_LAYOUT)  # (S3 테스트 재사용 — 기본과 동일해짐)
nlw = extract_netlist(Lw)
Lo = copy.deepcopy(DEFAULT_LAYOUT)  # 구형 rdd(L)로 되돌린 층 — W 미발견·미반영 확인
for el in Lo["elements"]:
    if isinstance(el, dict) and str((el.get("params") or {}).get("R", "")).replace(" ", "") == "rdd(L,W)":
        el["params"]["R"] = "rdd(L)"
nlo = extract_netlist(Lo)
chk("발견: rdd(L)이면 W 미발견 (발견=평가 일치)",
    {p["name"] for p in free_params(nlo)} == {"L", "x1", "x2"}, "")
ro5 = assemble_and_solve(nlo, inject="IO", ground="VSS", I=1.33, model_ctx=ctx,
                         pset={"W": 10.0})
chk("평가: rdd(L)은 W 무관", abs(ro5["v"]["IO"] - r_w5["v"]["IO"]) < 1e-9,
    str((ro5["v"]["IO"], r_w5["v"]["IO"])))

# 11) PSET 파이프라인 S2 (이슈 #11): supported 자동 판정 + pset query 수집
from server.main import _params_registry, _pset_from_query  # noqa: E402

reg = _params_registry(nl)
chk("S2 registry: 현 schematic 4기호 전부 supported (화이트리스트 폐지)",
    {r["name"]: r["supported"] for r in reg}
    == {"L": True, "W": True, "x1": True, "x2": True},
    str([(r["name"], r["supported"]) for r in reg]))
regw = _params_registry(nlw)
Lf = copy.deepcopy(DEFAULT_LAYOUT)
for el in Lf["elements"]:
    if isinstance(el, dict) and str((el.get("params") or {}).get("R", "")).startswith("rdd"):
        el["params"]["R"] = "foo(T)"
        break
regf = _params_registry(extract_netlist(Lf))
tf = next(r for r in regf if r["name"] == "T")
chk("S2 registry: 미지 함수 기호 — 발견되나 미지원 (E1/E2)", tf["supported"] is False
    and tf["meta_defined"] is False and tf["default"] is None, str(tf))
p2, e2 = _pset_from_query({"W": "10"}, regw)
chk("S2 pset query: 값 반영 + META default 병합", e2 is None and p2["W"] == 10.0
    and p2["L"] == 350.0 and p2["x1"] == 2.56, str(p2))
_, e3 = _pset_from_query({"L": "-5"}, reg)
chk("S2 pset query: 무효값 422 (E5)", e3 is not None and e3.status_code == 422, "")
ii2 = instance_info()
chk("S2 instance_info: pset=발견 기호만 echo + R=파서 평가",
    set(ii2["pset"]) == {"L", "W", "x1", "x2"}
    and abs(next(i for i in ii2["instances"] if i["instance"] == "XRDD_un1")["R"] - 0.5) < 1e-12,
    str(ii2.get("pset")))
# 정본 페이지 model 표시 (사용자 지시 2026-07-28: model 반영분이 instance/subcircuit에 보여야)
rr = next(i for i in ii2["instances"] if i["instance"] == "XRDD_un1")
chk("instance: metal model 식·인자 표시 데이터", rr["R_expr"] == "rdd(L,W)"
    and "0.5" in rr["R_desc"] and rr["R_args"] == {"L": 350.0, "W": 5.0}, str(rr.get("R_desc")))
cr = next(c for c in ii2["cells"] if any(b.startswith("R=rdd") for b in c["bindings"]))
chk("subcircuit: cell 바인딩 집계 + 식 정본(docstring)", "R=rdd(L,W)" in cr["bindings"]
    and "sheet" in ii2["binding_funcs"]["rdd"], str((cr["id"], cr["bindings"])))
chk("W rule 창 [1,12] registry 반영",
    next(r for r in reg if r["name"] == "W")["rule_lo"] == 1.0
    and next(r for r in reg if r["name"] == "W")["rule_hi"] == 12.0, "")

# 12) PSET 파이프라인 S3 (이슈 #11): optimizer N-차원 자동 구성
r3 = optimize_mna(Lw, iters=1, n=200, windows={"x1": (1.0, 3.0)}, freeze=("L", "W"))
v3 = {v["key"]: v for v in r3["variables"]}
chk("S3 opt: rdd(L,W) → 변수 4개 자동 (registry 순서)",
    list(v3) == ["L", "W", "x1", "x2"], str(list(v3)))
chk("S3 opt: W rule 창 [1,12] META 반영 + 잠금 가능",
    v3["W"]["lo"] == 1.0 and v3["W"]["hi"] == 12.0 and v3["W"]["lockable"] is True
    and v3["W"]["frozen"] is True and v3["L"]["lockable"] is True, str(v3["W"]))
chk("S3 opt: windows override 반영", v3["x1"]["lo"] == 1.0 and v3["x1"]["hi"] == 3.0, "")
chk("S3 opt: freeze W는 전 history 불변(5.0)",
    all(h["W"] == 5.0 for h in r3["history"]) and r3["final"]["W"] == 5.0, "")
chk("S3 opt: pset echo", r3["pset"]["W"] == 5.0 and r3["pset"]["L"] == 350.0, str(r3["pset"]))
try:
    optimize_mna(Lw, iters=1, n=200, freeze=("x1", "x2", "L", "W"))
    chk("S3 opt: 전 변수 freeze → 대상 없음 거부 (E4)", False, "예외 없음")
except ValueError:
    chk("S3 opt: 전 변수 freeze → 대상 없음 거부 (E4)", True, "")
_wr = M.PARAM_META["W"].pop("rule")  # E3 회귀: rule 창 없으면 강제 고정
try:
    v3f = {v["key"]: v for v in optimize_mna(Lw, iters=1, n=200)["variables"]}
    chk("S3 opt: rule 창 없으면 강제 고정 (E3, lockable=false)",
        v3f["W"]["frozen"] is True and v3f["W"]["lockable"] is False, str(v3f["W"]))
finally:
    M.PARAM_META["W"]["rule"] = _wr

# 14) max barrier 선택 (사용자 확정 2026-07-28): log(기본, margin 소모) | softplus(준-rule)
from server.opt_mna import _logbar  # noqa: E402

chk("logbar: 내부 미미·벽 발산·C¹ 선형 연장", abs(_logbar(5.0, 1.0, 10.0) - math.log(9.0 / 5.0)) < 1e-12
    and _logbar(9.99, 1.0, 10.0) > 6.0
    and abs(_logbar(10.0, 1.0, 10.0) - (-math.log(1e-3) + 1.0)) < 1e-9, "")
try:
    optimize_mna(Lw, iters=1, n=200, barrier="bogus")
    chk("barrier 검증: 미지 모양 거부", False, "예외 없음")
except ValueError:
    chk("barrier 검증: 미지 모양 거부", True, "")
r_log = optimize_mna(Lw, iters=14, n=200, freeze=("L",))
chk("log barrier(기본): W margin 소모 — limit(12) 부근까지", r_log["barrier"] == "log"
    and r_log["final"]["W"] > 10.5 and r_log["final"]["W"] < 12.0,
    "W={}".format(r_log["final"]["W"]))
r_sp = optimize_mna(Lw, iters=14, n=200, freeze=("L",), barrier="softplus")
chk("softplus 옵션: 준-rule 여유 유지 (log보다 안쪽)", r_sp["barrier"] == "softplus"
    and r_sp["final"]["W"] < r_log["final"]["W"] - 0.5,
    "W log={} sp={}".format(r_log["final"]["W"], r_sp["final"]["W"]))
from server.opt_mna import _wallq  # noqa: E402

chk("wallq 벽: 내부 힘 0·외부 이차 복원", _wallq(11.9, 1.0, 12.0) == 0.0
    and abs(_wallq(12.11, 1.0, 12.0) - 500.0 * (0.11 / 11.0) ** 2) < 1e-12, "")
r_w2 = optimize_mna(Lw, iters=20, freeze=("L", "x1", "x2"), mu_bar=0.002)
chk("log 벽(μb-독립): 초저 μb에도 창 이탈 금지 + margin 소모 (교정 회귀)",
    r_w2["final"]["W"] <= 12.0 and r_w2["final"]["W"] > 11.9,
    "W={}".format(r_w2["final"]["W"]))
chk("W 창 12: W 단독 소모로 HBM 1kV PASS", r_w2["final"]["soa_pass"] is True
    and r_w2["final"]["worst"] < 1.0, str(r_w2["final"]["worst"]))

# 13) S5 리허설 (이슈 #11 완료 기준): 새 파라미터는 정본 3곳(schematic 바인딩 +
#     PARAM_META + 물리식 등록)만으로 발견→supported→평가→optimizer 전 층 자동 — 배관 수정 0
from server.netlist import params_registry  # noqa: E402

M.PARAM_META["T"] = {"default": 2.0, "unit": "µm", "rule": (1.0, 4.0),
                     "label": "T (금속 두께)", "dec": 2, "cost_w": 0.0,
                     "freeze_default": True}
M.BINDING_FUNCS["rddt"] = lambda L, T: M.rdd_r(L) * 2.0 / float(T)
try:
    Lr = copy.deepcopy(DEFAULT_LAYOUT)
    for el in Lr["elements"]:
        if isinstance(el, dict) and str((el.get("params") or {}).get("R", "")).replace(" ", "") == "rdd(L,W)":
            el["params"]["R"] = "rddt(L,T)"
            break
    nlr = extract_netlist(Lr)
    regr = {r["name"]: r for r in params_registry(nlr)}
    chk("리허설: 새 기호 T 발견+supported+창 자동", "T" in regr
        and regr["T"]["supported"] is True and regr["T"]["rule_lo"] == 1.0
        and regr["T"]["freeze_default"] is True, str(regr.get("T")))
    rt2 = assemble_and_solve(nlr, inject="IO", ground="VSS", I=1.33, model_ctx=ctx)
    rt4 = assemble_and_solve(nlr, inject="IO", ground="VSS", I=1.33, model_ctx=ctx,
                             pset={"T": 4.0})
    chk("리허설: T=4 → 해당 금속 R 절반 → ΔV(IO)=1.33×0.25Ω",
        abs((rt2["v"]["IO"] - rt4["v"]["IO"]) - 1.33 * 0.25) < 0.03,
        str((rt2["v"]["IO"], rt4["v"]["IO"])))
    ro_t = optimize_mna(Lr, iters=1, n=200)
    vT = next(v for v in ro_t["variables"] if v["key"] == "T")
    chk("리허설: optimizer 변수에 T 자동 편입(창=META rule·잠금 가능)",
        vT["lo"] == 1.0 and vT["hi"] == 4.0 and vT["lockable"] is True, str(vT))
finally:
    del M.PARAM_META["T"]
    del M.BINDING_FUNCS["rddt"]

# 15) Feasibility optimizer S1/S2 (이슈 #12/#13): loss 분리·constraint 스키마·best 분리
from server.opt_feas import evaluate_candidate, optimize_feas  # noqa: E402

_win = {"x1": (0.64, 3.84), "x2": (1415.232, 2628.288), "W": (1.0, 12.0), "L": (70.0, 1400.0)}
_ispec = M.hbm_current(1.0)
ev0f = evaluate_candidate(nl, {"x1": 2.56, "x2": 1415.232, "L": 350.0, "W": 5.0},
                          "worst", "IO", "VSS", _ispec, 5e-12, windows=_win, n=500)
chk("S1 평가: 스키마(solver/constraints/losses/feasible/usages)",
    set(ev0f) >= {"solver", "constraints", "losses", "feasible", "usages"}
    and set(ev0f["losses"]) >= {"rule", "soa", "spec", "total", "constraint_total"}
    and {c["category"] for c in ev0f["constraints"]["soa"]} == {"soa"}, "")
chk("S1 평가: 초기 설계 — SOA만 FAIL (loss_rule=loss_spec=0)",
    ev0f["losses"]["soa"] > 0 and ev0f["losses"]["rule"] == 0.0
    and ev0f["losses"]["spec"] == 0.0 and ev0f["feasible"] is False, str(ev0f["losses"]))
evWf = evaluate_candidate(nl, {"x1": 2.56, "x2": 1415.232, "L": 350.0, "W": 12.0},
                          "worst", "IO", "VSS", _ispec, 5e-12, windows=_win, n=M.N)
chk("S1 평가: W=12 전 constraint PASS → 세 loss 0·feasible (cost·guard band 없음)",
    evWf["feasible"] is True and evWf["losses"]["total"] == 0.0, str(evWf["losses"]))
evRf = evaluate_candidate(nl, {"x1": 5.0, "x2": 1415.232, "L": 350.0, "W": 12.0},
                          "worst", "IO", "VSS", _ispec, 5e-12, windows=_win, n=500)
chk("S1 평가: rule 위반 검출 (x1>max → loss_rule>0·infeasible)",
    evRf["losses"]["rule"] > 0 and evRf["feasible"] is False,
    str(evRf["losses"]["rule"]))
try:
    optimize_feas(DEFAULT_LAYOUT, iters=1, barrier="bogus")
    chk("S2 opt: barrier 검증 거부", False, "예외 없음")
except ValueError:
    chk("S2 opt: barrier 검증 거부", True, "")
r_fs = optimize_feas(DEFAULT_LAYOUT, iters=25, freeze=("L", "x1", "x2"))
chk("S2 opt: W 단독·barrier off — status PASS·loss 0 (clamp 없이 창 내 feasible)",
    r_fs["status"] == "PASS" and r_fs["best_feasible"] is not None
    and r_fs["best_feasible"]["losses"]["total"] == 0.0
    and 11.5 < r_fs["best_feasible"]["W"] <= 12.0 + 1e-9,
    "W={} status={}".format(r_fs.get("best_feasible", {}).get("W"), r_fs["status"]))
chk("S2 opt: history에 loss 3종·feasibility·gradient·solver 기록",
    all(("losses" in h and "feasible" in h and "solver" in h) for h in r_fs["history"])
    and any(h.get("gradient") for h in r_fs["history"]), "")
r_stop = optimize_feas(DEFAULT_LAYOUT, iters=25, freeze=("L", "x1", "x2"),
                       stop_on_feasible=True)
chk("S2 opt: stop_on_feasible 옵션 — 조기 종료", r_stop["stopped_on_feasible"] is True
    and len(r_stop["history"]) < len(r_fs["history"]), str(len(r_stop["history"])))

# 16) S3~S5 (이슈 #13): adjoint gradient — central FD oracle 대조 (rel_err·부호)
from server.opt_feas import adjoint_gradient  # noqa: E402

_KEYS = ("x1", "x2", "W", "L")


def _jhat(ps, cap_lim=5e-12):
    ev = evaluate_candidate(nl, dict(ps), "worst", "IO", "VSS", _ispec, cap_lim,
                            windows=_win, n=500)
    return ev["losses"]["total"]


def _central(ps, p, h, cap_lim):
    pp, pm = dict(ps), dict(ps)
    pp[p] += h
    pm[p] -= h
    return (_jhat(pp, cap_lim) - _jhat(pm, cap_lim)) / (2 * h)


def _grad_check(tag, ps, cap_lim=5e-12, atol=1e-6, zero_tol=1e-9):
    """adjoint vs central FD (#14 §9): abs_err ≤ atol + rtol·max(|adj|,|fd|).
    step sweep(h, h/2)로 FD 안정성 판정 — 안정=1e-3(smooth), 불안정=1e-2(kink 인접).
    부호는 양쪽 다 |g|≤zero_tol이 아니면 일치 필수."""
    ev = evaluate_candidate(nl, dict(ps), "worst", "IO", "VSS", _ispec, cap_lim,
                            windows=_win, n=500, keep_aux=True)
    ga = adjoint_gradient(nl, dict(ps), ev, _KEYS, _win, (1.0, 1.0, 1.0), cap_lim,
                          corner="worst", n=500)
    ok, msgs = True, []
    for p in _KEYS:
        h0 = 5e-4 * max(1.0, abs(ps[p]))
        fd1 = _central(ps, p, h0, cap_lim)
        fd2 = _central(ps, p, h0 / 2, cap_lim)
        stable = abs(fd1 - fd2) <= atol + 1e-2 * max(abs(fd1), abs(fd2))
        # x1/x2는 실측 pwl 곡선 경로(hybrid 1단계 dI/dx — #13 4.2.D, analytic은 2단계
        # 후속)라 항상 kink 인접 취급 1e-2; W/L은 해석 스탬프 — smooth 1e-3
        rtol = 1e-2 if (p in ("x1", "x2") or not stable) else 1e-3
        g_fd = fd2
        abs_err = abs(ga[p] - g_fd)
        lim_err = atol + rtol * max(abs(ga[p]), abs(g_fd))
        sign_ok = (abs(g_fd) <= zero_tol and abs(ga[p]) <= zero_tol) \
            or (ga[p] * g_fd >= 0)
        if abs_err > lim_err or not sign_ok:
            ok = False
        msgs.append("{}: adj={:.5g} fd={:.5g} err={:.2g}/{:.2g}{}".format(
            p, ga[p], g_fd, abs_err, lim_err, "" if stable else "(kink)"))
    chk("S5 gradient check ({}): atol+rtol·부호".format(tag), ok, " | ".join(msgs))


_grad_check("SOA 활성 — 초기 설계", {"x1": 2.56, "x2": 1415.232, "L": 350.0, "W": 5.0})
_grad_check("rule 활성 — x1>max", {"x1": 4.2, "x2": 1415.232, "L": 350.0, "W": 11.5})
_grad_check("spec 활성 — capLim 0.4pF",
            {"x1": 2.56, "x2": 1415.232, "L": 350.0, "W": 5.0}, cap_lim=0.4e-12)
_grad_check("device I/V SOA 활성 — x1 축소", {"x1": 0.8, "x2": 1415.232, "L": 350.0, "W": 11.5})
_grad_check("rule 경계 바로 안 — 비활성", {"x1": 3.8399, "x2": 1415.232, "L": 350.0, "W": 5.0})
_grad_check("rule 경계 바로 밖 — 활성", {"x1": 3.8401, "x2": 1415.232, "L": 350.0, "W": 5.0})
_grad_check("rule+SOA+spec 동시 활성",
            {"x1": 4.2, "x2": 1415.232, "L": 350.0, "W": 5.0}, cap_lim=0.4e-12)
# 경계 kink 좌우 분리 (#14 §9.3): W=12(rule max 경계) — adjoint는 내부(좌측) 분지,
# 우측(위반) 분지는 양수 — one-sided behavior 명시 기록
ps_k = {"x1": 2.56, "x2": 1415.232, "L": 350.0, "W": 12.0}
ev_k = evaluate_candidate(nl, dict(ps_k), "worst", "IO", "VSS", _ispec, 5e-12,
                          windows=_win, n=500, keep_aux=True)
ga_k = adjoint_gradient(nl, dict(ps_k), ev_k, _KEYS, _win, (1.0, 1.0, 1.0), 5e-12,
                        corner="worst", n=500)
_hk = 6e-3
g_back = (_jhat(ps_k) - _jhat({**ps_k, "W": 12.0 - _hk})) / _hk
g_fwd = (_jhat({**ps_k, "W": 12.0 + _hk}) - _jhat(ps_k)) / _hk
chk("S5 kink: 경계에서 adjoint=좌측(내부) 미분, 우측 분지와 분리",
    abs(ga_k["W"] - g_back) <= 1e-6 + 1e-2 * abs(g_back) and g_fwd > g_back + 1e-6,
    "adj={:.3g} back={:.3g} fwd={:.3g}".format(ga_k["W"], g_back, g_fwd))
r_adj = optimize_feas(DEFAULT_LAYOUT, iters=25, freeze=("L", "x1", "x2"), grad="adjoint")
chk("S6 opt: adjoint(기본)로 W 단독 PASS — FD 경로와 동일 결말",
    r_adj["status"] == "PASS" and r_adj["grad"] == "adjoint"
    and 11.5 < r_adj["best_feasible"]["W"] <= 12.0 + 1e-9,
    "W={} status={}".format((r_adj.get("best_feasible") or {}).get("W"), r_adj["status"]))
chk("S6 opt: freeze 변수는 gradient에서 제외",
    all(set(h["gradient"]["total"]) == {"W"} for h in r_adj["history"]
        if h.get("gradient")), "")

# 17) 실행 자동 기록 (사용자 지시 2026-07-29): query+응답 아티팩트 저장 + run_file echo
from server.main import _save_opt_run, RUNS_DIR  # noqa: E402

_rr = _save_opt_run("feas", {"iters": "1"}, {"status": "PASS"})
_saved = os.path.join(os.path.dirname(os.path.dirname(RUNS_DIR)),
                      _rr.get("run_file", "").replace("/", os.sep))
chk("실행 기록: 파일 생성 + run_file echo", "run_file" in _rr
    and os.path.exists(_saved), str(_rr))
_js = json.load(open(_saved, encoding="utf-8"))
chk("실행 기록: query·응답 보존", _js["kind"] == "feas" and _js["query"] == {"iters": "1"}
    and _js["response"]["status"] == "PASS", "")
os.remove(_saved)  # 테스트 아티팩트는 남기지 않음

# 18) #14 S1 — 비수렴 candidate 정합성 (negative 먼저): J=0 오인 금지·상태 3분법·rollback
import server.opt_feas as OF  # noqa: E402

_orig_solve = OF.assemble_and_solve


def _fail_solve(tags=("+",), w_above=None):
    def fake(nl_, inject="IO", ground="VSS", I=1.33, **kw):
        sol = _orig_solve(nl_, inject=inject, ground=ground, I=I, **kw)
        tag = "+" if I >= 0 else "-"
        bad = tag in tags and (w_above is None
                               or (kw.get("pset") or {}).get("W", 5.0) > w_above)
        if bad:
            sol = dict(sol)
            sol["converged"] = False
        return sol
    return fake


try:
    OF.assemble_and_solve = _fail_solve(("+",))
    ev_p = OF.evaluate_candidate(nl, {"x1": 2.56, "x2": 1415.232, "L": 350.0, "W": 5.0},
                                 "worst", "IO", "VSS", _ispec, 5e-12, windows=_win, n=500)
    chk("#14 S1: +측만 비수렴 — J=0이어도 SOLVER_ERROR (infeasible 오인 금지)",
        ev_p["candidate_status"] == "SOLVER_ERROR" and ev_p["feasible"] is False
        and ev_p["losses"]["total"] == 0.0 and ev_p["solver_valid"] is False,
        str((ev_p["candidate_status"], ev_p["losses"])))
    OF.assemble_and_solve = _fail_solve(("-",))
    ev_m = OF.evaluate_candidate(nl, {"x1": 2.56, "x2": 1415.232, "L": 350.0, "W": 5.0},
                                 "worst", "IO", "VSS", _ispec, 5e-12, windows=_win, n=500)
    chk("#14 S1: −측만 비수렴도 SOLVER_ERROR", ev_m["candidate_status"] == "SOLVER_ERROR", "")
    OF.assemble_and_solve = _fail_solve(("+", "-"))
    r_se = OF.optimize_feas(DEFAULT_LAYOUT, iters=3, freeze=("L", "x1", "x2"))
    chk("#14 S1: VALID 전무 → status SOLVER_ERROR·best 3종 분리",
        r_se["status"] == "SOLVER_ERROR" and r_se["best_feasible"] is None
        and r_se["best_infeasible"] is None and r_se["best_solver_error"] is not None
        and r_se["final"] is None, str(r_se["status"]))
    # rollback: W>8에서만 비수렴 — trial 거부·절반 step으로 W≤8 유지, VALID만 best에
    OF.assemble_and_solve = _fail_solve(("+", "-"), w_above=8.0)
    r_rb = OF.optimize_feas(DEFAULT_LAYOUT, iters=8, freeze=("L", "x1", "x2"))
    chk("#14 S1: 비수렴 영역 rollback — z는 VALID에 머물고 INFEASIBLE 보고",
        r_rb["status"] == "INFEASIBLE" and r_rb["final"] is not None
        and r_rb["final"]["W"] <= 8.0 + 1e-9
        and all(h["candidate_status"] == "VALID" for h in r_rb["history"]
                if h["it"] > 0 and h is not r_rb["history"][-1]),
        "W={} status={}".format(r_rb["final"]["W"], r_rb["status"]))
finally:
    OF.assemble_and_solve = _orig_solve

# 19) IO cap contributor 일반화 (#15 §3, negative 먼저): 1..N contributor·silent 0 금지
from server.netlist import (validate_io_cap_contributors, io_cap_at_zero,  # noqa: E402
                            has_role, io_cap_contributors)


def _mutate_layout(fn):
    L2 = copy.deepcopy(DEFAULT_LAYOUT)
    for el in L2["elements"]:
        if isinstance(el, dict):
            fn(el)
    return extract_netlist(L2)


chk("#15 cap: 기본 2 contributor — up/down 합 500fF·명단·cell cap_model",
    validate_io_cap_contributors(nl)["count"] == 2
    and abs(io_cap_at_zero(nl) - 500e-15) < 1e-18
    and {c["instance"] for c in validate_io_cap_contributors(nl)["contributors"]}
    == {"XD_up", "XD_down"}, str(validate_io_cap_contributors(nl)))
nl_zero = _mutate_layout(lambda el: el.pop("roles", None))
chk("#15 cap: contributor 0개 — configuration error (silent 0 금지)",
    validate_io_cap_contributors(nl_zero)["valid"] is False, "")
try:
    io_cap_at_zero(nl_zero)
    chk("#15 cap: strict 기본 — 0개 시 예외", False, "예외 없음")
except ValueError:
    chk("#15 cap: strict 기본 — 0개 시 예외", True, "")
chk("#15 cap: strict=False 진단 경로", io_cap_at_zero(nl_zero, strict=False) == 0.0, "")
nl_one = _mutate_layout(lambda el: el.pop("roles", None)
                        if el.get("instance") == "XD_down" else None)
chk("#15 cap: contributor 1개 정상 (정확히 2 강제 금지)",
    validate_io_cap_contributors(nl_one)["count"] == 1
    and abs(io_cap_at_zero(nl_one) - 250e-15) < 1e-18, "")
nl_three = _mutate_layout(lambda el: el.update({"roles": ["io_cap_contributor"]})
                          if el.get("instance") == "XClamp" else None)
chk("#15 cap: contributor 3개 + 혼합 cap model(D1×2 + clamp D2) 합산",
    validate_io_cap_contributors(nl_three)["count"] == 3
    and abs(io_cap_at_zero(nl_three) - (500e-15 + 2.1e-12)) < 1e-16
    and {c["cap_model"] for c in
         validate_io_cap_contributors(nl_three)["contributors"]} == {"diode", "clamp"},
    str(io_cap_at_zero(nl_three)))
chk("#15 cap: 혼합 파라미터 바인딩 — clamp contributor는 x2, diode는 x1 의존",
    io_cap_at_zero(nl_three, pset={"x2": 2 * 1415.232})
    > io_cap_at_zero(nl_three) + 1e-13
    and abs(io_cap_at_zero(nl_three, pset={"x1": 5.12})
            - (1000e-15 + 2.1e-12)) < 1e-16, "")
nl_open = _mutate_layout(lambda el: el.update({"enabled": False})
                         if el.get("instance") == "XD_up" else None)
chk("#15 cap: contributor open 검출", any("open" in e
    for e in validate_io_cap_contributors(nl_open)["errors"]),
    str(validate_io_cap_contributors(nl_open)["errors"]))
nl_legacy = _mutate_layout(lambda el: el.update({"roles": None, "role": "io_primary_up"})
                           if el.get("instance") == "XD_up" else
                           (el.pop("roles", None)
                            if el.get("instance") == "XD_down" else None))
chk("#15 cap: 구 layout migration — 단일 role=io_primary_up도 contributor 인정",
    validate_io_cap_contributors(nl_legacy)["count"] == 1
    and has_role(io_cap_contributors(nl_legacy)[0], "io_primary_up"), "")
chk("#15 cap: up2/down2/b2b는 role 없으면 제외",
    all(c["instance"] in ("XD_up", "XD_down")
        for c in validate_io_cap_contributors(nl)["contributors"]), "")

# 20) #14 S3 — feasible_policy 명시 + best_it/final 일치
r_mm = r_adj  # 기본 policy=max_margin 실행 재사용 (§16)
chk("#14 S3: 기본 policy=max_margin — 완주·secondary 명시",
    r_mm["feasible_policy"] == "max_margin" and r_mm["secondary_objective_used"] is True
    and r_mm["secondary_score"] is not None and r_mm["stopped_on_feasible"] is False,
    str((r_mm["feasible_policy"], r_mm["secondary_score"])))
chk("#14 S3: best_it=final.source_it — history[best_it] pset과 final 일치",
    all(abs(r_mm["history"][r_mm["best_it"]][k] - r_mm["final"][k]) < 1e-9
        for k in ("x1", "x2", "W", "L")), str(r_mm["best_it"]))
r_first = optimize_feas(DEFAULT_LAYOUT, iters=25, freeze=("L", "x1", "x2"),
                        feasible_policy="first")
chk("#14 S3: first policy — 최초 feasible 보존 + 자동 조기 종료",
    r_first["feasible_policy"] == "first" and r_first["stopped_on_feasible"] is True
    and r_first["secondary_objective_used"] is False
    and r_first["status"] == "PASS"
    and len(r_first["history"]) <= len(r_mm["history"]), str(len(r_first["history"])))
chk("#14 S3: 두 policy 모두 PASS 판정 기준 동일(전 g≤0)",
    r_first["best_feasible"]["losses"]["total"] == 0.0
    and r_mm["best_feasible"]["losses"]["total"] == 0.0, "")
try:
    optimize_feas(DEFAULT_LAYOUT, iters=1, feasible_policy="bogus")
    chk("#14 S3: 미지 policy 거부", False, "예외 없음")
except ValueError:
    chk("#14 S3: 미지 policy 거부", True, "")

# 21) #14 S4 — 응답 의미론: pass 분해·barrier/objective 분리·API 검증
from server.main import _feas_input_error  # noqa: E402

ev_spec = evaluate_candidate(nl, {"x1": 2.56, "x2": 1415.232, "L": 350.0, "W": 12.0},
                             "worst", "IO", "VSS", _ispec, 0.4e-12, windows=_win, n=500)
chk("#14 S4: spec-only FAIL — pass 분해·soa_pass는 SOA만 의미",
    ev_spec["pass"]["spec"] is False and ev_spec["pass"]["soa"] is True
    and ev_spec["pass"]["rule"] is True and ev_spec["pass"]["all"] is False
    and ev_spec["feasible"] is False, str(ev_spec["pass"]))
chk("#14 S4: rule-only 위반의 pass 분해", evRf["pass"]["rule"] is False, "")
chk("#14 S4: losses에 constraint_total 별칭", evWf["losses"]["constraint_total"]
    == evWf["losses"]["total"], "")
r_bar = optimize_feas(DEFAULT_LAYOUT, iters=2, freeze=("L", "x1", "x2"), barrier="log")
h_bar = r_bar["history"][-1]
chk("#14 S4: barrier=log — objective=constraint+barrier·gradient 분리 기록",
    abs(h_bar["losses"]["objective"]
        - (h_bar["losses"]["constraint_total"] + h_bar["losses"]["barrier"])) < 2e-6
    and h_bar["losses"]["barrier"] > 0
    and set(h_bar["gradient"]) == {"constraint", "barrier", "total"},
    str(h_bar["losses"]))
h_off = r_adj["history"][-1]
chk("#14 S4: barrier=off — barrier loss 정확히 0", h_off["losses"]["barrier"] == 0.0
    and h_off["losses"]["objective"] == h_off["losses"]["constraint_total"], "")
for _args, _msg in (((0.0, 5.0, (1, 1, 1), 0.06, 0.01, 20.0, 30), "hbm 0"),
                    ((1.0, -1.0, (1, 1, 1), 0.06, 0.01, 20.0, 30), "capLim 음수"),
                    ((1.0, 5.0, (1, -1, 1), 0.06, 0.01, 20.0, 30), "alpha 음수"),
                    ((1.0, 5.0, (0, 0, 0), 0.06, 0.01, 20.0, 30), "alpha 전부 0"),
                    ((1.0, 5.0, (1, 1, 1), 0.0, 0.01, 20.0, 30), "lr 0"),
                    ((float("nan"), 5.0, (1, 1, 1), 0.06, 0.01, 20.0, 30), "NaN")):
    chk("#14 S4: 입력 검증 거부 — " + _msg, _feas_input_error(*_args) is not None, "")
chk("#14 S4: 정상 입력 통과", _feas_input_error(1.0, 5.0, (1, 1, 1), 0.06, 0.01, 20.0, 30)
    is None, "")

if fails:
    print("FAIL: netlist/matrix ({}건)".format(len(fails)))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS: schematic→netlist→MNA ({}건: net 추출·P0 semantics·검증 발견 회귀·해석·실측 연계)"
      .format(n_checks[0]))
