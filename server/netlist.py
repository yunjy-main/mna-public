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
                          "equation": e.get("equation"), "role": e.get("role"),
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
            "equation": r.get("equation"), "role": r.get("role"),
            "a": net(d["a"]), "b": net(d["b"]),
        })
    for f in fets:
        r = resolve(f)
        dn, sn, gn = net(f["drain"]), net(f["source"]), net(f["gate"])
        out_devices.append({
            "kind": f["kind"], "open": f["open"] or r.get("open", False),
            "instance": r.get("instance"), "cell": r.get("cell"),
            "model": r.get("model"), "params": r.get("params", {}),
            "equation": r.get("equation"), "role": r.get("role"),
            "drain": dn, "source": sn, "gate": gn,
            # 명시 terminal map (이슈 #10 §6) — bulk는 렌더러의 bulk→source 직결로 b=s
            "terminals": {"d": dn, "g": gn, "s": sn, "b": sn},
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


# ---------------- 실측 model 연계 (사용자 궁극 목표, 이슈 #9 P1) ----------------
# schematic instance의 cell이 실측 제공 model을 가지면 placeholder 대신
# calib 곡선(pos+neg branch 병합)의 piecewise-linear I(V)로 stamping한다.
#   d_up / d_down (esdvpnp/esdndsx) = Device1 — element 방향(anode a→cathode b)이
#     회로 배치를 이미 담으므로 곡선은 그대로 사용 (D2 결정 "down=미러"는 배치로 표현됨)
#   clamp (nfet_clamp) = Device2 — zener element가 a=하단(N3B)/b=상단(N3)이라
#     주 도통(트리거)이 element 좌표계 V<0 → 곡선 미러
#   d_b2b (essvpnp) = 실측 미제공 → placeholder softplus 유지

def _pwl_iv(Vs, Is):
    """병합 실측 곡선 → I(V) 구간선형 평가기 (양끝은 끝 기울기로 선형 외삽)."""
    def f(V):
        n = len(Vs)
        if V <= Vs[0]:
            g = (Is[1] - Is[0]) / ((Vs[1] - Vs[0]) or 1e-12)
            return Is[0] + g * (V - Vs[0]), g
        if V >= Vs[-1]:
            g = (Is[-1] - Is[-2]) / ((Vs[-1] - Vs[-2]) or 1e-12)
            return Is[-1] + g * (V - Vs[-1]), g
        lo, hi = 0, n - 1
        while hi - lo > 1:
            m = (lo + hi) // 2
            if Vs[m] <= V:
                lo = m
            else:
                hi = m
        g = (Is[hi] - Is[lo]) / ((Vs[hi] - Vs[lo]) or 1e-12)
        return Is[lo] + g * (V - Vs[lo]), g
    return f


def _mirror(f):
    def g(V):
        i, gg = f(-V)
        return -i, gg
    return g


def _size_of(dev, x1, x2):
    """instance params.size 해석 — "x1"/"x2"/"x1/10"/숫자. 기본: diode류=x1, clamp=x2.
    (secondary는 primary 면적 1/10 — 사용자 지시 2026-07-28)"""
    base = x2 if dev.get("cell") == "clamp" else x1
    s = (dev.get("params") or {}).get("size")
    if s is None:
        return base
    if isinstance(s, (int, float)):
        return float(s)
    expr = str(s).replace(" ", "")
    num = {"x1": x1, "x2": x2}.get(expr.split("/")[0])
    if num is None:
        return base
    if "/" in expr:
        try:
            return num / float(expr.split("/")[1])
        except ValueError:
            return num
    return num


def measured_context(x1=2.56, x2=1415.232, corner="worst"):
    """device record → 실측 I(V) 평가기 resolver. 곡선은 server.model calib에서 유도.

    cell→모델: d_up/d_down/d_b2b = Device1(esdvpnp 제공 diode model — b2b·down도 동일
    곡선, 사용자 지시 2026-07-28 — 방향은 element 배치가 표현), clamp = Device2 미러.
    size는 _size_of로 해석. (모델, size)별 곡선 캐시."""
    from server import model as M
    cache = {}

    def curve(dev, x, mirror=False):
        key = (dev["id"], round(float(x), 9), mirror)
        if key not in cache:
            c = M.calib(dev, x, corner)
            Vs = c["neg"]["V"][::-1] + c["pos"]["V"][1:]
            Is = c["neg"]["I"][::-1] + c["pos"]["I"][1:]
            f = _pwl_iv(Vs, Is)
            cache[key] = _mirror(f) if mirror else f
        return cache[key]

    def resolve(d):
        cell = d.get("cell")
        if cell in ("d_up", "d_down", "d_b2b"):
            return curve(M.D1, _size_of(d, x1, x2))
        if cell == "clamp":
            return curve(M.D2, _size_of(d, x1, x2), mirror=True)
        return None

    return resolve


def soa_endpoints(nl, x1=2.56, x2=1415.232, corner="worst"):
    """저항 제외 device별 실측 SOA endpoint {vp, ip, vn, inn, size} — **element 좌표계**.

    diode류=Device1·clamp=Device2를 해당 instance size로 평가. clamp는 곡선을
    미러해 stamping하므로(zener a=하단) endpoint도 뒤집어 표현한다: element 음(−)
    방향(주 도통)=Device2 pos branch 한계. 데이터 없는 소자=None."""
    from server import model as M
    out = {}
    for key, d in _device_keys(nl):
        cell = d.get("cell")
        x = _size_of(d, x1, x2)
        if cell in ("d_up", "d_down", "d_b2b"):
            e = M.ep(M.D1, x, corner)
            out[key] = {"vp": e["vp"], "ip": e["ip"], "vn": e["vn"], "inn": e["inn"], "size": x}
        elif cell == "clamp":
            e = M.ep(M.D2, x, corner)
            out[key] = {"vp": -e["vn"], "ip": -e["inn"], "vn": -e["vp"], "inn": -e["ip"], "size": x}
        else:
            out[key] = None
    return out


def assemble_and_solve(nl, inject="IO", ground="VSS", I=1.33, L=350.0,
                       max_iter=200, tol=1e-9, v0=None, model_ctx=None):
    """netlist → MNA 조립 + Newton. inject/ground는 net 이름.
    v0: unknowns 순서의 초기 전압 벡터 (continuation sweep warm-start용).
    model_ctx: measured_context() resolver — device별 실측 I(V). None이면 placeholder."""
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

    # 이슈 #10 §2: role=soa_monitor는 equation이 없는 관측 전용 —
    # residual/Jacobian에 0 기여 (placeholder 접합 diode도 적용하지 않음)
    stamped = [d for d in nl["devices"] if not d["open"] and d["kind"] != "sourcei"
               and d.get("role") != "soa_monitor"]

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
                meas = model_ctx(d) if model_ctx else None
                if d["kind"] == "resistor":
                    g = 1.0 / _res_R(d, L)
                    Idev = g * V
                elif meas is not None:  # 실측 곡선 (d_up/d_down/clamp)
                    Idev, g = meas(V)
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

    v = list(v0) if (v0 is not None and len(v0) == N) else [0.0] * N
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
        step = 1.0 if mx <= cap else cap / mx
        # residual backtracking: 구간선형(실측 pwl) kink에서의 진동 방지 —
        # 스텝 후 잔차가 늘면 반감 (부동 net 걷기는 잔차가 단조 감소라 무영향)
        vn = [vi + step * di for vi, di in zip(v, dv)]
        for _ in range(8):
            Fn = build(vn)[1]
            rn = max(abs(x) for x in Fn) if Fn else 0.0
            if rn <= res or step < 1e-6:
                break
            step *= 0.5
            vn = [vi + step * di for vi, di in zip(v, dv)]
        v = vn
        prev_res = res

    G, F = build(v)
    res = max(abs(x) for x in F) if F else 0.0
    vmap = {names[n]: v[idx[n]] for n in unknowns}
    for n in ref:
        if n in names:
            vmap[names[n]] = 0.0  # reference net — monitor 평가에 전 net 전압 필요
    return {
        "inject": inject, "ground": ground, "I": I, "L": L,
        "unknowns": [names[n] for n in unknowns],
        "ref_nets": sorted(names[n] for n in ref if n in names),
        "v": vmap,
        "G": G, "residual": res,
        "converged": res < 1e-6,
        "newton_iters": it,
        "size": "{0}×{0}".format(N),
        "nnz": sum(1 for row in G for x in row if abs(x) > 1e-12),
    }


# ---------------- SOA monitor (이슈 #10) ----------------
# role=soa_monitor 소자는 equation이 없어 행렬에 기여하지 않는다.
# solve 이후 terminal 전압만 관측해 signed min/max rule로 SOA를 평가한다.
# rule 수치는 코드 고정이 아니라 실측 데이터(server.victim_soa)에서 유도한다.

def soa_rules_for(model):
    """process model명("SG_NFET 1stk_1rx") → signed SOA rule 목록.

    victim_soa 실측 등가 변환: |VDS|≤Vfail ⇔ VDS∈[−Vfail,+Vfail];
    NFET u_inv = max(VGS,VGD,VGB,0)/Vinv < 1 ⇔ 각 항 ≤ +Vinv,
    u_acc ⇔ 각 항 ≥ −Vacc (PFET는 부호 반대)."""
    from server import victim_soa as VS
    try:
        dev_class, topology = model.split()
        vfail = VS.TERMINAL_VFAIL[dev_class][topology]
        ox = VS.OXIDE_LIMIT[dev_class]
    except (AttributeError, ValueError, KeyError):
        return []
    if ox["type"] == "nfet":
        gmin, gmax = -ox["accumulation"], ox["inversion"]
    else:
        gmin, gmax = -ox["inversion"], ox["accumulation"]
    return [
        {"quantity": "VDS", "min": -vfail, "max": vfail},
        {"quantity": "VGS", "min": gmin, "max": gmax},
        {"quantity": "VGD", "min": gmin, "max": gmax},
        {"quantity": "VGB", "min": gmin, "max": gmax},
    ]


def device_caps(nl, x1=2.56, x2=1415.232):
    """저항 제외 device별 capacitance spec — model.CAP의 size 스케일 평가.
    {c0: V=0 값[F], vbi, mj, fc, size} (frontend가 C(V)를 재현할 수 있게 계수 포함).
    diode류(d_up/d_down/d_b2b)=D1 cap, clamp=D2 cap, 그 외(전류원·monitor)=None.
    EM은 spec 제외(사용자 지시 2026-07-28)."""
    from server import model as M
    out = {}
    for key, d in device_keys(nl):
        cell = d.get("cell")
        dev = M.D1 if cell in ("d_up", "d_down", "d_b2b") else (M.D2 if cell == "clamp" else None)
        if dev is None:
            out[key] = None
            continue
        x = _size_of(d, x1, x2)
        p = M.CAP[dev["id"]]
        out[key] = {"c0": M.cap_of(dev, x, 0.0), "vbi": p["vbi"], "mj": p["mj"],
                    "fc": p["fc"], "size": x}
    return out


def device_curves(nl, x1=2.56, x2=1415.232, corner="worst", npts=41):
    """저항 제외 device별 실측 특성곡선 {V,I} — I-V 차트의 참조선(궤적 vs 특성 대비).
    element 좌표계(clamp는 미러). 실측 데이터 없는 소자=None. (모델,size)별 캐시."""
    from server import model as M
    cache = {}
    out = {}
    for key, d in device_keys(nl):
        cell = d.get("cell")
        if cell in ("d_up", "d_down", "d_b2b"):
            dev, mirror = M.D1, False
        elif cell == "clamp":
            dev, mirror = M.D2, True
        else:
            out[key] = None
            continue
        x = _size_of(d, x1, x2)
        ck = (dev["id"], round(x, 9), mirror)
        if ck not in cache:
            c = M.calib(dev, x, corner)
            Vs = c["neg"]["V"][::-1] + c["pos"]["V"][1:]
            Is = c["neg"]["I"][::-1] + c["pos"]["I"][1:]
            if mirror:
                Vs = [-v for v in reversed(Vs)]
                Is = [-i for i in reversed(Is)]
            step = max(1, len(Vs) // npts)
            keep = list(range(0, len(Vs), step))
            if keep[-1] != len(Vs) - 1:
                keep.append(len(Vs) - 1)
            cache[ck] = {"V": [round(Vs[j], 4) for j in keep],
                         "I": [round(Is[j], 5) for j in keep]}
        out[key] = cache[ck]
    return out


def evaluate_soa_monitors(nl, sol, rules_by_model=None):
    """solve 이후 post-processing (이슈 #10 §3·§4).

    terminal 유효성: active(stamped) 소자 그래프에서 reference와 같은 연결성분에
    속해야 해석 가능. GMIN만으로 결정된 전압(부동 net)은 SOA 평가에 쓰지 않는다.
    solver 비수렴이면 전 monitor를 solver_non_convergence로 무효 처리."""
    names = nl["nets"]
    name_to_net = {v: k for k, v in names.items()}
    ref_ids = set(name_to_net[nm] for nm in sol.get("ref_nets", []) if nm in name_to_net)

    # active 소자(비 open·비 monitor·비 전류원) pin으로 net 연결성분 구성
    uf = _UF()
    SENTINEL = ("ref",)
    for n in ref_ids:
        uf.union(n, SENTINEL)
    for d in nl["devices"]:
        if d["open"] or d.get("role") == "soa_monitor" or d["kind"] == "sourcei":
            continue
        if d["kind"] in ("pfet", "nfet"):
            uf.union(d["drain"], d["source"])  # placeholder 접합 diode의 stamp 경로
        else:
            uf.union(d["a"], d["b"])

    def resolved(net_id):
        return net_id in ref_ids or uf.find(net_id) == uf.find(SENTINEL)

    out = []
    for d in nl["devices"]:
        if d.get("role") != "soa_monitor" or d["open"]:
            continue
        term_nets = d.get("terminals") or {}
        terminals = {}
        unresolved = []
        for tname, nid in term_nets.items():
            nm = names.get(nid, "n{}".format(nid))
            ok = resolved(nid)
            terminals[tname] = {"net": nm,
                                "voltage": sol["v"].get(nm) if ok else None}
            if not ok:
                unresolved.append({"terminal": tname, "net": nm})
        res = {"instance": d.get("instance"), "role": "soa_monitor",
               "model": d.get("model"), "terminals": terminals,
               "valid": True, "reason": None, "unresolved_terminals": unresolved,
               "stress": None, "checks": [], "passed": None,
               "worst_quantity": None, "worst_margin": None}
        if not sol.get("converged"):
            res["valid"] = False
            res["reason"] = "solver_non_convergence"
            out.append(res)
            continue
        if unresolved:
            res["valid"] = False
            res["reason"] = "unresolved_monitor_terminal"
            out.append(res)
            continue
        vd = terminals["d"]["voltage"]
        vg = terminals["g"]["voltage"]
        vs = terminals["s"]["voltage"]
        vb = terminals["b"]["voltage"]
        stress = {"VGS": vg - vs, "VGD": vg - vd, "VDS": vd - vs,
                  "VGB": vg - vb, "VDB": vd - vb, "VSB": vs - vb}
        res["stress"] = stress
        rules = (rules_by_model or {}).get(d.get("model"))
        if rules is None:
            rules = soa_rules_for(d.get("model") or "")
        checks = []
        for r in rules:
            val = stress[r["quantity"]]
            margin = min(val - r["min"], r["max"] - val)  # fail이면 음수
            checks.append({"quantity": r["quantity"], "value": val,
                           "min": r["min"], "max": r["max"],
                           "margin": margin, "passed": margin >= 0.0})
        res["checks"] = checks
        if checks:
            worst = min(checks, key=lambda c: c["margin"])
            res["passed"] = all(c["passed"] for c in checks)
            res["worst_quantity"] = worst["quantity"]
            res["worst_margin"] = worst["margin"]
        out.append(res)
    return out


# Top Cell rail {VDD, IO, VSS}의 ordered force/ground 6종 (이슈 #10 §5)
RAIL_SCENARIOS = [("IO", "VSS"), ("VSS", "IO"), ("IO", "VDD"),
                  ("VDD", "IO"), ("VDD", "VSS"), ("VSS", "VDD")]


def device_keys(nl):
    """저항 제외 device의 (표시 key, record) 목록 — 시각화의 단일 소자 원천.
    동일 instance 복수 소자(b2b 쌍)는 #k 접미. device_v/device_i/soa_endpoints/
    frontend 소자 리스트가 전부 이 키를 공유한다."""
    out = []
    seen = {}
    for d in nl["devices"]:
        if d["kind"] == "resistor" or d["open"]:
            continue
        key = d.get("instance") or d["kind"]
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = "{}#{}".format(key, seen[key])
        out.append((key, d))
    return out


def _device_keys(nl):
    return device_keys(nl)


def device_voltages(nl, sol):
    """저항을 제외한 모든 device의 양단 전압 (사용자 요구: 동적 그래프 원천).
    monitor FET은 VDS(상세 stress는 monitors에)."""
    names = nl["nets"]
    v = sol["v"]
    out = {}
    for key, d in device_keys(nl):
        if d["kind"] in ("pfet", "nfet"):
            out[key] = v[names[d["drain"]]] - v[names[d["source"]]]
        else:
            out[key] = v[names[d["a"]]] - v[names[d["b"]]]
    return out


def device_currents(nl, sol, model_ctx=None):
    """저항 제외 device의 분기 전류 — diode/zener는 stamping과 동일한 평가기의 I(V).
    monitor(무방정식)·전류원(시나리오 강제)은 None (임의 계산 금지, 이슈 #10)."""
    names = nl["nets"]
    v = sol["v"]
    out = {}
    for key, d in device_keys(nl):
        if d["kind"] in ("diode", "zener") and d.get("role") != "soa_monitor":
            V = v[names[d["a"]]] - v[names[d["b"]]]
            meas = model_ctx(d) if model_ctx else None
            if meas is not None:
                out[key] = meas(V)[0]
            elif d["kind"] == "zener":
                out[key] = _clamp_iv(V)[0]
            else:
                out[key] = _diode_iv(V)[0]
        else:
            out[key] = None
    return out


def sweep_scenario(nl, force, ground, imax=2.0, n=21, L=350.0, model_ctx=None, imin=0.0):
    """I=imin→imax continuation sweep + 매 point SOA 평가 (points는 I 오름차순).

    imin<0(양극 sweep, 사용자 지시 2026-07-28)이면 0에서 바깥쪽으로 양/음 두 갈래
    warm-start 후 병합 — 극성 반전점에서의 cold start를 피한다.
    point 상태 4종: non_convergence / unresolved_monitor_terminal / soa_fail / pass.
    SOA fail은 solve 실패가 아니다 — 해는 유효하게 저장하고 metadata만 기록."""
    grid = [imin + (imax - imin) * k / float(n - 1) if n > 1 else imax for k in range(n)]

    def solve_point(i, v0):
        sol = assemble_and_solve(nl, inject=force, ground=ground, I=i, L=L, v0=v0,
                                 model_ctx=model_ctx)
        mons = evaluate_soa_monitors(nl, sol)
        if not sol["converged"]:
            status = "non_convergence"
        elif any(m["reason"] == "unresolved_monitor_terminal" for m in mons):
            status = "unresolved_monitor_terminal"
        elif any(m["valid"] and m["passed"] is False for m in mons):
            status = "soa_fail"
        else:
            status = "pass"
        point = {"I": i, "status": status, "converged": sol["converged"],
                 "residual": sol["residual"], "v": sol["v"],
                 "device_v": device_voltages(nl, sol),
                 "device_i": device_currents(nl, sol, model_ctx=model_ctx),
                 "monitors": [{"instance": m["instance"], "valid": m["valid"],
                               "reason": m["reason"], "passed": m["passed"],
                               "stress": m["stress"],
                               "worst_quantity": m["worst_quantity"],
                               "worst_margin": m["worst_margin"]} for m in mons]}
        return point, sol, mons

    def branch(currents):  # 0 근처→바깥 순서로 continuation, (points, first_fail, last_conv)
        pts, v0, ff, lc = [], None, None, None
        for i in currents:
            p, sol, mons = solve_point(i, v0)
            if sol["converged"]:
                v0 = [sol["v"][nm] for nm in sol["unknowns"]]
                lc = {"current": i, "newton_iters": sol["newton_iters"]}
            if p["status"] == "soa_fail" and ff is None:
                fm = [m for m in mons if m["valid"] and m["passed"] is False][0]
                ff = {"current": i, "instance": fm["instance"],
                      "quantity": fm["worst_quantity"], "margin": fm["worst_margin"]}
            pts.append(p)
        return pts, ff, lc

    pos = [g for g in grid if g >= 0.0]
    neg = sorted([g for g in grid if g < 0.0], reverse=True)  # 0에 가까운 쪽부터
    pos_pts, ff_pos, lc_pos = branch(pos)
    neg_pts, ff_neg, lc_neg = branch(neg)
    points = list(reversed(neg_pts)) + pos_pts  # I 오름차순

    lim = lambda ff: "{}:{}".format(ff["instance"], ff["quantity"]) if ff else None
    return {"force": force, "ground": ground, "imax": imax, "imin": imin, "n": len(points),
            "points": points,
            "first_soa_fail": ff_pos, "first_soa_fail_neg": ff_neg,
            "last_converged": lc_pos, "last_converged_neg": lc_neg,
            "active_limiter": lim(ff_pos), "active_limiter_neg": lim(ff_neg)}
