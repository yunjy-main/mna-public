# -*- coding: utf-8 -*-
"""Schematic renderer (schemdraw 0.15, server-side SVG, offline).

Draws the strengthened topology — VDD/IO/VSS rails, D_up/D_down (model1),
Clamp (model2), R devices (Rio/Rvdd/Resd) and the victim inverter — with
optional operating-point annotations (node voltages / currents).
"""
import schemdraw
import schemdraw.elements as elm

ACC = '#0b57a4'   # 전압 주석(푸른계열)
CUR = '#00796b'   # 전류 주석
MUT = '#5b6673'

IO = (0.0, 3.0)
N1 = (3.0, 3.0)
N2 = (3.0, 6.0)
N3 = (7.0, 6.0)
OUT = (10.5, 3.0)
SRCX = -1.7
RESDY = 0.8
RCOL = 9.6


def _vlabel(d, xy, text, ofst=(0.15, 0.25)):
    d.add(elm.Label().at((xy[0] + ofst[0], xy[1] + ofst[1])).label(text, fontsize=8, color=ACC))


def build_svg(x1, x2, L=350.0, op=None, iv=None):
    """Return schematic SVG (utf-8 str). op: dict of node voltages + currents."""
    rvdd = 0.5 * L / 350.0
    d = schemdraw.Drawing(backend='svg')
    d.config(unit=2, fontsize=9)

    # rails
    d.add(elm.Line().at((SRCX, 0)).to((OUT[0], 0)))
    d.add(elm.Ground().at((SRCX, 0)))
    d.add(elm.Label().at((OUT[0] + 0.25, 0)).label('VSS', fontsize=9, color=MUT))
    d.add(elm.Line().at(N3).to((OUT[0], N3[1])))
    d.add(elm.Label().at((OUT[0] + 0.25, N3[1])).label('VDD', fontsize=9, color=MUT))

    # stress source: VSS -> IO (positive stress into the pad)
    d.add(elm.SourceI().endpoints((SRCX, 0), (SRCX, IO[1])).label('I_ESD', loc='left', fontsize=9))
    d.add(elm.Line().at((SRCX, IO[1])).to(IO))

    # R devices + diodes + clamp
    d.add(elm.Dot().at(IO))
    d.add(elm.Resistor().endpoints(IO, N1).label('Rio 0.1Ω', loc='top', fontsize=9))
    d.add(elm.Dot().at(N1))
    d.add(elm.Diode().endpoints(N1, N2).label('D_up x1={:g}'.format(x1), loc='bottom', fontsize=9))
    d.add(elm.Dot().at(N2))
    d.add(elm.Resistor().endpoints(N2, N3).label(
        'Rvdd {:.3g}Ω (L={:g}µm)'.format(rvdd, L), loc='top', fontsize=9))
    d.add(elm.Dot().at(N3))
    d.add(elm.Zener().endpoints(N3, (N3[0], 0)).label('Clamp x2={:g}'.format(x2), loc='bottom', fontsize=9))
    d.add(elm.Diode().endpoints((N1[0], 0), N1).label('D_down', loc='bottom', fontsize=9))

    # Resd route: IO -> down -> right -> up -> OUT
    d.add(elm.Line().at(IO).to((IO[0], RESDY)))
    d.add(elm.Line().at((IO[0], RESDY)).to((4.0, RESDY)))
    d.add(elm.Resistor().endpoints((4.0, RESDY), (6.4, RESDY)).label('Resd 500Ω', loc='bottom', fontsize=9))
    d.add(elm.Line().at((6.4, RESDY)).to((RCOL, RESDY)))
    d.add(elm.Line().at((RCOL, RESDY)).to((RCOL, OUT[1])))
    d.add(elm.Line().at((RCOL, OUT[1])).to(OUT))
    d.add(elm.Dot().at(OUT))

    # victim inverter (common drain at OUT, gates tied right)
    pf = d.add(elm.PFet().at(OUT).anchor('drain').label('PMOS', loc='right', fontsize=9))
    d.add(elm.Line().at((OUT[0], OUT[1] + 1.5)).to((OUT[0], N3[1])))
    nf = d.add(elm.NFet().at(OUT).anchor('drain').label('NMOS', loc='right', fontsize=9))
    d.add(elm.Line().at((OUT[0], OUT[1] - 1.5)).to((OUT[0], 0)))
    g1, g2 = pf.absanchors['gate'], nf.absanchors['gate']
    d.add(elm.Line().at((g1.x, g1.y)).to((g2.x, g2.y)))
    d.add(elm.Line().at((g1.x, (g1.y + g2.y) / 2)).to((g1.x + 0.6, (g1.y + g2.y) / 2)))
    d.add(elm.Label().at((g1.x + 0.7, (g1.y + g2.y) / 2)).label('V_IN=0', fontsize=8, color=MUT))

    # node names / operating point
    names = {'IO': IO, 'N1': N1, 'N2': N2, 'N3': N3, 'OUT': OUT}
    for name, xy in names.items():
        if op and name in op:
            _vlabel(d, xy, '{} {:.2f}V'.format(name, op[name]))
        else:
            _vlabel(d, xy, name)
    if op and 'i' in op:
        d.add(elm.Label().at((1.5, 3.65)).label('I={:.2f}A'.format(op['i']), fontsize=8, color=CUR))
    if op and 'iv' in op:
        d.add(elm.Label().at((5.2, 0.25)).label('I_v={:.2f}mA'.format(1000 * op['iv']), fontsize=8, color=CUR))

    data = d.get_imagedata('svg')
    return data.decode('utf-8') if isinstance(data, bytes) else data
