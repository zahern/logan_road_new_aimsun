r"""tikz_phase.py -- TikZ figures, in the style of Qin & Zhang (arXiv:2404.19683),
generated from what a RUN actually derived and measured. Pure stdlib.

  phase_sequence_tex   Fig. 4/5 analogue: one panel per real green phase of a
                       junction, its movements drawn as arrows from each
                       approach's REAL compass bearing (through / left / right),
                       protected vs free left labelled, PRIORITY (bus) phases
                       highlighted, and run statistics under each panel (mean
                       green served, times served, CBQL picks).
  ctm_cells_tex        Fig. 3 analogue: the junction's approach links as CTM
                       cells (stop line at the centre), each cell shaded by the
                       run-mean occupancy (car + bus pcu / storage) with the bus
                       density drawn as its own bar -- the paper's separate
                       rho_bus / rho_non-bus -- and receiving (exit) arms.
  standalone_doc       a compilable wrapper that \input's the figures.

Every figure is a self-contained tikzpicture: colours are \providecolor'd, so
it drops into the paper (where corridorgreen / busred already exist) or the
wrapper unchanged.

Bearings are degrees in the math frame (0 = east, CCW positive) and are the
direction of TRAVEL at the approach's stop line; a vehicle heading north
therefore enters from the south arm.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

PREAMBLE_COLOURS = (
    "\\providecolor{corridorgreen}{RGB}{46,139,87}\n"
    "\\providecolor{busred}{RGB}{200,30,45}\n"
    "\\providecolor{carblue}{RGB}{40,90,170}\n")


def _esc(s) -> str:
    return (str(s).replace('\\', '/').replace('_', '\\_').replace('%', '\\%')
            .replace('&', '\\&').replace('#', '\\#'))


def _arm_xy(bearing_travel_deg: float, r: float):
    """Point on the arm a vehicle travelling at `bearing` ENTERS from."""
    a = math.radians(bearing_travel_deg + 180.0)
    return r * math.cos(a), r * math.sin(a)


def _movement_path(bearing: float, turn: str, R=0.9, lane_off=0.16,
                   left_hand_traffic=True):
    """TikZ path for one movement in a unit junction: from the entry arm the
    vehicle comes in on, to the exit arm it leaves by, each kept to the
    traffic side (left for KG / Logan)."""
    sgn = 1.0 if left_hand_traffic else -1.0

    def side(hx, hy):                     # unit vector to the traffic side
        return -hy * sgn, hx * sgn
    h = math.radians(bearing)
    ux, uy = math.cos(h), math.sin(h)
    sx0, sy0 = side(ux, uy)
    S = (-ux * R + sx0 * lane_off, -uy * R + sy0 * lane_off)
    if turn == 'through':
        E = (ux * R + sx0 * lane_off, uy * R + sy0 * lane_off)
        return "(%.3f,%.3f) -- (%.3f,%.3f)" % (S + E)
    nh = h + (math.pi / 2.0 if turn == 'left' else -math.pi / 2.0)
    nx, ny = math.cos(nh), math.sin(nh)
    ex0, ey0 = side(nx, ny)
    E = (nx * R + ex0 * lane_off, ny * R + ey0 * lane_off)
    k = 0.55 * R
    return "(%.3f,%.3f) .. controls (%.3f,%.3f) and (%.3f,%.3f) .. (%.3f,%.3f)" % (
        S[0], S[1], S[0] + ux * k, S[1] + uy * k, E[0] - nx * k, E[1] - ny * k,
        E[0], E[1])


def phase_sequence_tex(junction: int, phases: Sequence[dict], cycle_s=None,
                       title: str = '', per_row: int = 4,
                       left_hand_traffic: bool = True) -> str:
    """phases: [{'idx', 'type', 'priority', 'movements': [(bearing, turn)],
                 'green_mean_s', 'n_served', 'picks'}]"""
    W, H, GAP = 2.4, 2.4, 0.35
    out = [PREAMBLE_COLOURS,
           "\\begin{tikzpicture}[font=\\scriptsize,\n"
           "  road/.style={gray!25, line width=7pt},\n"
           "  mv/.style={black!75, line width=0.9pt, -{Stealth[length=4pt]}},\n"
           "  mvp/.style={busred, line width=1.3pt, -{Stealth[length=5pt]}},\n"
           "  box/.style={draw=gray!60, rounded corners=2pt},\n"
           "  pbox/.style={draw=busred, line width=1.1pt, rounded corners=2pt, fill=busred!6}]\n"]
    for k, ph in enumerate(phases):
        col, row = k % per_row, k // per_row
        ox = col * (W + GAP) + W / 2.0
        oy = -row * (H + 1.15) - H / 2.0
        pri = bool(ph.get('priority'))
        out.append("  \\begin{scope}[shift={(%.3f,%.3f)}]\n" % (ox, oy))
        out.append("    \\draw[%s] (%.2f,%.2f) rectangle (%.2f,%.2f);\n"
                   % ('pbox' if pri else 'box', -W / 2, -H / 2, W / 2, H / 2))
        out.append("    \\draw[road] (-1.0,0) -- (1.0,0); \\draw[road] (0,-1.0) -- (0,1.0);\n")
        for (b, turn) in ph.get('movements', ()):
            if b is None:
                continue
            out.append("    \\draw[%s] %s;\n" % ('mvp' if pri else 'mv',
                                                 _movement_path(float(b), turn, 0.9, 0.16,
                                                                left_hand_traffic)))
        out.append("    \\node[anchor=north west, font=\\scriptsize\\bfseries%s] at (%.2f,%.2f) {$\\phi_{%s}$%s};\n"
                   % (', text=busred' if pri else '', -W / 2 + 0.05, H / 2 - 0.03,
                      ph.get('idx'), ' P' if pri else ''))
        out.append("    \\node[anchor=north east, font=\\tiny] at (%.2f,%.2f) {%s};\n"
                   % (W / 2 - 0.05, H / 2 - 0.05, _esc(ph.get('type', '')).replace('\\_', ' ')))
        stats = []
        if ph.get('green_mean_s') is not None:
            stats.append("$\\bar g$=%.0f\\,s" % float(ph['green_mean_s']))
        if ph.get('n_served') is not None:
            stats.append("served %d" % int(ph['n_served']))
        if ph.get('picks') is not None:
            stats.append("CBQL %d" % int(ph['picks']))
        if stats:
            out.append("    \\node[anchor=north, align=center, font=\\tiny] at (0,%.2f) {%s};\n"
                       % (-H / 2 - 0.05, ' \\\\ '.join(stats)))
        out.append("  \\end{scope}\n")
    n_rows = (len(phases) + per_row - 1) // per_row
    cap = "Junction %s%s" % (junction, (" -- " + _esc(title)) if title else '')
    if cycle_s:
        cap += ", cycle %.0f\\,s" % float(cycle_s)
    out.append("  \\node[anchor=north west, font=\\small\\bfseries] at (0,%.2f) {%s};\n"
               % (-n_rows * (H + 1.15) + 0.2, cap))
    out.append("\\end{tikzpicture}\n")
    return ''.join(out)


def ctm_cells_tex(junction: int, approaches: Sequence[dict],
                  exits: Sequence[dict] = (), title: str = '',
                  cell_w=0.42, cell_h=0.30, gap=0.75,
                  left_hand_traffic: bool = True) -> str:
    """approaches: [{'sec', 'bearing', 'occ': [per-cell mean occupancy 0..1,
                     upstream -> stop line], 'bus': [per-cell mean buses],
                     'phase_ids': [...], 'priority': bool}]
       exits: [{'sec', 'bearing'}]  (bearing of travel leaving the node)

    Each arm is drawn in its own rotated frame with x pointing AWAY from the
    node. Entering cells sit on the traffic side of the INBOUND direction and
    exit (receiving) arms on the traffic side of the OUTBOUND one, so the two
    never overlap; labels are placed unrotated just past the arm's end."""
    sgn = 1.0 if left_hand_traffic else -1.0
    lane_y = 0.5 * cell_h + 0.04          # half-road offset of a carriageway
    out = [PREAMBLE_COLOURS,
           "\\begin{tikzpicture}[font=\\tiny,\n"
           "  cell/.style={draw=gray!70, line width=0.3pt},\n"
           "  busbar/.style={fill=busred},\n"
           "  ex/.style={gray!55, line width=%.2fcm, -{Stealth[length=6pt, width=10pt]}}]\n" % (cell_h * 0.8),
           "  \\draw[gray!40, fill=gray!8] (-%.2f,-%.2f) rectangle (%.2f,%.2f);\n"
           % (gap, gap, gap, gap)]
    ext = [gap]
    for ap in approaches:
        b = float(ap.get('bearing') or 0.0)
        occ = list(ap.get('occ') or [])
        bus = list(ap.get('bus') or [])
        K = len(occ)
        a = math.radians(b + 180.0)        # arm direction, away from the node
        ux, uy = math.cos(a), math.sin(a)
        # inbound travel is -x in the arm frame; its traffic side:
        y0 = -sgn * lane_y
        pri = bool(ap.get('priority'))
        out.append("  \\begin{scope}[shift={(%.3f,%.3f)}, rotate=%.1f]\n"
                   % (ux * gap, uy * gap, math.degrees(a)))
        for j in range(K):
            o = max(0.0, min(1.0, float(occ[K - 1 - j])))
            nb = float(bus[K - 1 - j]) if (K - 1 - j) < len(bus) else 0.0
            x0 = j * cell_w
            out.append("    \\draw[cell, fill=carblue!%d] (%.3f,%.3f) rectangle (%.3f,%.3f);\n"
                       % (int(round(100 * o)), x0, y0 - cell_h / 2, x0 + cell_w, y0 + cell_h / 2))
            if nb > 0.005:
                hb = min(1.0, nb) * cell_h
                out.append("    \\fill[busbar] (%.3f,%.3f) rectangle (%.3f,%.3f);\n"
                           % (x0 + 0.04, y0 - cell_h / 2, x0 + 0.12, y0 - cell_h / 2 + hb))
        out.append("    \\draw[%s, line width=1.4pt] (0,%.3f) -- (0,%.3f);\n"
                   % ('busred' if pri else 'black', y0 - cell_h / 2 - 0.04, y0 + cell_h / 2 + 0.04))
        out.append("  \\end{scope}\n")
        L = gap + K * cell_w + 0.12
        ext.append(L)
        px, py = ux * L - math.sin(a) * y0, uy * L + math.cos(a) * y0
        anc = ('west' if ux > 0.5 else 'east' if ux < -0.5 else
               'south' if uy > 0 else 'north')
        out.append("  \\node[anchor=%s, font=\\tiny, inner sep=1pt] at (%.3f,%.3f) {sec %s%s};\n"
                   % (anc, px, py, ap.get('sec'),
                      (' $\\phi$' + ','.join(str(p) for p in ap.get('phase_ids', ())))
                      if ap.get('phase_ids') else ''))
    for ex in exits or ():
        b = math.radians(float(ex.get('bearing') or 0.0))
        ux, uy = math.cos(b), math.sin(b)
        oy = sgn * lane_y                  # outbound traffic side (+y in its frame)
        sx, sy = -uy * oy, ux * oy
        out.append("  \\draw[ex] (%.3f,%.3f) -- (%.3f,%.3f);\n"
                   % (ux * gap + sx, uy * gap + sy, ux * (gap + 1.1) + sx, uy * (gap + 1.1) + sy))
        if abs(ux) > 0.5:                  # horizontal exit: label beside its far end
            anc = 'north' if sy < 0 else 'south'
            lx, ly = ux * (gap + 0.9) + sx, uy * (gap + 0.9) + sy * 2.2
        else:                              # vertical exit: label on its outer side
            anc = 'east' if sx < 0 else 'west'
            lx, ly = ux * (gap + 0.9) + sx * 2.2, uy * (gap + 0.9) + sy
        out.append("  \\node[anchor=%s, font=\\tiny, text=gray, inner sep=1pt] at (%.3f,%.3f) {exit %s};\n"
                   % (anc, lx, ly, ex.get('sec')))
        ext.append(gap + 1.2)
    out.append("  \\node[font=\\scriptsize\\bfseries] at (0,0) {J%s};\n" % junction)
    R = max(ext) + 0.6
    out.append("  \\begin{scope}[shift={(%.2f,%.2f)}]\n"
               "    \\foreach \\o/\\x in {0/0,25/0.45,50/0.9,75/1.35,100/1.8}"
               " {\\draw[cell, fill=carblue!\\o] (\\x,0) rectangle +(0.42,0.3);}\n"
               "    \\node[anchor=west] at (2.3,0.15) {occupancy (pcu / storage), 0 $\\to$ 1};\n"
               "    \\fill[busbar] (0.05,-0.5) rectangle +(0.08,0.3);\n"
               "    \\node[anchor=west] at (0.2,-0.35) {mean buses in cell ($\\rho_{\\text{bus}}$)};\n"
               "    \\draw[gray!55, line width=0.24cm, -{Stealth[length=6pt, width=10pt]}] (3.9,-0.35) -- (4.5,-0.35);\n"
               "    \\node[anchor=west] at (4.55,-0.35) {exit (receiving)};\n"
               "  \\end{scope}\n" % (-R, -R - 0.4))
    if title:
        out.append("  \\node[anchor=south, font=\\small\\bfseries] at (0,%.2f) {%s};\n"
                   % (R, _esc(title)))
    out.append("\\end{tikzpicture}\n")
    return ''.join(out)


def standalone_doc(inputs: Sequence[str], captions: Sequence[str] = ()) -> str:
    body = []
    for i, f in enumerate(inputs):
        cap = captions[i] if i < len(captions) else ''
        body.append("\\begin{figure}[ht]\\centering\n\\input{%s}\n%s\\end{figure}\n"
                    % (f, ("\\caption{%s}\n" % cap) if cap else ''))
    return ("\\documentclass{article}\n\\usepackage[margin=1.5cm]{geometry}\n"
            "\\usepackage{tikz}\\usetikzlibrary{arrows.meta}\n"
            "\\usepackage{amsmath}\n\\begin{document}\n" + ''.join(body)
            + "\\end{document}\n")


def _selftest():
    ph = [
        {'idx': 1, 'type': 'through', 'priority': True,
         'movements': [(90.0, 'through'), (270.0, 'through')],
         'green_mean_s': 34.2, 'n_served': 30, 'picks': 12},
        {'idx': 2, 'type': 'protected_left', 'priority': False,
         'movements': [(90.0, 'left'), (270.0, 'left')], 'green_mean_s': 12.0,
         'n_served': 30, 'picks': 3},
        {'idx': 3, 'type': 'free_left', 'priority': False,
         'movements': [(0.0, 'through'), (180.0, 'through'), (0.0, 'right')]},
    ]
    t = phase_sequence_tex(38339, ph, 120.0, 'CBQL_SHAPLEY_KG seed 500')
    assert t.count('\\begin{scope}') == 3 and 'mvp' in t and '$\\phi_{1}$ P' in t, t[:400]
    assert '\\providecolor{busred}' in t
    c = ctm_cells_tex(38339, [
        {'sec': 101, 'bearing': 90.0, 'occ': [0.1, 0.3, 0.8, 1.0],
         'bus': [0, 0, 0.4, 0], 'phase_ids': [1], 'priority': True},
        {'sec': 201, 'bearing': 0.0, 'occ': [0.0, 0.2], 'bus': [0, 0]}],
        [{'sec': 300, 'bearing': 90.0}], 'run means')
    assert c.count('rectangle') >= 6 and 'busbar' in c and 'carblue!100' in c
    d = standalone_doc(['a.tex', 'b.tex'], ['A', 'B'])
    assert d.count('\\input{') == 2 and 'arrows.meta' in d
    print('OK: phase sequence, CTM cells, standalone wrapper.')


if __name__ == '__main__':
    _selftest()
