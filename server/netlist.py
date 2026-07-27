# -*- coding: utf-8 -*-
"""Schematic → netlist → MNA 행렬 자동 변환.

원천은 schematic.DEFAULT_LAYOUT 하나다: 선(line)·소자 endpoints·FET anchor의
기하 연결성에서 net을 추출하고(축정렬 세그먼트 + 등록점 union-find),
instance 상자(cell/model/params)와 소자를 포함 관계로 결합해 netlist를 만든 뒤
MNA(G·v=J, Newton)로 조립·해석한다.

model equation은 임의 placeholder(사용자 허용 2026-07-27):
  diode/b2b/FET접합 = softplus 다이오드, clamp = 양방향 softplus(트리거 4V),
  R = 선형(params.R 또는 rdd(L)). 크기 파라미터(x1/x2)는 아직 미반영.

open(회색 #b0b6bf) 소자는 stamping 제외(배선은 유지). 전류원은 G에 기여하지
않으므로 시나리오는 (inject port, ground port, I)로 지정한다.
"""
import math

OPEN_COLOR = "#b0b6bf"
TOL = 0.02
GMIN = 1e-9

# net 이름 힌트: 대표 좌표 → 이름 (port 텍스트는 회로도에서 삭제된 상태라 좌표로 명명)
NET_NAMES = [
    ((-3.0, 6.0), "VDD"), ((-3.0, 3.0), "IO"), ((-3.0, 0.0), "VSS"), ((-3.0, -3.0), "MVSS"),
    ((10.3, 6.0), "VDD2"), ((10.3, 3.0), "IO2"), ((10.3, 0.0), "VSS2"),
    ((-0.2, 3.0), "N1"), ((-0.2, 6.0), "N2"), ((7.1, 6.0), "N3"), ((7.1, 0.0), "N3B"),
    ((5.1, 3.0), "OUT"), ((2.6, 3.0), "IN"), ((-0.2, 0.0), "VSSR"),
]


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
    for e in layout.get("elements", []):
        t = e.get("type")
        if t == "line":
            wires.append((pt(e["from"]), pt(e["to"])))
        elif t == "rect" and e.get("instance"):
            (x1, y1), (x2, y2) = e["corner1"], e["corner2"]
            rects.append({"instance": e["instance"], "cell": e.get("cell"),
                          "model": e.get("model"), "params": e.get("params", {}),
                          "variant": e.get("variant"),
                          "bb": (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)),
                          "open": e.get("color") == OPEN_COLOR})
        elif t in ("resistor", "diode", "zener", "sourcei"):
            a, b = pt(e["from"]), pt(e["to"])
            devices.append({"kind": t, "a": a, "b": b,
                            "mid": ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0),
                            "open": e.get("color") == OPEN_COLOR})
        elif t == "ground":
            grounds.append(pt(e["at"]))
        elif t in ("pfet", "nfet"):
            d = pt(e["drain"])
            sgn = 1.0 if t == "pfet" else -1.0  # 본 레이아웃 고정 방향(rot180+flip)
            src = (d[0], d[1] + 0.96 * sgn)
            gate = (d[0] - 0.875, d[1] + 0.48 * sgn)
            fets.append({"kind": t, "drain": d, "source": src, "gate": gate,
                         "mid": ((d[0] + gate[0]) / 2.0, d[1]), "open": e.get("color") == OPEN_COLOR})
            if "rail_y" in e:
                wires.append((src, (src[0], e["rail_y"])))
    # gates: 같은 drain의 pfet/nfet 쌍 → gate-gate 수직 배선 (tie 점은 세그먼트 위 등록점으로 합류)
    for i, f1 in enumerate(fets):
        for f2 in fets[i + 1:]:
            if f1["kind"] != f2["kind"] and _k(f1["drain"]) == _k(f2["drain"]):
                wires.append((f1["gate"], f2["gate"]))
    # bulk = source (렌더러의 bulk→source 직결) — 별도 net 불필요

    # 등록점: 모든 배선 끝점 + 소자 pin + ground + dot
    pts = set()
    for a, b in wires:
        pts.add(_k(a)); pts.add(_k(b))
    for d in devices:
        pts.add(_k(d["a"])); pts.add(_k(d["b"]))
    for f in fets:
        pts.add(_k(f["drain"])); pts.add(_k(f["source"])); pts.add(_k(f["gate"]))
    for g in grounds:
        pts.add(_k(g))
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
    for i, (root, members) in enumerate(sorted(roots.items())):
        for p in members:
            net_of[p] = i
        name = None
        for coord, nm in NET_NAMES:
            if _k(coord) in members:
                name = nm
                break
        net_names[i] = name or "n{}".format(i)

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

    out_devices = []
    for d in devices:
        r = owner(d["mid"]) or {}
        out_devices.append({
            "kind": d["kind"], "open": d["open"] or r.get("open", False),
            "instance": r.get("instance"), "cell": r.get("cell"),
            "model": r.get("model"), "params": r.get("params", {}),
            "a": net(d["a"]), "b": net(d["b"]),
        })
    for f in fets:
        r = owner(f["mid"]) or {}
        out_devices.append({
            "kind": f["kind"], "open": f["open"] or r.get("open", False),
            "instance": r.get("instance"), "cell": r.get("cell"),
            "model": r.get("model"), "params": r.get("params", {}),
            "drain": net(f["drain"]), "source": net(f["source"]), "gate": net(f["gate"]),
        })

    ground_nets = sorted(set(net(g) for g in grounds))
    return {"nets": net_names, "devices": out_devices, "ground_nets": ground_nets,
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

    ref = set(nl["ground_nets"])
    ref.add(name_to_net[ground])
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
    it, res = 0, float("inf")
    for it in range(1, max_iter + 1):
        G, F = build(v)
        res = max(abs(x) for x in F) if F else 0.0
        if res < tol:
            break
        dv = solve_lin(G, [-x for x in F])
        mx = max(abs(x) for x in dv) if dv else 0.0
        damp = 1.0 if mx <= 1.0 else 1.0 / mx  # step 제한 1V
        v = [vi + damp * di for vi, di in zip(v, dv)]

    G, F = build(v)
    return {
        "inject": inject, "ground": ground, "I": I, "L": L,
        "unknowns": [names[n] for n in unknowns],
        "ref_nets": sorted(names[n] for n in ref if n in names),
        "v": {names[n]: v[idx[n]] for n in unknowns},
        "G": G, "residual": max(abs(x) for x in F) if F else 0.0,
        "newton_iters": it,
        "size": "{0}×{0}".format(N),
        "nnz": sum(1 for row in G for x in row if abs(x) > 1e-12),
    }
