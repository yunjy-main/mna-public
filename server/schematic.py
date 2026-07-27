# -*- coding: utf-8 -*-
"""Schematic renderer (schemdraw 0.15) — data-driven, user-editable layout.

The drawing is fully described by a layout dict (JSON-editable from the circuit
screen): node coordinates + label offsets, and an ordered element list.
Element types: line, dot, ground, sourcei, resistor, diode, zener, label,
pfet, nfet, gates. Coordinates are [x, y] or a node name. Labels may use
{x1} {x2} {L} {rvdd} placeholders.

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
    "nodes": {
        "IO":  {"xy": [0.0, 3.0],  "ofst": [-0.2, 0.4]},
        "N1":  {"xy": [3.4, 3.0],  "ofst": [0.25, -0.75]},
        "N2":  {"xy": [3.4, 6.0],  "ofst": [-1.3, 0.35]},
        "N3":  {"xy": [7.4, 6.0],  "ofst": [0.3, 0.35]},
        "OUT": {"xy": [11.0, 3.0], "ofst": [0.1, 0.45]},
    },
    "elements": [
        {"type": "line", "from": [-1.8, 0], "to": [11.0, 0]},
        {"type": "label", "at": [11.4, 0.0], "text": "VSS"},
        {"type": "ground", "at": [5.4, 0]},
        {"type": "sourcei", "from": [-1.8, 0], "to": [-1.8, 3]},
        {"type": "label", "at": [-2.6, 1.5], "text": "I_ESD"},
        {"type": "line", "from": [-1.8, 3], "to": "IO"},
        {"type": "dot", "at": "IO"},
        {"type": "resistor", "from": "IO", "to": "N1", "label": "Rio 0.1Ω", "loc": "top"},
        {"type": "dot", "at": "N1"},
        {"type": "diode", "from": "N1", "to": "N2", "label": "D_up x1={x1}", "loc": "bottom"},
        {"type": "dot", "at": "N2"},
        {"type": "resistor", "from": "N2", "to": "N3", "label": "Rvdd {rvdd}Ω L={L}µm", "loc": "top"},
        {"type": "dot", "at": "N3"},
        {"type": "line", "from": "N3", "to": [11.0, 6]},
        {"type": "label", "at": [11.4, 6.0], "text": "VDD"},
        {"type": "zener", "from": "N3", "to": [7.4, 0], "label": "Clamp x2={x2}", "loc": "bottom"},
        {"type": "diode", "from": [3.4, 0], "to": "N1", "label": "D_down", "loc": "bottom"},
        {"type": "line", "from": "IO", "to": [0, 0.9]},
        {"type": "line", "from": [0, 0.9], "to": [4.2, 0.9]},
        {"type": "resistor", "from": [4.2, 0.9], "to": [6.6, 0.9], "label": "Resd 500Ω", "loc": "bottom"},
        {"type": "line", "from": [6.6, 0.9], "to": [10.0, 0.9]},
        {"type": "line", "from": [10.0, 0.9], "to": [10.0, 3.0]},
        {"type": "line", "from": [10.0, 3.0], "to": "OUT"},
        {"type": "dot", "at": "OUT"},
        {"type": "pfet", "drain": "OUT", "label": "PMOS", "rail_y": 6.0},
        {"type": "nfet", "drain": "OUT", "label": "NMOS", "rail_y": 0.0},
        {"type": "gates", "text": "V_IN=0"},
    ],
    "current_labels": {"i": [1.7, 2.45], "iv": [5.4, 1.25]},
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
    fets = {}

    for e in layout.get("elements", []):
        t = e.get("type")
        if t == "line":
            d.add(elm.Line().at(pt(e["from"])).to(pt(e["to"])))
        elif t == "dot":
            d.add(elm.Dot().at(pt(e["at"])))
        elif t == "ground":
            d.add(elm.Ground().at(pt(e["at"])))
        elif t == "label":
            d.add(elm.Label().at(pt(e["at"])).label(txt(e.get("text", "")), fontsize=fs - 1,
                                                    color=e.get("color", MUT)))
        elif t in ("resistor", "diode", "zener", "sourcei"):
            cls = {"resistor": elm.Resistor, "diode": elm.Diode,
                   "zener": elm.Zener, "sourcei": elm.SourceI}[t]
            el = cls().endpoints(pt(e["from"]), pt(e["to"]))
            if e.get("label"):
                el = el.label(txt(e["label"]), loc=e.get("loc", "top"), fontsize=fs)
            d.add(el)
        elif t in ("pfet", "nfet"):
            cls = elm.PFet if t == "pfet" else elm.NFet
            q = d.add(cls().at(pt(e["drain"])).anchor('drain')
                      .label(e.get("label", ""), loc="right", fontsize=fs))
            fets[t] = q
            src = q.absanchors['source']
            if "rail_y" in e:
                d.add(elm.Line().at((src.x, src.y)).to((src.x, e["rail_y"])))
        elif t == "gates":
            if "pfet" in fets and "nfet" in fets:
                g1 = fets["pfet"].absanchors['gate']
                g2 = fets["nfet"].absanchors['gate']
                ym = (g1.y + g2.y) / 2
                d.add(elm.Line().at((g1.x, g1.y)).to((g2.x, g2.y)))
                d.add(elm.Line().at((g1.x, ym)).to((g1.x + 0.6, ym)))
                d.add(elm.Label().at((g1.x + 0.75, ym)).label(e.get("text", "V_IN"),
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
