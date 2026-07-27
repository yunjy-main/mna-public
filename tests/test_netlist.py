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

# 1b) 이슈 #9 P0 semantics
chk("이름 충돌 없음", nl["name_conflicts"] == [], str(nl["name_conflicts"]))
chk("global ground 없음(현 회로도)", nl["global_ground_nets"] == [], str(nl["global_ground_nets"]))
chk("local ground 4개(전류원 리턴)", len(nl["local_ground_nets"]) == 4,
    str([names[g] for g in nl["local_ground_nets"]]))

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
chk("전 소자 instance 귀속(23)", len(nl["devices"]) == 23
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

# (b) 구형 layout(symbol_scale 없음, scale=1.0)에서도 victim gate tie 접속 유지
L8 = copy.deepcopy(DEFAULT_LAYOUT)
del L8["symbol_scale"]
nl8 = extract_netlist(L8)
vic8 = sorted((d["kind"], nl8["nets"][d["gate"]]) for d in nl8["devices"]
              if d["kind"] in ("pfet", "nfet"))
chk("scale=1.0에서 gate tie=IN 유지", vic8 == [("nfet", "IN"), ("pfet", "IN")], str(vic8))
chk("scale=1.0 net 수 불변", len(nl8["nets"]) == len(names), str(len(nl8["nets"])))

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
# local ground는 reference가 아니므로 그 net 주입은 허용되어야 함
lg0 = nl["nets"][nl["local_ground_nets"][0]]
chk("local ground net 주입 허용", assemble_and_solve(nl, inject=lg0, ground="VSS", I=0.1)["converged"],
    lg0)

if fails:
    print("FAIL: netlist/matrix ({}건)".format(len(fails)))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS: schematic→netlist→MNA ({}건 — net 추출·P0 semantics·검증 발견 회귀·해석)"
      .format(n_checks[0]))
