# -*- coding: utf-8 -*-
"""Schematic renderer (schemdraw 0.15) — data-driven, user-editable layout.

The drawing is fully described by a layout dict (JSON-editable from the circuit
screen): node coordinates + label offsets, and an ordered element list.
Element types: line, dot, ground, sourcei, resistor, diode, zener, label,
port(lofst), rect(subcircuit box), pfet, nfet, gates. Coordinates are [x, y]
or a node name. Labels may use {x1} {x2} {L} {rvdd} placeholders.

Styling rules (rail y=0/3/6, 심볼 간격 0.8, 저항 스팬 2.0, symbol_scale 0.64,
노드 중앙 배치 등)은 docs/SCHEMATIC_STYLE.md 에 성문화 — 레이아웃 수정 시 준수.

Custom layouts persist to assets/schematic_layout.json (DELETE to restore the
built-in default).
"""
import json
import os
import re as _re

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
        "IO": {"xy": [-0.2, 3.0], "ofst": [-1.5, 0.63]},
        "N2": {"xy": [-0.2, 6.0], "ofst": [-1.3, 0.525]},
        "N3": {"xy": [7.1, 6.0], "ofst": [0.3, -1.17]},
        "N3B": {"xy": [7.1, 0.0], "ofst": [0.3, 0.525]},
        "OUT": {"xy": [5.1, 3.0], "ofst": [0.3, 0.45]},
        "VSSR": {"xy": [0.9, 0.0], "ofst": [-0.6, 0.525]},
    },
    "elements": [
        {"type": "port", "at": [-3.0, 6.0], "text": "VDD", "lofst": [-0.45, 0.57]},
        {"type": "port", "at": [-3.0, 3.0], "text": "IO", "lofst": [-0.45, 0.57]},
        {"type": "port", "at": [-3.0, 0.0], "text": "VSS", "lofst": [-0.45, 0.57]},
        {"type": "line", "from": [-3.8, 6.0], "to": [-3.0, 6.0], "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, 3.0], "to": [-3.0, 3.0], "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, 0.0], "to": [-3.0, 0.0], "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, -3.0], "to": [-3.0, -3.0], "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, 5.5], "to": [-3.8, 6.0], "color": "#b0b6bf"},
        {"type": "sourcei", "from": [-3.8, 4.5], "to": [-3.8, 5.5], "color": "#b0b6bf"},
        {"type": "ground", "at": [-3.8, 4.5], "color": "#b0b6bf"},
        {"type": "rect", "corner1": [-4.3, 4.0], "corner2": [-3.3, 5.55], "instance": "I_ESD (IO→VDD) (open)", "instance_loc": "br", "color": "#b0b6bf"},
        {"type": "port", "at": [-3.8, 5.55], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, 2.5], "to": [-3.8, 3.0], "color": "#b0b6bf"},
        {"type": "sourcei", "from": [-3.8, 1.5], "to": [-3.8, 2.5], "color": "#b0b6bf"},
        {"type": "ground", "at": [-3.8, 1.5], "color": "#b0b6bf"},
        {"type": "rect", "corner1": [-4.3, 1.0], "corner2": [-3.3, 2.55], "instance": "I_ESD (IO→VSS) (open)", "instance_loc": "br", "color": "#b0b6bf"},
        {"type": "port", "at": [-3.8, 2.55], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, -0.5], "to": [-3.8, 0.0], "color": "#b0b6bf"},
        {"type": "sourcei", "from": [-3.8, -1.5], "to": [-3.8, -0.5], "color": "#b0b6bf"},
        {"type": "ground", "at": [-3.8, -1.5], "color": "#b0b6bf"},
        {"type": "rect", "corner1": [-4.3, -2.0], "corner2": [-3.3, -0.45], "instance": "I_ESD (GND→VSS) (open)", "instance_loc": "br", "color": "#b0b6bf"},
        {"type": "port", "at": [-3.8, -0.45], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, -3.5], "to": [-3.8, -3.0], "color": "#b0b6bf"},
        {"type": "sourcei", "from": [-3.8, -4.5], "to": [-3.8, -3.5], "color": "#b0b6bf"},
        {"type": "ground", "at": [-3.8, -4.5], "color": "#b0b6bf"},
        {"type": "rect", "corner1": [-4.3, -5.0], "corner2": [-3.3, -3.45], "instance": "I_ESD (GND→MVSS) (open)", "color": "#b0b6bf"},
        {"type": "port", "at": [-3.8, -3.45], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [-3.0, 6.0], "to": [-2.6, 6.0]},
        {"type": "resistor", "from": [-2.6, 6.0], "to": [-0.6, 6.0]},
        {"type": "rect", "corner1": [-2.25, 5.55], "corner2": [-0.95, 6.45], "instance": "Rvdd_rdl", "instance_loc": "bl", "equation": "0.1Ω"},
        {"type": "port", "at": [-2.25, 6.0], "text": ""},
        {"type": "port", "at": [-0.95, 6.0], "text": ""},
        {"type": "line", "from": [-0.6, 6.0], "to": "N2"},
        {"type": "line", "from": [-3.0, 3.0], "to": [-2.6, 3.0]},
        {"type": "resistor", "from": [-2.6, 3.0], "to": [-0.6, 3.0]},
        {"type": "rect", "corner1": [-2.25, 2.55], "corner2": [-0.95, 3.45], "instance": "Rio_rdl", "instance_loc": "bl", "equation": "0.1Ω"},
        {"type": "port", "at": [-2.25, 3.0], "text": ""},
        {"type": "port", "at": [-0.95, 3.0], "text": ""},
        {"type": "line", "from": [-0.6, 3.0], "to": "IO"},
        {"type": "line", "from": [-3.0, 0.0], "to": [-2.6, 0.0]},
        {"type": "resistor", "from": [-2.6, 0.0], "to": [-0.6, 0.0]},
        {"type": "rect", "corner1": [-2.25, -0.45], "corner2": [-0.95, 0.45], "instance": "Rvss_rdl", "instance_loc": "bl", "equation": "0.1Ω"},
        {"type": "port", "at": [-2.25, 0.0], "text": ""},
        {"type": "port", "at": [-0.95, 0.0], "text": ""},
        {"type": "line", "from": [-0.6, 0.0], "to": [5.1, 0.0]},
        {"type": "diode", "from": "IO", "to": "N2"},
        {"type": "rect", "corner1": [-0.7, 3.9], "corner2": [0.3, 5.1], "instance": "D_up", "model": "model1", "equation": "softplus_bi"},
        {"type": "port", "at": [-0.2, 5.1], "text": ""},
        {"type": "port", "at": [-0.2, 3.9], "text": ""},
        {"type": "diode", "from": [-0.2, 0.0], "to": "IO", "fill": "black"},
        {"type": "rect", "corner1": [-0.7, 0.9], "corner2": [0.3, 2.1], "instance": "D_down", "model": "model1", "equation": "softplus_bi"},
        {"type": "port", "at": [-0.2, 2.1], "text": ""},
        {"type": "port", "at": [-0.2, 0.9], "text": ""},
        {"type": "dot", "at": "IO"},
        {"type": "dot", "at": "N2"},
        {"type": "dot", "at": [-0.2, 0.0]},
        {"type": "line", "from": "N2", "to": [5.1, 6.0]},
        {"type": "resistor", "from": [5.1, 6.0], "to": "N3"},
        {"type": "rect", "corner1": [5.55, 5.55], "corner2": [6.65, 6.45], "instance": "RDD_un1", "equation": "rdd(L)"},
        {"type": "port", "at": [5.55, 6.0], "text": ""},
        {"type": "port", "at": [6.65, 6.0], "text": ""},
        {"type": "resistor", "from": [5.1, 0.0], "to": "N3B"},
        {"type": "rect", "corner1": [5.55, -0.45], "corner2": [6.65, 0.45], "instance": "RDD_dn1", "equation": "rdd(L)"},
        {"type": "port", "at": [5.55, 0.0], "text": ""},
        {"type": "port", "at": [6.65, 0.0], "text": ""},
        {"type": "zener", "from": "N3B", "to": "N3"},
        {"type": "rect", "corner1": [6.6, 0.9], "corner2": [7.6, 5.1], "instance": "Clamp", "model": "model2", "equation": "softplus_bi"},
        {"type": "port", "at": [7.1, 5.1], "text": ""},
        {"type": "port", "at": [7.1, 0.9], "text": ""},
        {"type": "dot", "at": "N3"},
        {"type": "dot", "at": "N3B"},
        {"type": "line", "from": "IO", "to": [0.2, 3.0]},
        {"type": "resistor", "from": [0.2, 3.0], "to": [2.2, 3.0]},
        {"type": "rect", "corner1": [0.55, 2.55], "corner2": [1.85, 3.45], "instance": "Resd", "equation": "500Ω"},
        {"type": "port", "at": [0.55, 3.0], "text": ""},
        {"type": "port", "at": [1.85, 3.0], "text": ""},
        {"type": "line", "from": [2.2, 3.0], "to": [2.6, 3.0]},
        {"type": "diode", "from": [2.6, 3.0], "to": [2.6, 6.0]},
        {"type": "rect", "corner1": [2.1, 3.9], "corner2": [3.1, 5.1], "instance": "D_up2", "model": "model1", "equation": "softplus_bi"},
        {"type": "port", "at": [2.6, 5.1], "text": ""},
        {"type": "port", "at": [2.6, 3.9], "text": ""},
        {"type": "diode", "from": [2.6, 0.0], "to": [2.6, 3.0], "fill": "black"},
        {"type": "rect", "corner1": [2.1, 0.9], "corner2": [3.1, 2.1], "instance": "D_down2", "model": "model1", "equation": "softplus_bi"},
        {"type": "port", "at": [2.6, 2.1], "text": ""},
        {"type": "port", "at": [2.6, 0.9], "text": ""},
        {"type": "dot", "at": [2.6, 3.0]},
        {"type": "dot", "at": [2.6, 6.0]},
        {"type": "dot", "at": [2.6, 0.0]},
        {"type": "line", "from": [2.6, 3.0], "to": [4.225, 3.0]},
        {"type": "rect", "corner1": [3.4, 0.9], "corner2": [5.45, 5.1], "instance": "Victim", "model": ["SG_PFET 1stk_1rx", "SG_NFET 1stk_1rx"]},
        {"type": "pfet", "drain": [5.1, 3.0], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": 6.0, "bulk": True},
        {"type": "nfet", "drain": [5.1, 3.0], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": 0.0, "bulk": True},
        {"type": "gates", "tie": "OUT"},
        {"type": "dot", "at": [5.1, 3.0]},
        {"type": "dot", "at": [5.1, 6.0]},
        {"type": "dot", "at": [5.1, 0.0]},
        {"type": "port", "at": [3.4, 3.0], "text": "IN", "lofst": [-0.7, -0.9]},
        {"type": "port", "at": [5.1, 5.1], "text": "VDD", "lofst": [0.15, 0.075]},
        {"type": "port", "at": [5.1, 0.9], "text": "VSS", "lofst": [0.15, 0.225]},
        {"type": "line", "from": "N3B", "to": [7.9, 0.0]},
        {"type": "dot", "at": [7.9, 0.0]},
        {"type": "line", "from": [7.9, 0.0], "to": [8.25, 0.0], "color": "#b0b6bf"},
        {"type": "dot", "at": [8.25, 0.0], "color": "#b0b6bf"},
        {"type": "line", "from": [8.25, 0.0], "to": [8.25, 0.3], "color": "#b0b6bf"},
        {"type": "line", "from": [8.25, 0.0], "to": [8.25, -0.3], "color": "#b0b6bf"},
        {"type": "diode", "from": [8.25, 0.3], "to": [9.15, 0.3], "color": "#b0b6bf"},
        {"type": "diode", "from": [9.15, -0.3], "to": [8.25, -0.3], "color": "#b0b6bf"},
        {"type": "rect", "corner1": [8.05, -0.65], "corner2": [9.35, 0.65], "instance": "D_b2b (open)", "color": "#b0b6bf"},
        {"type": "port", "at": [8.05, 0.0], "text": "", "color": "#b0b6bf"},
        {"type": "port", "at": [9.35, 0.0], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [9.15, 0.3], "to": [9.15, 0.0], "color": "#b0b6bf"},
        {"type": "line", "from": [9.15, -0.3], "to": [9.15, 0.0], "color": "#b0b6bf"},
        {"type": "dot", "at": [9.15, 0.0], "color": "#b0b6bf"},
        {"type": "line", "from": [9.15, 0.0], "to": [9.5, 0.0], "color": "#b0b6bf"},
        {"type": "dot", "at": [9.5, 0.0]},
        {"type": "line", "from": [9.5, 0.0], "to": [10.3, 0.0]},
        {"type": "port", "at": [10.3, 0.0], "text": "VSS2", "lofst": [0.65, 0.0]},
        {"type": "line", "from": [9.5, 3.0], "to": [10.3, 3.0]},
        {"type": "port", "at": [10.3, 3.0], "text": "IO2", "lofst": [0.6, 0.0]},
        {"type": "line", "from": [9.5, 6.0], "to": [10.3, 6.0]},
        {"type": "port", "at": [10.3, 6.0], "text": "VDD2", "lofst": [0.65, 0.0]},
        {"type": "line", "from": [10.3, 0.0], "to": [10.3, -0.825]},
        {"type": "dot", "at": [10.3, -0.825]},
        {"type": "line", "from": [10.3, -0.825], "to": [10.0, -0.825]},
        {"type": "line", "from": [10.3, -0.825], "to": [10.6, -0.825]},
        {"type": "diode", "from": [10.0, -2.175], "to": [10.0, -0.825]},
        {"type": "diode", "from": [10.6, -0.825], "to": [10.6, -2.175]},
        {"type": "rect", "corner1": [9.75, -2.4], "corner2": [10.85, -0.6], "instance": "D_b2b_m2"},
        {"type": "port", "at": [10.3, -0.6], "text": ""},
        {"type": "port", "at": [10.3, -2.4], "text": ""},
        {"type": "line", "from": [10.0, -2.175], "to": [10.3, -2.175]},
        {"type": "line", "from": [10.6, -2.175], "to": [10.3, -2.175]},
        {"type": "dot", "at": [10.3, -2.175]},
        {"type": "line", "from": [10.3, -2.175], "to": [10.3, -3.0]},
        {"type": "dot", "at": [10.3, -3.0]},
        {"type": "port", "at": [-3.0, -3.0], "text": "MVSS", "lofst": [-0.45, 0.57]},
        {"type": "line", "from": [-3.0, -3.0], "to": [10.3, -3.0]},
        {"type": "line", "from": [7.1, 0.0], "to": [7.1, -0.825]},
        {"type": "dot", "at": [7.1, -0.825]},
        {"type": "line", "from": [7.1, -0.825], "to": [6.8, -0.825]},
        {"type": "line", "from": [7.1, -0.825], "to": [7.4, -0.825]},
        {"type": "diode", "from": [6.8, -2.175], "to": [6.8, -0.825]},
        {"type": "diode", "from": [7.4, -0.825], "to": [7.4, -2.175]},
        {"type": "rect", "corner1": [6.55, -2.4], "corner2": [7.65, -0.6], "instance": "D_b2b_m"},
        {"type": "port", "at": [7.1, -0.6], "text": ""},
        {"type": "port", "at": [7.1, -2.4], "text": ""},
        {"type": "line", "from": [6.8, -2.175], "to": [7.1, -2.175]},
        {"type": "line", "from": [7.4, -2.175], "to": [7.1, -2.175]},
        {"type": "dot", "at": [7.1, -2.175]},
        {"type": "line", "from": [7.1, -2.175], "to": [7.1, -3.0]},
        {"type": "dot", "at": [7.1, -3.0]},
    ],
    "current_labels": {"i": [0.8, 2.4], "iv": [2.2, 1.95]},
}

# Subcircuit Set — 별도 canvas로 서빙 (/api/schematic/library). 형태 기준 중복 없는 cell 목록.
LIBRARY_LAYOUT = {
    "unit": 2,
    "fontsize": 9,
    "symbol_scale": 0.64,
    "nodes": {},
    "elements": [
        {"type": "line", "from": [-3.8, -8.05], "to": [-3.8, -8.0]},
        {"type": "sourcei", "from": [-3.8, -9.05], "to": [-3.8, -8.05]},
        {"type": "ground", "at": [-3.8, -9.05]},
        {"type": "rect", "corner1": [-4.3, -9.55], "corner2": [-3.3, -8.0], "title": "I_ESD"},
        {"type": "port", "at": [-3.8, -8.0], "text": ""},
        {"type": "line", "from": [-2.0, -8.0], "to": [-2.0, -9.05]},
        {"type": "ground", "at": [-2.0, -9.05]},
        {"type": "rect", "corner1": [-2.5, -9.55], "corner2": [-1.5, -8.0], "title": "GND"},
        {"type": "port", "at": [-2.0, -8.0], "text": ""},
        {"type": "resistor", "from": [-0.7, -8.5], "to": [0.6, -8.5]},
        {"type": "rect", "corner1": [-0.7, -8.95], "corner2": [0.6, -8.05], "title": "R"},
        {"type": "port", "at": [-0.7, -8.5], "text": ""},
        {"type": "port", "at": [0.6, -8.5], "text": ""},
        {"type": "line", "from": [1.4, -8.5], "to": [2.7, -8.5]},
        {"type": "rect", "corner1": [1.4, -8.95], "corner2": [2.7, -8.05], "title": "short"},
        {"type": "port", "at": [1.4, -8.5], "text": ""},
        {"type": "port", "at": [2.7, -8.5], "text": ""},
        {"type": "line", "from": [3.5, -8.5], "to": [3.85, -8.5]},
        {"type": "line", "from": [4.45, -8.5], "to": [4.8, -8.5]},
        {"type": "rect", "corner1": [3.5, -8.95], "corner2": [4.8, -8.05], "title": "open"},
        {"type": "port", "at": [3.5, -8.5], "text": ""},
        {"type": "port", "at": [4.8, -8.5], "text": ""},
        {"type": "diode", "from": [6.1, -9.1], "to": [6.1, -7.9]},
        {"type": "rect", "corner1": [5.6, -9.1], "corner2": [6.6, -7.9], "title": "D_up"},
        {"type": "port", "at": [6.1, -7.9], "text": ""},
        {"type": "port", "at": [6.1, -9.1], "text": ""},
        {"type": "diode", "from": [7.9, -9.1], "to": [7.9, -7.9], "fill": "black"},
        {"type": "rect", "corner1": [7.4, -9.1], "corner2": [8.4, -7.9], "instance": "D_down", "model": "model1", "equation": "softplus_bi"},
        {"type": "port", "at": [7.9, -7.9], "text": ""},
        {"type": "port", "at": [7.9, -9.1], "text": ""},
        {"type": "zener", "from": [9.7, -9.1], "to": [9.7, -7.9]},
        {"type": "rect", "corner1": [9.2, -9.1], "corner2": [10.2, -7.9], "title": "Clamp"},
        {"type": "port", "at": [9.7, -7.9], "text": ""},
        {"type": "port", "at": [9.7, -9.1], "text": ""},
        {"type": "line", "from": [11.0, -8.5], "to": [11.2, -8.5]},
        {"type": "dot", "at": [11.2, -8.5]},
        {"type": "line", "from": [11.2, -8.5], "to": [11.2, -8.2]},
        {"type": "line", "from": [11.2, -8.5], "to": [11.2, -8.8]},
        {"type": "diode", "from": [11.2, -8.2], "to": [12.1, -8.2]},
        {"type": "diode", "from": [12.1, -8.8], "to": [11.2, -8.8]},
        {"type": "line", "from": [12.1, -8.2], "to": [12.1, -8.5]},
        {"type": "line", "from": [12.1, -8.8], "to": [12.1, -8.5]},
        {"type": "dot", "at": [12.1, -8.5]},
        {"type": "line", "from": [12.1, -8.5], "to": [12.3, -8.5]},
        {"type": "rect", "corner1": [11.0, -9.15], "corner2": [12.3, -7.85], "title": "D_b2b"},
        {"type": "port", "at": [11.0, -8.5], "text": ""},
        {"type": "port", "at": [12.3, -8.5], "text": ""},
        {"type": "line", "from": [13.1, -8.5], "to": [13.425, -8.5]},
        {"type": "dot", "at": [13.425, -8.5]},
        {"type": "rect", "corner1": [13.1, -9.85], "corner2": [14.65, -7.15], "instance": "Victim", "model": ["SG_PFET 1stk_1rx", "SG_NFET 1stk_1rx"]},
        {"type": "pfet", "drain": [14.3, -8.5], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": -7.15, "bulk": True},
        {"type": "nfet", "drain": [14.3, -8.5], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": -9.85, "bulk": True},
        {"type": "gates", "stub": False},
        {"type": "dot", "at": [14.3, -8.5]},
        {"type": "port", "at": [13.1, -8.5], "text": ""},
        {"type": "port", "at": [14.3, -7.15], "text": ""},
        {"type": "port", "at": [14.3, -9.85], "text": ""},
        {"type": "line", "from": [15.45, -8.5], "to": [15.775, -8.5]},
        {"type": "line", "from": [16.65, -8.02], "to": [16.65, -7.55]},
        {"type": "nfet", "drain": [16.65, -8.02], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": -9.45, "bulk": True},
        {"type": "rect", "corner1": [15.45, -9.45], "corner2": [17.0, -7.55], "title": "Victim (NMOS)"},
        {"type": "port", "at": [15.45, -8.5], "text": ""},
        {"type": "port", "at": [16.65, -7.55], "text": ""},
        {"type": "port", "at": [16.65, -9.45], "text": ""},
        {"type": "line", "from": [17.8, -8.5], "to": [18.125, -8.5]},
        {"type": "line", "from": [19.0, -8.98], "to": [19.0, -9.45]},
        {"type": "pfet", "drain": [19.0, -8.98], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": -7.55, "bulk": True},
        {"type": "rect", "corner1": [17.8, -9.45], "corner2": [19.35, -7.55], "title": "Victim (PMOS)"},
        {"type": "port", "at": [17.8, -8.5], "text": ""},
        {"type": "port", "at": [19.0, -7.55], "text": ""},
        {"type": "port", "at": [19.0, -9.45], "text": ""},
    ],
    "current_labels": {},
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
    nmos_bulk_arrows = []  # NMOS bulk 화살표 반전용 (사용자 지시: NMOS는 채널 반대 방향)

    for e in layout.get("elements", []):
        t = e.get("type")
        if t == "line":
            el = elm.Line().at(pt(e["from"])).to(pt(e["to"]))
            if e.get("ls"):
                el = el.linestyle(e["ls"])
            if e.get("color"):
                el = el.color(e["color"])
            d.add(el)
        elif t == "dot":
            el = elm.Dot().at(pt(e["at"]))
            if e.get("color"):
                el = el.color(e["color"])
            d.add(el)
        elif t == "ground":
            el = elm.Ground().at(pt(e["at"])).scale(ss)
            if e.get("color"):
                el = el.color(e["color"])
            d.add(el)
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
            # 라벨 3계층 (SCHEMATIC_STYLE.md): instance=상자 밖, model/equation=상자 안.
            # 코너 우선순위는 반시계 tl→bl→br→tr.
            OUTC = {"tl": (xa + 0.05, yb + 0.15, 'left'), "bl": (xa + 0.05, ya - 0.45, 'left'),
                    "br": (xb - 0.05, ya - 0.45, 'right'), "tr": (xb - 0.05, yb + 0.15, 'right')}
            INC = [(xa + 0.12, yb - 0.34, 'left'), (xa + 0.12, ya + 0.16, 'left'),
                   (xb - 0.12, ya + 0.16, 'right'), (xb - 0.12, yb - 0.34, 'right')]
            if e.get("instance"):
                lx, ly, ha = OUTC[e.get("instance_loc", "tl")]
                d.add(elm.Label().at((lx, ly)).label(txt(e["instance"]), fontsize=fs - 1,
                                                     color=e.get("color", '#20242a'), halign=ha))
            inner = []
            mdl = e.get("model")
            if mdl:
                inner += [mdl] if isinstance(mdl, str) else list(mdl)
            if e.get("equation"):
                inner.append(e["equation"])
            koff = {"tl": 0, "bl": 1, "br": 2, "tr": 3}[e.get("model_loc", "tl")]
            for i, tv in enumerate(inner):
                sx, sy, ha = INC[(koff + i) % 4]
                d.add(elm.Label().at((sx, sy)).label(txt(tv), fontsize=fs - 2, color=col, halign=ha))
        elif t in ("resistor", "diode", "zener", "sourcei"):
            cls = {"resistor": elm.Resistor, "diode": elm.Diode,
                   "zener": elm.Zener, "sourcei": elm.SourceI}[t]
            el = cls().endpoints(pt(e["from"]), pt(e["to"])).scale(ss)
            if e.get("color"):
                el = el.color(e["color"])
            if e.get("fill"):
                el = el.fill(e["fill"] if isinstance(e["fill"], str) else True)
            if e.get("label"):
                el = el.label(txt(e["label"]), loc=e.get("loc", "top"), fontsize=fs)
            d.add(el)
        elif t == "port":
            x, y = pt(e["at"])
            lx, ly = e.get("lofst", [-0.75, 0])
            pd = elm.Dot(open=True).at((x, y))
            if e.get("color"):
                pd = pd.color(e["color"])
            d.add(pd)
            d.add(elm.Label().at((x + lx, y + ly)).label(e.get("text", ""), fontsize=fs,
                                                        color=e.get("color", '#20242a')))
        elif t in ("pfet", "nfet"):
            cls = elm.PFet if t == "pfet" else elm.NFet
            el = cls(bulk=True) if e.get("bulk") else cls()
            if e.get("rot"):
                el = el.theta(e["rot"])
            if e.get("flip"):
                el = el.flip()
            lloc = e.get("loc", "right")
            q = d.add(el.at(pt(e["drain"])).anchor('drain').scale(ss)
                      .label(e.get("label", ""), loc=lloc, fontsize=fs))
            fets[t] = q
            src = q.absanchors['source']
            if e.get("bulk"):
                blk = q.absanchors['bulk']
                d.add(elm.Line().at((blk.x, blk.y)).to((src.x, src.y)))
                if t == "nfet":
                    nmos_bulk_arrows.append((blk.x, blk.y))
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
                elif e.get("stub", True):
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
    svg = data.decode('utf-8') if isinstance(data, bytes) else data
    for bx, by in nmos_bulk_arrows:
        svg = _flip_nmos_bulk_arrow(svg, bx, by)
    return svg


def _flip_nmos_bulk_arrow(svg, bx, by, S=32.4):
    """NMOS bulk 화살촉(채널 방향)을 좌우 반전 — 자기 중심 기준 x 미러."""
    pat = _re.compile(r'd="M ([-\d.]+) ([-\d.]+) L ([-\d.]+) ([-\d.]+) L ([-\d.]+) ([-\d.]+) Z"')

    def rep(m):
        xs = [float(m.group(i)) for i in (1, 3, 5)]
        ys = [float(m.group(i)) for i in (2, 4, 6)]
        cx, cy = sum(xs) / 3 / S, -sum(ys) / 3 / S
        if abs(cy - by) < 0.15 and (bx - 0.6) < cx < bx:
            mx = sum(xs) / 3
            nx = [2 * mx - x for x in xs]
            return 'd="M {} {} L {} {} L {} {} Z"'.format(nx[0], ys[0], nx[1], ys[1], nx[2], ys[2])
        return m.group(0)

    return pat.sub(rep, svg)
