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
    "annotations": False,  # 3계층 라벨 외 주석(노드 전압·전류) 삭제 — 사용자 지시 2026-07-27
    "nodes": {
        "N1": {"xy": [-0.2, 3.0], "ofst": [-1.5, 0.63]},
        "IN": {"xy": [2.6, 3.0], "ofst": [0.0, 0.75]},
        "N2": {"xy": [-0.2, 6.0], "ofst": [-1.3, 0.525]},
        "N3": {"xy": [7.1, 6.0], "ofst": [0.3, -1.17]},
        "N3B": {"xy": [7.1, 0.0], "ofst": [0.3, 0.525]},
        "VSSR": {"xy": [0.9, 0.0], "ofst": [-0.6, 0.525]},
    },
    "elements": [
        {"type": "port", "at": [-3.0, 6.0], "text": "", "net": "VDD"},
        {"type": "port", "at": [-3.0, 3.0], "text": "", "net": "IO"},
        {"type": "port", "at": [-3.0, 0.0], "text": "", "net": "VSS"},
        {"type": "ground", "at": [-3.0, 0.0]},
        {"type": "line", "from": [-3.8, 6.0], "to": [-3.0, 6.0], "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, 3.0], "to": [-3.0, 3.0], "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, 0.0], "to": [-3.0, 0.0], "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, -3.0], "to": [-3.0, -3.0], "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, 5.5], "to": [-3.8, 6.0], "color": "#b0b6bf"},
        {"type": "sourcei", "from": [-3.8, 4.5], "to": [-3.8, 5.5], "color": "#b0b6bf", "instance_id": "XI_ESD (IO→VDD) (open)"},
        {"type": "ground", "at": [-3.8, 4.5], "color": "#b0b6bf"},
        {"type": "rect", "corner1": [-4.3, 4.0], "corner2": [-3.3, 5.55], "instance": "XI_ESD (IO→VDD) (open)", "instance_loc": "br", "cell": "i_esd", "params": {"I": "I_sweep"}, "enabled": False, "color": "#b0b6bf"},
        {"type": "port", "at": [-3.8, 5.55], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, 2.5], "to": [-3.8, 3.0]},
        {"type": "sourcei", "from": [-3.8, 1.5], "to": [-3.8, 2.5], "instance_id": "XI_ESD (IO→VSS)"},
        {"type": "ground", "at": [-3.8, 1.5]},
        {"type": "rect", "corner1": [-4.3, 1.0], "corner2": [-3.3, 2.55], "instance": "XI_ESD (IO→VSS)", "instance_loc": "br", "cell": "i_esd", "equation": "I: 0→2A sweep", "params": {"I": "I_sweep"}},
        {"type": "port", "at": [-3.8, 2.55], "text": ""},
        {"type": "line", "from": [-3.8, -0.5], "to": [-3.8, 0.0], "color": "#b0b6bf"},
        {"type": "sourcei", "from": [-3.8, -1.5], "to": [-3.8, -0.5], "color": "#b0b6bf", "instance_id": "XI_ESD (GND→VSS) (open)"},
        {"type": "ground", "at": [-3.8, -1.5], "color": "#b0b6bf"},
        {"type": "rect", "corner1": [-4.3, -2.0], "corner2": [-3.3, -0.45], "instance": "XI_ESD (GND→VSS) (open)", "instance_loc": "bl", "cell": "i_esd", "params": {"I": "I_sweep"}, "enabled": False, "color": "#b0b6bf"},
        {"type": "port", "at": [-3.8, -0.45], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [-3.8, -3.5], "to": [-3.8, -3.0], "color": "#b0b6bf"},
        {"type": "sourcei", "from": [-3.8, -4.5], "to": [-3.8, -3.5], "color": "#b0b6bf", "instance_id": "XI_ESD (GND→MVSS) (open)"},
        {"type": "ground", "at": [-3.8, -4.5], "color": "#b0b6bf"},
        {"type": "rect", "corner1": [-4.3, -5.0], "corner2": [-3.3, -3.45], "instance": "XI_ESD (GND→MVSS) (open)", "instance_loc": "bl", "cell": "i_esd", "params": {"I": "I_sweep"}, "enabled": False, "color": "#b0b6bf"},
        {"type": "port", "at": [-3.8, -3.45], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [-3.0, 6.0], "to": [-2.6, 6.0]},
        {"type": "resistor", "from": [-2.6, 6.0], "to": [-0.6, 6.0], "instance_id": "XRvdd_rdl"},
        {"type": "rect", "corner1": [-2.25, 5.55], "corner2": [-0.95, 6.45], "instance": "XRvdd_rdl", "cell": "r", "model": "metal", "equation": "0.1Ω", "params": {"R": 0.1}},
        {"type": "port", "at": [-2.25, 6.0], "text": ""},
        {"type": "port", "at": [-0.95, 6.0], "text": ""},
        {"type": "line", "from": [-0.6, 6.0], "to": "N2"},
        {"type": "line", "from": [-3.0, 3.0], "to": [-2.6, 3.0]},
        {"type": "resistor", "from": [-2.6, 3.0], "to": [-0.6, 3.0], "instance_id": "XRio_rdl"},
        {"type": "rect", "corner1": [-2.25, 2.55], "corner2": [-0.95, 3.45], "instance": "XRio_rdl", "cell": "r", "model": "metal", "equation": "0.1Ω", "params": {"R": 0.1}},
        {"type": "port", "at": [-2.25, 3.0], "text": ""},
        {"type": "port", "at": [-0.95, 3.0], "text": ""},
        {"type": "line", "from": [-0.6, 3.0], "to": "N1"},
        {"type": "line", "from": [-3.0, 0.0], "to": [-2.6, 0.0]},
        {"type": "resistor", "from": [-2.6, 0.0], "to": [-0.6, 0.0], "instance_id": "XRvss_rdl"},
        {"type": "rect", "corner1": [-2.25, -0.45], "corner2": [-0.95, 0.45], "instance": "XRvss_rdl", "cell": "r", "model": "metal", "equation": "0.1Ω", "params": {"R": 0.1}},
        {"type": "port", "at": [-2.25, 0.0], "text": ""},
        {"type": "port", "at": [-0.95, 0.0], "text": ""},
        {"type": "line", "from": [-0.6, 0.0], "to": [5.1, 0.0]},
        {"type": "diode", "from": "N1", "to": "N2", "instance_id": "XD_up"},
        {"type": "rect", "corner1": [-0.9, 3.9], "corner2": [0.5, 5.1], "instance": "XD_up", "cell": "d_up", "model": "esdvpnp", "equation": "meas(x1)", "params": {"size": "x1"}, "roles": ["io_primary_up", "io_cap_contributor"]},
        {"type": "port", "at": [-0.2, 5.1], "text": ""},
        {"type": "port", "at": [-0.2, 3.9], "text": ""},
        {"type": "diode", "from": [-0.2, 0.0], "to": "N1", "fill": "black", "instance_id": "XD_down"},
        {"type": "rect", "corner1": [-0.9, 0.9], "corner2": [0.5, 2.1], "instance": "XD_down", "cell": "d_down", "model": "esdndsx", "equation": "meas(x1)", "params": {"size": "x1"}, "roles": ["io_primary_down", "io_cap_contributor"]},
        {"type": "port", "at": [-0.2, 2.1], "text": ""},
        {"type": "port", "at": [-0.2, 0.9], "text": ""},
        {"type": "dot", "at": "N1"},
        {"type": "dot", "at": "N2"},
        {"type": "dot", "at": [-0.2, 0.0]},
        {"type": "line", "from": "N2", "to": [5.1, 6.0]},
        {"type": "resistor", "from": [5.1, 6.0], "to": "N3", "instance_id": "XRDD_un1"},
        {"type": "rect", "corner1": [5.55, 5.55], "corner2": [6.65, 6.45], "instance": "XRDD_un1", "cell": "r", "model": "metal", "equation": "rdd(L,W)", "params": {"R": "rdd(L,W)", "L": "L", "W": "W"}},
        {"type": "port", "at": [5.55, 6.0], "text": ""},
        {"type": "port", "at": [6.65, 6.0], "text": ""},
        {"type": "resistor", "from": [5.1, 0.0], "to": "N3B", "instance_id": "XRDD_dn1"},
        {"type": "rect", "corner1": [5.55, -0.45], "corner2": [6.65, 0.45], "instance": "XRDD_dn1", "cell": "r", "model": "metal", "equation": "rdd(L,W)", "params": {"R": "rdd(L,W)", "L": "L", "W": "W"}},
        {"type": "port", "at": [5.55, 0.0], "text": ""},
        {"type": "port", "at": [6.65, 0.0], "text": ""},
        {"type": "zener", "from": "N3B", "to": "N3", "instance_id": "XClamp"},
        {"type": "rect", "corner1": [6.4, 0.9], "corner2": [7.8, 5.1], "instance": "XClamp", "cell": "clamp", "model": "nfet_clamp", "equation": "meas(x2)", "params": {"size": "x2"}},
        {"type": "port", "at": [7.1, 5.1], "text": ""},
        {"type": "port", "at": [7.1, 0.9], "text": ""},
        {"type": "dot", "at": "N3"},
        {"type": "dot", "at": "N3B"},
        {"type": "line", "from": "N1", "to": [0.2, 3.0]},
        {"type": "resistor", "from": [0.2, 3.0], "to": [2.2, 3.0], "instance_id": "XResd"},
        {"type": "rect", "corner1": [0.55, 2.55], "corner2": [1.85, 3.45], "instance": "XResd", "cell": "r", "model": "rmres", "equation": "500Ω", "params": {"R": 500}},
        {"type": "port", "at": [0.55, 3.0], "text": ""},
        {"type": "port", "at": [1.85, 3.0], "text": ""},
        {"type": "line", "from": [2.2, 3.0], "to": [2.6, 3.0]},
        {"type": "diode", "from": [2.6, 3.0], "to": [2.6, 6.0], "instance_id": "XD_up2"},
        {"type": "rect", "corner1": [1.9, 3.9], "corner2": [3.3, 5.1], "instance": "XD_up2", "cell": "d_up", "model": "esdvpnp", "equation": "meas(x1/10)", "params": {"size": "x1/10"}},
        {"type": "port", "at": [2.6, 5.1], "text": ""},
        {"type": "port", "at": [2.6, 3.9], "text": ""},
        {"type": "diode", "from": [2.6, 0.0], "to": [2.6, 3.0], "fill": "black", "instance_id": "XD_down2"},
        {"type": "rect", "corner1": [1.9, 0.9], "corner2": [3.3, 2.1], "instance": "XD_down2", "cell": "d_down", "model": "esdndsx", "equation": "meas(x1/10)", "params": {"size": "x1/10"}},
        {"type": "port", "at": [2.6, 2.1], "text": ""},
        {"type": "port", "at": [2.6, 0.9], "text": ""},
        {"type": "dot", "at": [2.6, 3.0]},
        {"type": "dot", "at": [2.6, 6.0]},
        {"type": "dot", "at": [2.6, 0.0]},
        {"type": "line", "from": [2.6, 3.0], "to": [4.225, 3.0]},
        {"type": "line", "from": [4.225, 3.0], "to": [4.225, 2.52]},
        {"type": "rect", "corner1": [3.4, 0.9], "corner2": [5.45, 5.1], "instance": "XVictim", "cell": "victim_n", "model": "SG_NFET 1stk_1rx", "equation": None, "role": "soa_monitor", "params": {}},
        {"type": "nfet", "drain": [5.1, 3.0], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": 0.0, "bulk": True, "instance_id": "XVictim"},
        {"type": "line", "from": [5.1, 3.0], "to": [5.1, 6.0]},
        {"type": "dot", "at": [5.1, 6.0]},
        {"type": "dot", "at": [5.1, 0.0]},
        {"type": "port", "at": [3.4, 3.0], "text": ""},
        {"type": "port", "at": [5.1, 5.1], "text": ""},
        {"type": "port", "at": [5.1, 0.9], "text": ""},
        {"type": "line", "from": "N3B", "to": [7.9, 0.0]},
        {"type": "dot", "at": [7.9, 0.0]},
        {"type": "line", "from": [7.9, 0.0], "to": [8.25, 0.0], "color": "#b0b6bf"},
        {"type": "dot", "at": [8.25, 0.0], "color": "#b0b6bf"},
        {"type": "line", "from": [8.25, 0.0], "to": [8.25, 0.3], "color": "#b0b6bf"},
        {"type": "line", "from": [8.25, 0.0], "to": [8.25, -0.3], "color": "#b0b6bf"},
        {"type": "diode", "from": [8.25, 0.3], "to": [9.15, 0.3], "color": "#b0b6bf", "instance_id": "XD_b2b (open)"},
        {"type": "diode", "from": [9.15, -0.3], "to": [8.25, -0.3], "color": "#b0b6bf", "instance_id": "XD_b2b (open)"},
        {"type": "rect", "corner1": [8.05, -0.65], "corner2": [9.35, 0.65], "instance": "XD_b2b (open)", "cell": "d_b2b", "variant": "horizontal", "params": {}, "enabled": False, "color": "#b0b6bf"},
        {"type": "port", "at": [8.05, 0.0], "text": "", "color": "#b0b6bf"},
        {"type": "port", "at": [9.35, 0.0], "text": "", "color": "#b0b6bf"},
        {"type": "line", "from": [9.15, 0.3], "to": [9.15, 0.0], "color": "#b0b6bf"},
        {"type": "line", "from": [9.15, -0.3], "to": [9.15, 0.0], "color": "#b0b6bf"},
        {"type": "dot", "at": [9.15, 0.0], "color": "#b0b6bf"},
        {"type": "line", "from": [9.15, 0.0], "to": [9.5, 0.0], "color": "#b0b6bf"},
        {"type": "dot", "at": [9.5, 0.0]},
        {"type": "line", "from": [9.5, 0.0], "to": [10.3, 0.0]},
        {"type": "port", "at": [10.3, 0.0], "text": "", "net": "VSS2"},
        {"type": "line", "from": [9.5, 3.0], "to": [10.3, 3.0]},
        {"type": "port", "at": [10.3, 3.0], "text": "", "net": "IO2"},
        {"type": "line", "from": [9.5, 6.0], "to": [10.3, 6.0]},
        {"type": "port", "at": [10.3, 6.0], "text": "", "net": "VDD2"},
        {"type": "line", "from": [10.3, 0.0], "to": [10.3, -0.825]},
        {"type": "dot", "at": [10.3, -0.825]},
        {"type": "line", "from": [10.3, -0.825], "to": [10.0, -0.825]},
        {"type": "line", "from": [10.3, -0.825], "to": [10.6, -0.825]},
        {"type": "diode", "from": [10.0, -2.175], "to": [10.0, -0.825], "instance_id": "XD_b2b_m2"},
        {"type": "diode", "from": [10.6, -0.825], "to": [10.6, -2.175], "instance_id": "XD_b2b_m2"},
        {"type": "rect", "corner1": [9.75, -2.4], "corner2": [10.85, -0.6], "instance": "XD_b2b_m2", "cell": "d_b2b", "variant": "vertical", "params": {}},
        {"type": "port", "at": [10.3, -0.6], "text": ""},
        {"type": "port", "at": [10.3, -2.4], "text": ""},
        {"type": "line", "from": [10.0, -2.175], "to": [10.3, -2.175]},
        {"type": "line", "from": [10.6, -2.175], "to": [10.3, -2.175]},
        {"type": "dot", "at": [10.3, -2.175]},
        {"type": "line", "from": [10.3, -2.175], "to": [10.3, -3.0]},
        {"type": "dot", "at": [10.3, -3.0]},
        {"type": "port", "at": [-3.0, -3.0], "text": "", "net": "MVSS"},
        {"type": "line", "from": [-3.0, -3.0], "to": [10.3, -3.0]},
        {"type": "line", "from": [7.1, 0.0], "to": [7.1, -0.825]},
        {"type": "dot", "at": [7.1, -0.825]},
        {"type": "line", "from": [7.1, -0.825], "to": [6.8, -0.825]},
        {"type": "line", "from": [7.1, -0.825], "to": [7.4, -0.825]},
        {"type": "diode", "from": [6.8, -2.175], "to": [6.8, -0.825], "instance_id": "XD_b2b_m"},
        {"type": "diode", "from": [7.4, -0.825], "to": [7.4, -2.175], "instance_id": "XD_b2b_m"},
        {"type": "rect", "corner1": [6.55, -2.4], "corner2": [7.65, -0.6], "instance": "XD_b2b_m", "instance_loc": "bl", "cell": "d_b2b", "variant": "vertical", "params": {}},
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

# Subcircuit Set — cell별 개별 canvas로 서빙 (/api/schematic/library 목록,
# /api/schematic/library/{id} SVG). models = 해당 cell에 사용할 수 있는 process model 목록.
_LIB_COMMON = {"unit": 2, "fontsize": 9, "symbol_scale": 0.64, "annotations": False,
               "nodes": {}, "current_labels": {}}

LIBRARY_CELLS = [
    {"id": "i_esd", "name": "I_ESD", "models": [], "elements": [
        {"type": "line", "from": [-3.8, -8.05], "to": [-3.8, -8.0]},
        {"type": "sourcei", "from": [-3.8, -9.05], "to": [-3.8, -8.05]},
        {"type": "ground", "at": [-3.8, -9.05]},
        {"type": "rect", "corner1": [-4.3, -9.55], "corner2": [-3.3, -8.0], "title": "I_ESD"},
        {"type": "port", "at": [-3.8, -8.0], "text": ""},
    ]},
    {"id": "gnd", "name": "GND", "models": [], "elements": [
        {"type": "line", "from": [-2.0, -8.0], "to": [-2.0, -9.05]},
        {"type": "ground", "at": [-2.0, -9.05]},
        {"type": "rect", "corner1": [-2.5, -9.55], "corner2": [-1.5, -8.0], "title": "GND"},
        {"type": "port", "at": [-2.0, -8.0], "text": ""},
    ]},
    {"id": "r", "name": "R", "models": ["rmres", "metal"], "elements": [
        {"type": "resistor", "from": [-0.7, -8.5], "to": [0.6, -8.5]},
        {"type": "rect", "corner1": [-0.7, -8.95], "corner2": [0.6, -8.05], "title": "R"},
        {"type": "port", "at": [-0.7, -8.5], "text": ""},
        {"type": "port", "at": [0.6, -8.5], "text": ""},
    ]},
    {"id": "short", "name": "short", "models": [], "elements": [
        {"type": "line", "from": [1.4, -8.5], "to": [2.7, -8.5]},
        {"type": "rect", "corner1": [1.4, -8.95], "corner2": [2.7, -8.05], "title": "short"},
        {"type": "port", "at": [1.4, -8.5], "text": ""},
        {"type": "port", "at": [2.7, -8.5], "text": ""},
    ]},
    {"id": "open", "name": "open", "models": [], "elements": [
        {"type": "line", "from": [3.5, -8.5], "to": [3.85, -8.5]},
        {"type": "line", "from": [4.45, -8.5], "to": [4.8, -8.5]},
        {"type": "rect", "corner1": [3.5, -8.95], "corner2": [4.8, -8.05], "title": "open"},
        {"type": "port", "at": [3.5, -8.5], "text": ""},
        {"type": "port", "at": [4.8, -8.5], "text": ""},
    ]},
    {"id": "d_up", "cap_model": "D1", "name": "D_up", "models": ["esdvpnp", "esdvpnp_rg"], "elements": [
        {"type": "diode", "from": [6.1, -9.1], "to": [6.1, -7.9]},
        {"type": "rect", "corner1": [5.6, -9.1], "corner2": [6.6, -7.9], "title": "D_up", "model": "esdvpnp", "equation": "softplus_bi"},
        {"type": "port", "at": [6.1, -7.9], "text": ""},
        {"type": "port", "at": [6.1, -9.1], "text": ""},
    ]},
    {"id": "d_down", "cap_model": "D1", "name": "D_down", "models": ["esdndsx", "esdndsx_rg", "esdnwsx"], "elements": [
        {"type": "diode", "from": [7.9, -9.1], "to": [7.9, -7.9], "fill": "black"},
        {"type": "rect", "corner1": [7.4, -9.1], "corner2": [8.4, -7.9], "title": "D_down", "model": "esdndsx", "equation": "softplus_bi"},
        {"type": "port", "at": [7.9, -7.9], "text": ""},
        {"type": "port", "at": [7.9, -9.1], "text": ""},
    ]},
    {"id": "clamp", "cap_model": "D2", "name": "Clamp", "models": ["nfet_clamp"], "elements": [
        {"type": "zener", "from": [9.7, -9.1], "to": [9.7, -7.9]},
        {"type": "rect", "corner1": [9.2, -9.1], "corner2": [10.2, -7.9], "title": "Clamp", "model": "nfet_clamp", "equation": "softplus_bi"},
        {"type": "port", "at": [9.7, -7.9], "text": ""},
        {"type": "port", "at": [9.7, -9.1], "text": ""},
    ]},
    {"id": "d_b2b", "cap_model": "D1", "name": "D_b2b", "models": ["essvpnp ×2"], "elements": [
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
    ]},
    {"id": "victim_n", "name": "Victim (NMOS)", "models": ["SG_NFET 1stk_1rx"], "elements": [
        {"type": "line", "from": [15.45, -8.5], "to": [15.775, -8.5]},
        {"type": "line", "from": [16.65, -8.02], "to": [16.65, -7.55]},
        {"type": "nfet", "drain": [16.65, -8.02], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": -9.45, "bulk": True},
        {"type": "rect", "corner1": [15.45, -9.45], "corner2": [17.0, -7.55], "title": "Victim (NMOS)", "model": "SG_NFET 1stk_1rx"},
        {"type": "port", "at": [15.45, -8.5], "text": ""},
        {"type": "port", "at": [16.65, -7.55], "text": ""},
        {"type": "port", "at": [16.65, -9.45], "text": ""},
    ]},
    {"id": "victim_p", "name": "Victim (PMOS)", "models": ["SG_PFET 1stk_1rx"], "elements": [
        {"type": "line", "from": [17.8, -8.5], "to": [18.125, -8.5]},
        {"type": "line", "from": [19.0, -8.98], "to": [19.0, -9.45]},
        {"type": "pfet", "drain": [19.0, -8.98], "label": "", "loc": "right", "rot": 180, "flip": True, "rail_y": -7.55, "bulk": True},
        {"type": "rect", "corner1": [17.8, -9.45], "corner2": [19.35, -7.55], "title": "Victim (PMOS)", "model": "SG_PFET 1stk_1rx"},
        {"type": "port", "at": [17.8, -8.5], "text": ""},
        {"type": "port", "at": [19.0, -7.55], "text": ""},
        {"type": "port", "at": [19.0, -9.45], "text": ""},
    ]},
]


def build_cell_svg(cell_id):
    """라이브러리 cell 하나를 개별 SVG로 렌더 (없으면 None)."""
    for c in LIBRARY_CELLS:
        if c["id"] == cell_id:
            layout = dict(_LIB_COMMON)
            layout["elements"] = c["elements"]
            return build_svg(2.56, 1415.232, 350.0, None, layout)
    return None


def validate_mapping(layout=None):
    """instance→cell 매핑 검증: cell 존재·model이 cell.models 원소인지(목록 비면 무제약).
    layout 미지정 시 표시 중 레이아웃(load_layout — custom 포함)을 검사한다."""
    if layout is None:
        layout = load_layout()[0]
    cells = {c["id"]: c for c in LIBRARY_CELLS}
    rows, issues = [], []
    for e in layout.get("elements", []):
        if e.get("type") == "rect" and e.get("instance"):
            inst, cid = e["instance"], e.get("cell")
            mdl = e.get("model")
            mdls = [mdl] if isinstance(mdl, str) else list(mdl or [])
            rows.append({"instance": inst, "cell": cid, "variant": e.get("variant"),
                         "model": mdls, "params": e.get("params", {})})
            if not cid:
                issues.append(inst + ": cell 참조 없음")
            elif cid not in cells:
                issues.append("{}: 미지 cell '{}'".format(inst, cid))
            else:
                allowed = cells[cid]["models"]
                if allowed:
                    for m in mdls:
                        if m not in allowed:
                            issues.append("{}: model '{}' ∉ {}.models {}".format(inst, m, cid, allowed))
    return {"instances": rows, "issues": issues}


_FET_OFFSET_CACHE = {}


def _fet_element(kind, rot=0, flip=False, bulk=False):
    """schemdraw FET element 생성 — 렌더러·fet_anchors 공용 (이슈 #9 P0-5).

    theta는 rot 생략/0에서도 **무조건 명시** 호출한다: schemdraw는 theta 미지정 시
    도면 진행 방향(dwgtheta)을 상속하므로, 공유 Drawing(build_svg)과 빈 Drawing
    (fet_anchors)에서 기하가 갈라질 수 있다(검증 워크플로우 발견 2026-07-28)."""
    cls = elm.PFet if kind == "pfet" else elm.NFet
    el = cls(bulk=True) if bulk else cls()
    el = el.theta(rot or 0)
    if flip:
        el = el.flip()
    return el


def fet_anchors(kind, drain, rot=0, flip=False, scale=1.0, bulk=False):
    """FET pin 절대좌표 {drain, source, gate[, bulk]} — 렌더러·netlist 추출기 공용 (이슈 #9 P0-5).

    렌더러와 동일하게 schemdraw element를 실제 배치해 absanchors를 읽으므로
    rot/flip/scale 어떤 조합에서도 두 경로의 기하가 어긋날 수 없다.
    (drain 기준 상대 offset은 (kind, rot, flip, scale, bulk)별로 캐시)"""
    key = (kind, rot or 0, bool(flip), round(float(scale), 6), bool(bulk))
    if key not in _FET_OFFSET_CACHE:
        d = schemdraw.Drawing(show=False)
        q = d.add(_fet_element(kind, rot, flip, bulk).at((0.0, 0.0)).anchor('drain').scale(scale))
        names = ('drain', 'source', 'gate') + (('bulk',) if bulk else ())
        _FET_OFFSET_CACHE[key] = tuple((n, (q.absanchors[n].x, q.absanchors[n].y))
                                       for n in names)
    x0, y0 = drain
    return {n: (x0 + ox, y0 + oy) for n, (ox, oy) in _FET_OFFSET_CACHE[key]}


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


def build_svg(x1=None, x2=None, L=None, op=None, layout=None, pset=None):
    """Render the layout (saved/custom/default) to SVG. op = node voltages/currents.
    라벨 치환은 pset(자유 파라미터 dict) 전 기호 + rvdd — x1/x2/L kwarg는 legacy."""
    if layout is None:
        layout, _ = load_layout()
    from server import model as _M
    p = {k: v["default"] for k, v in _M.PARAM_META.items()}
    for k, v in (("x1", x1), ("x2", x2), ("L", L)):
        if v is not None:
            p[k] = float(v)
    if pset:
        p.update(pset)
    rvdd = _M.rdd_r(p["L"], p.get("W", _M.RDD_W0))  # 금속 정본 = model.rdd_r (이슈 #11)
    subst = {k: "{:g}".format(v) for k, v in p.items()}
    subst["rvdd"] = "{:.3g}".format(rvdd)

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
    d.config(unit=layout.get("unit", 2), fontsize=layout.get("fontsize", 9),
             lw=layout.get("lw", 1.0))  # 선 굵기 1/2 (기본 2)
    fs = layout.get("fontsize", 9)
    ss = layout.get("symbol_scale", 1.0)  # 심볼 몸체 배율 — 2단자 소자 endpoints 스팬은 불변,
    #                                       FET pin(source/gate)은 scale 종속 (fet_anchors가 원천)
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
                # type 이름(라이브러리) — instance와 동일하게 상자 밖 좌상단
                d.add(elm.Label().at((xa - 0.1, yb + 0.24)).label(txt(e["title"]), fontsize=fs - 1,
                                                                  color=col, halign='left'))
            # 라벨 3계층 (SCHEMATIC_STYLE.md): instance=상자 밖, model/equation=상자 안.
            # 코너 우선순위는 반시계 tl→bl→br→tr.
            # 라벨은 외곽선 스트로크와 겹치지 않게 (좌측 들여쓰기 없음 — 좌변 정렬).
            # schemdraw .label() 자체 x오프셋 +0.10을 앵커에서 상쇄.
            OUTC = {"tl": (xa - 0.1, yb + 0.24, 'left'), "bl": (xa - 0.1, ya - 0.3, 'left'),
                    "br": (xb - 0.1, ya - 0.3, 'right'), "tr": (xb - 0.1, yb + 0.24, 'right')}
            INC = [(xa - 0.09, yb - 0.01, 'left'), (xa - 0.09, ya + 0.12, 'left'),
                   (xb - 0.11, ya + 0.12, 'right'), (xb - 0.11, yb - 0.01, 'right')]
            if e.get("instance"):
                lx, ly, ha = OUTC[e.get("instance_loc", "tl")]
                d.add(elm.Label().at((lx, ly)).label(txt(e["instance"]), fontsize=fs - 1,
                                                     color=e.get("color", '#20242a'), halign=ha))
            mdl = e.get("model")
            inner = ([mdl] if isinstance(mdl, str) else list(mdl)) if mdl else []
            if e.get("equation"):
                inner.append(e["equation"])
            if e.get("role") == "soa_monitor":
                inner.append("SOA monitor · no equation")  # 이슈 #10 §7 표시
            # model/equation 여러 개면 한 코너에서 위→아래 순차 스택 (코너 분산 금지)
            koff = {"tl": 0, "bl": 1, "br": 2, "tr": 3}[e.get("model_loc", "tl")]
            sx, sy, ha = INC[koff]
            step = -0.18 if koff in (0, 3) else 0.18
            for i, tv in enumerate(inner):
                d.add(elm.Label().at((sx, sy + step * i)).label(txt(tv), fontsize=fs - 3,
                                                                color=col, halign=ha))
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
            # _fet_element: theta 명시 → netlist.fet_anchors와 동일 기하 보장 (P0-5)
            el = _fet_element(t, e.get("rot", 0), e.get("flip"), e.get("bulk"))
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

    # node names + operating-point voltages (파란 주석) — annotations=False면 생략
    for name, nd in (nodes.items() if layout.get("annotations", True) else []):
        x, y = nd["xy"]
        dx, dy = nd.get("ofst", [0.15, 0.3])
        text = name
        if op and name in op:
            text = "{} {:.2f}V".format(name, op[name])
        d.add(elm.Label().at((x + dx, y + dy)).label(text, fontsize=fs - 1, color=ACC))
    cl = layout.get("current_labels", {}) if layout.get("annotations", True) else {}
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
