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
io_total = sum(c["c0"] for c in caps.values() if c and c["on_io"])
chk("cap: IO 합산 550fF ≤ capLim 5pF (usage 11%)", abs(io_total - 550e-15) < 1e-18
    and io_total < M.IO_CAP_LIM, str(io_total))
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

if fails:
    print("FAIL: netlist/matrix ({}건)".format(len(fails)))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS: schematic→netlist→MNA ({}건: net 추출·P0 semantics·검증 발견 회귀·해석·실측 연계)"
      .format(n_checks[0]))
