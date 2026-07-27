# -*- coding: utf-8 -*-
"""Schematic → netlist → MNA 행렬 자동 변환.

원천은 schematic.DEFAULT_LAYOUT 하나다: 선(line)·소자 endpoints·FET anchor의
기하 연결성에서 net을 추출하고(축정렬 세그먼트 + 등록점 union-find),
instance 상자(cell/model/params)와 소자를 포함 관계로 결합해 netlist를 만든 뒤
MNA(G·v=J, Newton)로 조립·해석한다.

model equation은 임의 placeholder(사용자 허용 2026-07-27):
  diode/b2b/FET접합 = softplus 다이오드, clamp = 양방향 softplus(트리거 4V),
  R = 선형(params.R 또는 rdd(L)). 크기 파라미터(x1/x2)는 아직 미반영.

enabled=False 소자는 stamping 제외(배선은 유지) — 색상은 표시 전용(P0-3).
net 이름은 layout nodes/port "net" 선언에서 온다(P0-4). reference는 scenario.ground +
global=True ground만(P0-2). 전류원은 G에 기여하지 않으므로 시나리오는
(inject net, ground net, I)로 지정한다. 소자→instance 귀속은 명시 instance_id가
권위이고 기하는 교차 검증(P0-6, assoc_conflicts). FET pin 기하는 렌더러와 공유하는
schematic.fet_anchors가 원천(P0-5). — 이슈 #9 P0 반영
"""
import math

from server.schematic import fet_anchors  # P0-5: 렌더러와 동일 기하 원천 (schemdraw)

TOL = 0.02
GMIN = 1e-9

# net 이름 원천 (P0-4, 이슈 #9): 좌표 하드코딩 금지 —
#   port element의 "net" 키 + layout "nodes" 선언(이름→xy)이 semantic 이름을 준다.
#   같은 component에 서로 다른 이름이 들어오면 name_conflicts로 보고.


def _k(p):
    return (round(p[0], 3), round(p[1], 3))


def _on_seg(p, a, b):
    """축정렬 세그먼트 a-b 위(끝점 포함)에 p가 있는가."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs(ax - bx) < TOL:  # 수직
        return abs(px - ax) < TOL and min(ay, by) - TOL <= py <= max(ay, by) + TOL
    if abs(ay - by) < TOL:  # 수평
        return abs(py - ay) < TOL and min(ax, bx) - TOL <= px <= max(ax, bx) + TOL
    return False


class _UF(dict):
    def find(self, x):
        while self.setdefault(x, x) != x:
            self[x] = self[self[x]]
            x = self[x]
        return x

    def union(self, a, b):
        self[self.find(a)] = self.find(b)


def extract_netlist(layout):
    """layout dict → {nets, devices, grounds}. 연결 규칙:
    - 등록점(배선/소자 endpoints·dot·ground)이 어떤 배선 세그먼트 위에 있으면 그 net에 합류
      (등록점 없는 배선 교차는 미연결 — 표준 schematic 규약)."""
    nodes = layout.get("nodes", {})

    def pt(ref):
        if isinstance(ref, str):
            return tuple(nodes[ref]["xy"])
        return tuple(ref)

    wires, devices, grounds, rects, fets = [], [], [], [], []
    symbol_scale = layout.get("symbol_scale", 1.0)
    tie_ys = []        # gates tie 접점의 y (렌더러가 dot을 찍는 위치 — 추출기도 등록점으로)
    name_anchors = []  # (좌표, 이름) — port "net" + nodes 선언
    for nm, nd in nodes.items():
        name_anchors.append((tuple(nd["xy"]), nm))
    for e in layout.get("elements", []):
        t = e.get("type")
        if t == "port" and e.get("net"):
            name_anchors.append((pt(e["at"]), e["net"]))
        if t == "line":
            wires.append((pt(e["from"]), pt(e["to"])))
        elif t == "rect" and e.get("instance"):
            (x1, y1), (x2, y2) = e["corner1"], e["corner2"]
            rects.append({"instance": e["instance"], "cell": e.get("cell"),
                          "model": e.get("model"), "params": e.get("params", {}),
                          "variant": e.get("variant"),
                          "bb": (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)),
                          "open": e.get("enabled") is False})  # P0-3: 색이 아니라 enabled가 semantics
        elif t in ("resistor", "diode", "zener", "sourcei"):
            a, b = pt(e["from"]), pt(e["to"])
            devices.append({"kind": t, "a": a, "b": b,
                            "mid": ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0),
                            "open": e.get("enabled") is False,
                            "instance_id": e.get("instance_id")})
        elif t == "ground":
            # global=True인 ground만 항상 reference; 나머지는 cell 내부 local return (P0-2)
            grounds.append({"at": pt(e["at"]), "global": bool(e.get("global"))})
        elif t in ("pfet", "nfet"):
            # P0-5: 렌더러와 공유하는 fet_anchors — rot/flip/scale 어떤 조합도 동일 기하
            anc = fet_anchors(t, pt(e["drain"]), rot=e.get("rot", 0),
                              flip=bool(e.get("flip")), scale=symbol_scale)
            d, src, gate = anc["drain"], anc["source"], anc["gate"]
            fets.append({"kind": t, "drain": d, "source": src, "gate": gate,
                         "mid": ((d[0] + gate[0]) / 2.0, d[1]), "open": e.get("enabled") is False,
                         "instance_id": e.get("instance_id")})
            if "rail_y" in e:
                wires.append((src, (src[0], e["rail_y"])))
        elif t == "gates":
            tie = e.get("tie")
            if tie and tie in nodes:
                tie_ys.append(nodes[tie]["xy"][1])
    # gates: 같은 drain의 pfet/nfet 쌍 → gate-gate 수직 배선.
    # tie 접점은 렌더러가 (gate.x, tie_y)에 dot을 찍는 것과 동일하게 등록점으로 추가
    # (scale에 따라 gate.x가 움직여도 tie 배선과의 접속이 유지된다 — 2026-07-28 수정)
    tie_pts = []
    for i, f1 in enumerate(fets):
        for f2 in fets[i + 1:]:
            if f1["kind"] != f2["kind"] and _k(f1["drain"]) == _k(f2["drain"]):
                wires.append((f1["gate"], f2["gate"]))
                for ty in tie_ys:
                    tie_pts.append((f1["gate"][0], ty))
    # bulk = source (렌더러의 bulk→source 직결) — 별도 net 불필요

    # 등록점: 모든 배선 끝점 + 소자 pin + ground + dot + gates tie 접점
    pts = set()
    for p in tie_pts:
        pts.add(_k(p))
    for a, b in wires:
        pts.add(_k(a)); pts.add(_k(b))
    for d in devices:
        pts.add(_k(d["a"])); pts.add(_k(d["b"]))
    for f in fets:
        pts.add(_k(f["drain"])); pts.add(_k(f["source"])); pts.add(_k(f["gate"]))
    for g in grounds:
        pts.add(_k(g["at"]))
    for e in layout.get("elements", []):
        if e.get("type") == "dot":
            pts.add(_k(pt(e["at"])))

    uf = _UF()
    for a, b in wires:
        ka, kb = _k(a), _k(b)
        uf.union(ka, kb)
        for p in pts:
            if _on_seg(p, ka, kb):
                uf.union(p, ka)

    # net id 부여 + 이름
    roots = {}
    for p in pts:
        roots.setdefault(uf.find(p), []).append(p)
    net_of = {}
    net_names = {}
    name_conflicts = []

    def _find_root(coord):
        kc = _k(coord)
        if kc in uf:
            return uf.find(kc)
        for a, b in wires:
            if _on_seg(kc, _k(a), _k(b)):
                return uf.find(_k(a))
        return None

    root_names = {}
    for coord, nm in name_anchors:
        rt = _find_root(coord)
        if rt is None:
            continue  # 미부착 anchor (annotation 전용 좌표 등)
        root_names.setdefault(rt, [])
        if nm not in root_names[rt]:
            root_names[rt].append(nm)
    for i, (root, members) in enumerate(sorted(roots.items())):
        for p in members:
            net_of[p] = i
        nms = root_names.get(uf.find(root), [])
        if len(nms) > 1:
            name_conflicts.append("net {}: 이름 충돌 {}".format(i, nms))
        net_names[i] = nms[0] if nms else "n{}".format(i)

    def net(p):
        kp = _k(p)
        if kp in net_of:
            return net_of[kp]
        for a, b in wires:  # 미등록점이 세그먼트 위인 경우
            if _on_seg(kp, _k(a), _k(b)):
                return net_of[_k(a)]
        net_of[kp] = len(roots) + len(net_of)  # 고립점
        return net_of[kp]

    def owner(mid):
        for r in rects:
            xa, ya, xb, yb = r["bb"]
            if xa - 0.05 <= mid[0] <= xb + 0.05 and ya - 0.05 <= mid[1] <= yb + 0.05:
                return r
        return None

    def _contains(r, mid):
        xa, ya, xb, yb = r["bb"]
        return xa - 0.05 <= mid[0] <= xb + 0.05 and ya - 0.05 <= mid[1] <= yb + 0.05

    def _fmt(mid):
        return "({:g}, {:g})".format(round(mid[0], 3), round(mid[1], 3))

    # P0-6 (이슈 #9): 소자→instance 귀속은 명시 instance_id가 권위,
    # 기하는 교차 검증 — **자기 상자 포함 여부**로 판단(상자 겹침에 무관).
    # instance 중복 정의는 첫 정의 우선 + 충돌 보고 (2026-07-28 확정).
    assoc_conflicts = []
    rect_by_name = {}
    for r in rects:
        if r["instance"] in rect_by_name:
            assoc_conflicts.append("instance 중복 정의: {} (첫 정의 우선)".format(r["instance"]))
            continue
        rect_by_name[r["instance"]] = r

    def resolve(dev):
        iid = dev.get("instance_id")
        if not iid:
            return owner(dev["mid"]) or {}
        r = rect_by_name.get(iid)
        if r is None:
            assoc_conflicts.append("{} @{}: instance_id '{}' 미정의 (기하 귀속 사용)"
                                   .format(dev["kind"], _fmt(dev["mid"]), iid))
            return owner(dev["mid"]) or {}
        if not _contains(r, dev["mid"]):
            geo = owner(dev["mid"])
            if geo is None:
                assoc_conflicts.append("{} @{}: instance_id '{}'이나 상자 밖"
                                       .format(dev["kind"], _fmt(dev["mid"]), iid))
            else:
                assoc_conflicts.append("{} @{}: instance_id '{}' vs 기하 '{}'"
                                       .format(dev["kind"], _fmt(dev["mid"]), iid,
                                               geo["instance"]))
        return r

    out_devices = []
    for d in devices:
        r = resolve(d)
        out_devices.append({
            "kind": d["kind"], "open": d["open"] or r.get("open", False),
            "instance": r.get("instance"), "cell": r.get("cell"),
            "model": r.get("model"), "params": r.get("params", {}),
            "a": net(d["a"]), "b": net(d["b"]),
        })
    for f in fets:
        r = resolve(f)
        out_devices.append({
            "kind": f["kind"], "open": f["open"] or r.get("open", False),
            "instance": r.get("instance"), "cell": r.get("cell"),
            "model": r.get("model"), "params": r.get("params", {}),
            "drain": net(f["drain"]), "source": net(f["source"]), "gate": net(f["gate"]),
        })

    global_grounds = sorted(set(net(g["at"]) for g in grounds if g["global"]))
    local_grounds = sorted(set(net(g["at"]) for g in grounds if not g["global"]))
    return {"nets": net_names, "devices": out_devices,
            "global_ground_nets": global_grounds, "local_ground_nets": local_grounds,
            "name_conflicts": name_conflicts, "assoc_conflicts": assoc_conflicts,
            "n_points": len(pts), "n_wires": len(wires)}


# ---------------- 임의(placeholder) model equations ----------------

def _sp(z):
    return z if z > 30 else (math.exp(z) if z < -30 else math.log1p(math.exp(z)))


def _sg(z):
    return 1.0 if z > 30 else (math.exp(z) if z < -30 else 1.0 / (1.0 + math.exp(-z)))


def _diode_iv(V, Gon=10.0, Von=0.7, Vt=0.05):
    """softplus diode: I=Gon·Vt·softplus((V−Von)/Vt) — Newton-안정(선형 점근)."""
    return Gon * Vt * _sp((V - Von) / Vt), Gon * _sg((V - Von) / Vt)


def _clamp_iv(V, Gon=10.0, Von=0.7, Vtrig=4.0, Vt=0.05):
    """양방향: 순방향(anode→cathode) 0.7V, 역방향 트리거 4V (nfet_clamp placeholder)."""
    i1, g1 = _diode_iv(V, Gon, Von, Vt)
    i2, g2 = _diode_iv(-V, Gon, Vtrig, Vt)
    return i1 - i2, g1 + g2


def _res_R(dev, L):
    prm = dev.get("params", {})
    R = prm.get("R", 1.0)
    if isinstance(R, str):  # "rdd(L)"
        return 0.5 * float(L) / 350.0
    return float(R)


def assemble_and_solve(nl, inject="IO", ground="VSS", I=1.33, L=350.0,
                       max_iter=200, tol=1e-9):
    """netlist → MNA 조립 + Newton. inject/ground는 net 이름."""
    names = nl["nets"]
    name_to_net = {v: k for k, v in names.items()}
    if inject not in name_to_net or ground not in name_to_net:
        raise ValueError("unknown net: inject={} ground={}".format(inject, ground))
    if inject == ground:
        raise ValueError("inject와 ground가 같은 net입니다: {}".format(inject))

    # P0-2 (이슈 #9): scenario.ground만 유일 강제 + 명시적 global ground.
    # cell 내부 local ground는 return 단자 표현 — 자동 reference 아님.
    ref = set(nl.get("global_ground_nets", []))
    ref.add(name_to_net[ground])
    if name_to_net[inject] in ref:
        raise ValueError("inject net {}이 reference에 속합니다".format(inject))
    unknowns = sorted(n for n in names if n not in ref)
    idx = {n: i for i, n in enumerate(unknowns)}
    N = len(unknowns)

    stamped = [d for d in nl["devices"] if not d["open"] and d["kind"] != "sourcei"]

    def vof(n, v):
        return 0.0 if n in ref else v[idx[n]]

    def build(v):
        G = [[0.0] * N for _ in range(N)]
        F = [0.0] * N
        for i, n in enumerate(unknowns):
            G[i][i] += GMIN
            F[i] += GMIN * v[i]
        inj = name_to_net[inject]
        if inj not in ref:
            F[idx[inj]] -= I
        for d in stamped:
            if d["kind"] in ("resistor", "diode", "zener"):
                a, b = d["a"], d["b"]
                V = vof(a, v) - vof(b, v)
                if d["kind"] == "resistor":
                    g = 1.0 / _res_R(d, L)
                    Idev = g * V
                elif d["kind"] == "zener":
                    Idev, g = _clamp_iv(V)
                else:
                    Idev, g = _diode_iv(V)
                for n, s in ((a, 1.0), (b, -1.0)):
                    if n in ref:
                        continue
                    F[idx[n]] += s * Idev
                    for m, s2 in ((a, 1.0), (b, -1.0)):
                        if m not in ref:
                            G[idx[n]][idx[m]] += s * s2 * g
            elif d["kind"] in ("pfet", "nfet"):
                # 접합 다이오드(placeholder): PMOS drain→bulk(=source), NMOS bulk(=source)→drain
                a, b = (d["drain"], d["source"]) if d["kind"] == "pfet" else (d["source"], d["drain"])
                V = vof(a, v) - vof(b, v)
                Idev, g = _diode_iv(V)
                for n, s in ((a, 1.0), (b, -1.0)):
                    if n in ref:
                        continue
                    F[idx[n]] += s * Idev
                    for m, s2 in ((a, 1.0), (b, -1.0)):
                        if m not in ref:
                            G[idx[n]][idx[m]] += s * s2 * g
        return G, F

    def solve_lin(A, rhs):
        n = len(rhs)
        M = [row[:] + [rhs[i]] for i, row in enumerate(A)]
        for c in range(n):
            p = max(range(c, n), key=lambda r: abs(M[r][c]))
            M[c], M[p] = M[p], M[c]
            piv = M[c][c]
            for r in range(n):
                if r != c and M[r][c] != 0.0:
                    f = M[r][c] / piv
                    for j in range(c, n + 1):
                        M[r][j] -= f * M[c][j]
        return [M[i][n] / M[i][i] for i in range(n)]

    v = [0.0] * N
    it, res, prev_res = 0, float("inf"), float("inf")
    cap = 1.0  # 적응형 step 제한: 걸린 채 residual이 안 줄면 확대 (부동 net 고전압 해 수렴)
    for it in range(1, max_iter + 1):
        G, F = build(v)
        res = max(abs(x) for x in F) if F else 0.0
        if res < tol:
            break
        dv = solve_lin(G, [-x for x in F])
        mx = max(abs(x) for x in dv) if dv else 0.0
        capped = mx > cap
        if capped and res >= 0.9 * prev_res:
            cap *= 4.0
        damp = 1.0 if mx <= cap else cap / mx
        v = [vi + damp * di for vi, di in zip(v, dv)]
        prev_res = res

    G, F = build(v)
    res = max(abs(x) for x in F) if F else 0.0
    return {
        "inject": inject, "ground": ground, "I": I, "L": L,
        "unknowns": [names[n] for n in unknowns],
        "ref_nets": sorted(names[n] for n in ref if n in names),
        "v": {names[n]: v[idx[n]] for n in unknowns},
        "G": G, "residual": res,
        "converged": res < 1e-6,
        "newton_iters": it,
        "size": "{0}×{0}".format(N),
        "nnz": sum(1 for row in G for x in row if abs(x) > 1e-12),
    }
