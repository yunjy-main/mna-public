# -*- coding: utf-8 -*-
"""Schematic renderer (schemdraw 0.15) — data-driven, user-editable layout.

The drawing is fully described by a layout dict (JSON-editable from the circuit
screen): node coordinates + label offsets, and an ordered element list.
Element types: line, dot, ground, sourcei, resistor, diode, zener, label,
port(lofst), rect(subcircuit box), pfet, nfet, gates. Coordinates are [x, y]
or a node name. Labels may use {x1} {x2} {L} {rvdd} placeholders.

Styling rules (rail y=0/2/4, 심볼 간격 0.8, 저항 스팬 2.0, symbol_scale 0.64,
저항 직결/중앙 배치 등)은 docs/SCHEMATIC_STYLE.md 에 성문화 — 레이아웃 수정 시 준수.

Custom layouts persist to assets/schematic_layout.json (DELETE to restore the
built-in default).
"""
import json
import os

import schemdraw
import schemdraw.elements as elm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUT_PATH = os.path.join(ROOT, "assets", "schematic_layout.json")

ACC = '#0b57a4'   # 전압 주석(푸른계열)
CUR = '#00796b'   # 전류 주석
MUT = '#5b6673'

DEFAULT_LAYOUT = {
    "unit": 2,
    "fontsize": 9,
    "symbol_scale": 0.64,
    "nodes": {
        "IO":  {"xy": [-0.2, 2.0], "ofst": [-1.5, 0.42]},
        "N2":  {"xy": [-0.2, 4.0], "ofst": [-1.3, 0.35]},
        "N3":  {"xy": [7.1, 4.0], "ofst": [0.3, -0.78]},
        "N3B": {"xy": [7.1, 0.0], "ofst": [0.3, 0.35]},
        "OUT": {"xy": [2.2, 2.0],  "ofst": [0.0, 0.5]},
        "VSSR": {"xy": [0.9, 0.0], "ofst": [-0.6, 0.35]},
    },
    "elements": [
        {"type": "port", "at": [-3.0, 4.0], "text": "VDD", "lofst": [-0.45, 0.38]},
        {"type": "port", "at": [-3.0, 2.0], "text": "IO", "lofst": [-0.45, 0.38]},
        {"type": "port", "at": [-3.0, 0.0], "text": "VSS", "lofst": [-0.45, 0.38]},
        {"type": "line", "from": [-3.8, 4], "to": [-3.0, 4]},
        {"type": "line", "from": [-3.8, 2], "to": [-3.0, 2]},
        {"type": "line", "from": [-3.8, 0], "to": [-3.0, 0]},
        {"type": "sourcei", "from": [-3.8, 2], "to": [-3.8, 4]},
        {"type": "sourcei", "from": [-3.8, 0], "to": [-3.8, 2]},
        {"type": "sourcei", "from": [-3.8, -2.0], "to": [-3.8, 0]},
        {"type": "ground", "at": [-3.8, -2.0]},
        {"type": "dot", "at": [-3.8, 4]},
        {"type": "dot", "at": [-3.8, 2]},
        {"type": "dot", "at": [-3.8, 0]},
        {"type": "label", "at": [-4.95, 3.0], "text": "I_ESD (IO→VDD)"},
        {"type": "label", "at": [-4.95, 1.0], "text": "I_ESD (IO→VSS)"},
        {"type": "label", "at": [-4.95, -1.0], "text": "I_ESD (GND→VSS)"},
        {"type": "line", "from": [-3.0, 4], "to": [-2.6, 4]},
        {"type": "resistor", "from": [-2.6, 4], "to": [-0.6, 4], "label": "Rvdd_rdl 0.1Ω", "loc": "top"},
        {"type": "line", "from": [-0.6, 4], "to": "N2"},
        {"type": "line", "from": [-3.0, 2], "to": [-2.6, 2]},
        {"type": "resistor", "from": [-2.6, 2], "to": [-0.6, 2], "label": "Rio_rdl 0.1Ω", "loc": "top"},
        {"type": "line", "from": [-0.6, 2], "to": "IO"},
        {"type": "line", "from": [-3.0, 0], "to": [-2.6, 0]},
        {"type": "resistor", "from": [-2.6, 0], "to": [-0.6, 0], "label": "Rvss_rdl 0.1Ω", "loc": "bottom"},
        {"type": "line", "from": [-0.6, 0], "to": [5.1, 0]},
        {"type": "diode", "from": "IO", "to": "N2"},
        {"type": "rect", "corner1": [-0.7, 2.3], "corner2": [0.3, 3.7], "title": "D_up x1={x1}"},
        {"type": "port", "at": [-0.2, 3.7], "text": ""},
        {"type": "port", "at": [-0.2, 2.3], "text": ""},
        {"type": "diode", "from": [-0.2, 0], "to": "IO"},
        {"type": "rect", "corner1": [-0.7, 0.3], "corner2": [0.3, 1.7], "title": "D_down"},
        {"type": "port", "at": [-0.2, 1.7], "text": ""},
        {"type": "port", "at": [-0.2, 0.3], "text": ""},
        {"type": "dot", "at": "IO"},
        {"type": "dot", "at": "N2"},
        {"type": "dot", "at": [-0.2, 0]},
        {"type": "line", "from": "N2", "to": [5.1, 4]},
        {"type": "resistor", "from": [5.1, 4], "to": "N3", "label": "RDD_un1 {rvdd}Ω L={L}µm", "loc": "top"},
        {"type": "resistor", "from": [5.1, 0], "to": "N3B", "label": "RDD_dn1 {rvdd}Ω", "loc": "bottom"},
        {"type": "zener", "from": "N3B", "to": "N3", "label": "Clamp x2={x2}", "loc": "bottom"},
        {"type": "dot", "at": "N3"},
        {"type": "dot", "at": "N3B"},
        {"type": "line", "from": "IO", "to": [0.2, 2.0]},
        {"type": "resistor", "from": [0.2, 2.0], "to": [2.2, 2.0], "label": "Resd 500Ω", "loc": "bottom"},
        {"type": "line", "from": [2.2, 2.0], "to": [2.6, 2.0]},
        {"type": "diode", "from": [2.6, 2.0], "to": [2.6, 4.0]},
        {"type": "rect", "corner1": [2.1, 2.3], "corner2": [3.1, 3.7], "title": "D_up2"},
        {"type": "port", "at": [2.6, 3.7], "text": ""},
        {"type": "port", "at": [2.6, 2.3], "text": ""},
        {"type": "diode", "from": [2.6, 0.0], "to": [2.6, 2.0]},
        {"type": "rect", "corner1": [2.1, 0.3], "corner2": [3.1, 1.7], "title": "D_down2"},
        {"type": "port", "at": [2.6, 1.7], "text": ""},
        {"type": "port", "at": [2.6, 0.3], "text": ""},
        {"type": "dot", "at": [2.6, 2.0]},
        {"type": "dot", "at": [2.6, 4.0]},
        {"type": "dot", "at": [2.6, 0.0]},
        {"type": "line", "from": [2.6, 2.0], "to": [5.1, 2.0]},
        {"type": "rect", "corner1": [3.4, 0.3], "corner2": [5.45, 3.7], "title": "Victim"},
        {"type": "pfet", "drain": [5.1, 2.0], "label": "PMOS", "loc": "right", "rot": 180, "flip": True, "rail_y": 4.0},
        {"type": "nfet", "drain": [5.1, 2.0], "label": "NMOS", "loc": "right", "rot": 180, "flip": True, "rail_y": 0.0},
        {"type": "gates", "tie": "OUT"},
        {"type": "dot", "at": [5.1, 2.0]},
        {"type": "dot", "at": [5.1, 4.0]},
        {"type": "dot", "at": [5.1, 0.0]},
        {"type": "port", "at": [3.4, 2.0], "text": "IN", "lofst": [-0.7, -0.6]},
        {"type": "port", "at": [5.1, 3.7], "text": "VDD", "lofst": [0.15, 0.05]},
        {"type": "port", "at": [5.1, 0.3], "text": "VSS", "lofst": [0.15, 0.15]},
        {"type": "line", "from": "N3B", "to": [7.9, 0]},
        {"type": "dot", "at": [7.9, 0]},
        {"type": "line", "from": [7.9, 0], "to": [8.25, 0]},
        {"type": "dot", "at": [8.25, 0]},
        {"type": "line", "from": [8.25, 0], "to": [8.25, 0.35]},
        {"type": "line", "from": [8.25, 0], "to": [8.25, -0.35]},
        {"type": "diode", "from": [8.25, 0.35], "to": [9.15, 0.35]},
        {"type": "diode", "from": [9.15, -0.35], "to": [8.25, -0.35]},
        {"type": "rect", "corner1": [8.05, -0.6], "corner2": [9.35, 0.6], "title": "D_b2b"},
        {"type": "port", "at": [8.05, 0.0], "text": ""},
        {"type": "port", "at": [9.35, 0.0], "text": ""},
        {"type": "line", "from": [9.15, 0.35], "to": [9.15, 0]},
        {"type": "line", "from": [9.15, -0.35], "to": [9.15, 0]},
        {"type": "dot", "at": [9.15, 0]},
        {"type": "line", "from": [9.15, 0], "to": [9.5, 0]},
        {"type": "dot", "at": [9.5, 0]},
        {"type": "line", "from": [9.5, 0], "to": [10.3, 0]},
        {"type": "port", "at": [10.3, 0.0], "text": "VSS2", "lofst": [0.65, 0]},
        {"type": "line", "from": [9.5, 2], "to": [10.3, 2]},
        {"type": "port", "at": [10.3, 2.0], "text": "IO2", "lofst": [0.6, 0]},
        {"type": "line", "from": [9.5, 4], "to": [10.3, 4]},
        {"type": "port", "at": [10.3, 4.0], "text": "VDD2", "lofst": [0.65, 0]},
        {"type": "port", "at": [-3.0, -2.0], "text": "MVSS", "lofst": [-0.45, 0.38]},
        {"type": "line", "from": [-3.0, -2.0], "to": [10.3, -2.0]},
        {"type": "dot", "at": [1.2, 0.0]},
        {"type": "line", "from": [1.2, 0.0], "to": [1.2, -0.55]},
        {"type": "dot", "at": [1.2, -0.55]},
        {"type": "line", "from": [1.2, -0.55], "to": [0.9, -0.55]},
        {"type": "line", "from": [1.2, -0.55], "to": [1.5, -0.55]},
        {"type": "diode", "from": [0.9, -1.45], "to": [0.9, -0.55]},
        {"type": "diode", "from": [1.5, -0.55], "to": [1.5, -1.45]},
        {"type": "rect", "corner1": [0.65, -1.65], "corner2": [1.75, -0.35], "title": "D_b2b_m"},
        {"type": "port", "at": [1.2, -0.35], "text": ""},
        {"type": "port", "at": [1.2, -1.65], "text": ""},
        {"type": "line", "from": [0.9, -1.45], "to": [1.2, -1.45]},
        {"type": "line", "from": [1.5, -1.45], "to": [1.2, -1.45]},
        {"type": "dot", "at": [1.2, -1.45]},
        {"type": "line", "from": [1.2, -1.45], "to": [1.2, -2.0]},
        {"type": "dot", "at": [1.2, -2.0]},
    ],
    "current_labels": {"i": [0.8, 1.6], "iv": [2.2, 1.3]},
}


def load_layout():
    if os.path.isfile(LAYOUT_PATH):
        with open(LAYOUT_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh), True
    return DEFAULT_LAYOUT, False


def save_layout(layout):
    os.makedirs(os.path.dirname(LAYOUT_PATH), exist_ok=True)
    with open(LAYOUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(layout, fh, ensure_ascii=False, indent=1)


def reset_layout():
    if os.path.isfile(LAYOUT_PATH):
        os.remove(LAYOUT_PATH)


def build_svg(x1, x2, L=350.0, op=None, layout=None):
    """Render the layout (saved/custom/default) to SVG. op = node voltages/currents."""
    if layout is None:
        layout, _ = load_layout()
    rvdd = 0.5 * L / 350.0
    subst = {"x1": "{:g}".format(x1), "x2": "{:g}".format(x2),
             "L": "{:g}".format(L), "rvdd": "{:.3g}".format(rvdd)}

    nodes = {k: v for k, v in layout.get("nodes", {}).items()}

    def pt(ref):
        if isinstance(ref, str):
            return tuple(nodes[ref]["xy"])
        return tuple(ref)

    def txt(s):
        for k, v in subst.items():
            s = s.replace("{" + k + "}", v)
        return s

    d = schemdraw.Drawing(backend='svg')
    d.config(unit=layout.get("unit", 2), fontsize=layout.get("fontsize", 9))
    fs = layout.get("fontsize", 9)
    ss = layout.get("symbol_scale", 1.0)  # 심볼 몸체 배율 (endpoints 스팬·anchor는 불변)
    fets = {}

    for e in layout.get("elements", []):
        t = e.get("type")
        if t == "line":
            d.add(elm.Line().at(pt(e["from"])).to(pt(e["to"])))
        elif t == "dot":
            d.add(elm.Dot().at(pt(e["at"])))
        elif t == "ground":
            d.add(elm.Ground().at(pt(e["at"])).scale(ss))
        elif t == "label":
            d.add(elm.Label().at(pt(e["at"])).label(txt(e.get("text", "")), fontsize=fs - 1,
                                                    color=e.get("color", MUT)))
        elif t == "rect":
            # subcircuit 외곽 상자: corner1/corner2 절대좌표 4변 (Rect는 상대좌표라 미사용)
            (x1r, y1r), (x2r, y2r) = pt(e["corner1"]), pt(e["corner2"])
            xa, xb = min(x1r, x2r), max(x1r, x2r)
            ya, yb = min(y1r, y2r), max(y1r, y2r)
            ls, col = e.get("ls", "--"), e.get("color", MUT)
            for a, b in (((xa, ya), (xb, ya)), ((xb, ya), (xb, yb)),
                         ((xb, yb), (xa, yb)), ((xa, yb), (xa, ya))):
                d.add(elm.Line().at(a).to(b).linestyle(ls).color(col))
            if e.get("title"):
                d.add(elm.Label().at((xa + 0.15, yb - 0.32)).label(txt(e["title"]), fontsize=fs - 1,
                                                                   color=col, halign='left'))
        elif t in ("resistor", "diode", "zener", "sourcei"):
            cls = {"resistor": elm.Resistor, "diode": elm.Diode,
                   "zener": elm.Zener, "sourcei": elm.SourceI}[t]
            el = cls().endpoints(pt(e["from"]), pt(e["to"])).scale(ss)
            if e.get("label"):
                el = el.label(txt(e["label"]), loc=e.get("loc", "top"), fontsize=fs)
            d.add(el)
        elif t == "port":
            x, y = pt(e["at"])
            lx, ly = e.get("lofst", [-0.75, 0])
            d.add(elm.Dot(open=True).at((x, y)))
            d.add(elm.Label().at((x + lx, y + ly)).label(e.get("text", ""), fontsize=fs, color='#20242a'))
        elif t in ("pfet", "nfet"):
            cls = elm.PFet if t == "pfet" else elm.NFet
            el = cls()
            if e.get("rot"):
                el = el.theta(e["rot"])
            if e.get("flip"):
                el = el.flip()
            lloc = e.get("loc", "right")
            q = d.add(el.at(pt(e["drain"])).anchor('drain').scale(ss)
                      .label(e.get("label", ""), loc=lloc, fontsize=fs))
            fets[t] = q
            src = q.absanchors['source']
            if "rail_y" in e:
                d.add(elm.Line().at((src.x, src.y)).to((src.x, e["rail_y"])))
        elif t == "gates":
            if "pfet" in fets and "nfet" in fets:
                g1 = fets["pfet"].absanchors['gate']
                g2 = fets["nfet"].absanchors['gate']
                d.add(elm.Line().at((g1.x, g1.y)).to((g2.x, g2.y)))
                tie = e.get("tie")
                if tie and tie in nodes:
                    # gate tie를 tie 노드 배선과 접점(dot)으로 연결 (diode-connected)
                    ty = nodes[tie]["xy"][1]
                    d.add(elm.Dot().at((g1.x, ty)))
                else:
                    # 외부 입력 스텁
                    sy = g2.y
                    d.add(elm.Line().at((g2.x, sy)).to((g2.x - 0.6, sy)))
                    d.add(elm.Label().at((g2.x - 1.15, sy)).label(e.get("text", "V_IN"),
                                                                  fontsize=fs - 1, color=MUT))

    # node names + operating-point voltages (파란 주석)
    for name, nd in nodes.items():
        x, y = nd["xy"]
        dx, dy = nd.get("ofst", [0.15, 0.3])
        text = name
        if op and name in op:
            text = "{} {:.2f}V".format(name, op[name])
        d.add(elm.Label().at((x + dx, y + dy)).label(text, fontsize=fs - 1, color=ACC))
    cl = layout.get("current_labels", {})
    if op and "i" in op and "i" in cl:
        d.add(elm.Label().at(tuple(cl["i"])).label("I={:.2f}A".format(op["i"]),
                                                   fontsize=fs - 1, color=CUR))
    if op and "iv" in op and "iv" in cl:
        d.add(elm.Label().at(tuple(cl["iv"])).label("I_v={:.2f}mA".format(1000 * op["iv"]),
                                                    fontsize=fs - 1, color=CUR))

    data = d.get_imagedata('svg')
    return data.decode('utf-8') if isinstance(data, bytes) else data
