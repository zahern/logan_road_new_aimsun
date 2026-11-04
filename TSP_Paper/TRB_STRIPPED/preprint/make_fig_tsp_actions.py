"""make_fig_tsp_actions.py -- generate fig_tsp_actions.tex, the TSP action
figure (fig:action_mech) as signal-timing diagrams.

Each panel is one junction's signal timeline: the PLAN row (what runs without
the action) above the WITH-ACTION row, on a common 0-64 s axis. Bars: bus
(main) phase green B, cross-street green X / X1 / X2, intergreen IG. The red
dashed line is the bus arrival; the bus glyph on each row is when it leaves,
and the red arrow under the row is its wait, computed here from the timing so
the drawing and the numbers cannot disagree. A brace marks what the action
changed.

    python make_fig_tsp_actions.py            # writes fig_tsp_actions.tex
    python make_fig_tsp_actions.py --preview  # + fig_tsp_actions_preview.tex

In main.tex the figure body is just:  \\input{fig_tsp_actions.tex}
Colours used (defined in main.tex): busred, carblue, corridorgreen.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SX = 0.112          # cm per second
ROW_H = 0.34        # bar height (cm)
ROW_GAP = 0.78      # vertical distance between the two rows (cm)
T_MAX = 64

# phase kinds -> (fill, text colour, label)
KIND = {
    'B':  ('corridorgreen!72', 'white', 'B'),
    'X':  ('carblue!30', 'black!80', 'X'),
    'X1': ('carblue!30', 'black!80', 'X$_1$'),
    'X2': ('carblue!48', 'black!85', 'X$_2$'),
    'IG': ('orange!45', 'black', ''),
    'R':  ('busred!18', 'black!70', 'red'),
}


def seq(*parts):
    """('B',20),('IG',4),... -> [(t0,t1,kind)] from t=0."""
    t, out = 0.0, []
    for k, d in parts:
        out.append((t, t + d, k))
        t += d
    return out


def depart(row, arr, bus_phase='B'):
    """First time >= arr that the bus phase is green on this row."""
    for t0, t1, k in row:
        if k == bus_phase and t1 > arr:
            return max(t0, arr)
    return None


# ---------------------------------------------------------------- panels
CYCLE = seq(('B', 20), ('IG', 4), ('X', 32), ('IG', 4), ('B', 4))   # 0-64
PANELS = [
    dict(key='a', title='(a) reference: no action',
         rows=[('plan', CYCLE)], arr=22,
         note=['bus arrives just after its', 'green: it waits a full red']),
    dict(key='b', title=r'(b) \texttt{GE} green extension',
         rows=[('plan', CYCLE),
               ('with GE', seq(('B', 26), ('IG', 4), ('X', 26), ('IG', 4), ('B', 4)))],
         arr=22, brace=(1, 20, 26, r'$+\delta$'),
         note=[r'bus green held $\delta$ longer;', r'cross green $-\delta$ (recovered)']),
    dict(key='c', title=r'(c) \texttt{GR} green reallocation',
         rows=[('plan', CYCLE),
               ('with GR', seq(('B', 20), ('IG', 4), ('X', 20), ('IG', 4), ('B', 16)))],
         arr=40, brace=(1, 44, 56, r'$-\delta$ cross'),
         note=['cross green cut short:', 'bus green starts $\\delta$ sooner']),
    dict(key='d', title=r'(d) \texttt{INS}/PI phase insertion',
         rows=[('plan', CYCLE),
               ('with INS', seq(('B', 20), ('IG', 4), ('X', 8), ('IG', 4), ('B', 8),
                                ('IG', 4), ('X', 12), ('IG', 4)))],
         arr=30, brace=(1, 36, 44, r'inserted $\delta$'),
         note=['a short bus phase is inserted', 'inside the cross green']),
    dict(key='e', title=r'(e) \texttt{ER} early red',
         rows=[('plan', CYCLE),
               ('with ER', seq(('B', 12), ('IG', 4), ('X', 40), ('IG', 4), ('B', 4)))],
         arr=6, brace=(1, 12, 20, r'$-\delta$ bus'),
         note=['bus already through: its green', r'ends $\delta$ early, cross served sooner'],
         gain='cross'),
    dict(key='f', title=r'(f) \texttt{VP} phase skip',
         rows=[('plan', seq(('B', 20), ('IG', 4), ('X1', 12), ('IG', 4), ('X2', 16),
                            ('IG', 4), ('B', 4))),
               ('with VP', seq(('B', 20), ('IG', 4), ('X2', 16), ('IG', 4), ('B', 20)))],
         arr=30, brace=(1, 24, 40, r'X$_1$ skipped: X$_2$ runs now'),
         note=['empty phase X$_1$ dropped;', 'one intergreen saved']),
    dict(key='g', title=r'(g) \texttt{PT} phase rotation',
         rows=[('plan', seq(('X1', 14), ('IG', 4), ('X2', 18), ('IG', 4), ('B', 16),
                            ('IG', 4), ('X1', 4))),
               ('with PT', seq(('B', 16), ('IG', 4), ('X1', 14), ('IG', 4), ('X2', 18),
                               ('IG', 4), ('B', 4)))],
         arr=4, brace=(1, 0, 16, 'B served first'),
         note=['same phases and greens,', 'order rotated: B first']),
    dict(key='h', title=r'(h) offset correction',
         rows=[('J2 plan', seq(('B', 20), ('IG', 4), ('X', 32), ('IG', 4), ('B', 4))),
               (r'J2 $+\Delta$', seq(('X', 6), ('IG', 4), ('B', 20), ('IG', 4), ('X', 26),
                                     ('IG', 4)))],
         arr=27, brace=(1, 10, 30, r'band shifted $+\Delta$'),
         note=['downstream green band shifted', r'by $\Delta$ to meet the bus from J1']),
]


def _bar(y, t0, t1, kind, out):
    fill, tc, lab = KIND[kind]
    x0, x1 = t0 * SX, min(t1, T_MAX) * SX
    out.append(r'\fill[%s] (%.3f,%.3f) rectangle (%.3f,%.3f);' % (fill, x0, y, x1, y + ROW_H))
    out.append(r'\draw[white, line width=0.5pt] (%.3f,%.3f) -- (%.3f,%.3f);'
               % (x0, y, x0, y + ROW_H))
    if lab and (x1 - x0) > 0.30:
        out.append(r'\node[font=\fontsize{6}{7}\selectfont\bfseries, text=%s] at (%.3f,%.3f) {%s};'
                   % (tc, (x0 + x1) / 2, y + ROW_H / 2, lab))


def panel(p):
    """Vertical lanes (cm, panel origin at the action row's bottom-left):
    title 2.10 | 'bus arrives' 1.74 | wait arrow 1.47 | PLAN bar 0.95-1.29 |
    wait arrow 0.50 | ACTION bar 0.00-0.34 | brace + label below | axis -0.62 |
    outcome / note -0.98 ..."""
    out = []
    rows = p['rows']
    ys = [0.95, 0.0][:len(rows)] if len(rows) == 2 else [0.95]
    arr = float(p['arr'])
    waits = []
    out.append(r'\node[anchor=west, font=\fontsize{7.5}{9}\selectfont\bfseries] at (0,2.12) {%s};'
               % p['title'])
    for (lab, segs), y in zip(rows, ys):
        out.append(r'\node[anchor=east, font=\fontsize{6}{7}\selectfont, text=black!75] '
                   r'at (-0.08,%.3f) {%s};' % (y + ROW_H / 2, lab))
        for t0, t1, k in segs:
            if t0 < T_MAX:
                _bar(y, t0, t1, k, out)
        out.append(r'\draw[black!35, line width=0.3pt] (0,%.3f) rectangle (%.3f,%.3f);'
                   % (y, T_MAX * SX, y + ROW_H))
        d = depart(segs, arr)
        if d is None:
            continue
        w = d - arr
        waits.append(w)
        ya = y + ROW_H + 0.16                     # wait lane just above the bar
        if w > 0.5:
            out.append(r'\draw[busred, line width=0.8pt, -{Stealth[length=1.5mm]}] '
                       r'(%.3f,%.3f) -- (%.3f,%.3f);' % (arr * SX, ya, d * SX - 0.17, ya))
        out.append(r'\node[draw=busred!80!black, fill=busred!75, rounded corners=0.8pt, '
                   r'minimum width=0.30cm, minimum height=0.15cm, inner sep=0pt] at (%.3f,%.3f) {};'
                   % (d * SX, ya))
        lab_w = (r'wait %d\,s' % round(w)) if w > 0.5 else 'no wait'
        col = 'busred' if w > 0.5 else 'corridorgreen!55!black'
        # label beside the glyph, on whichever side has room
        if d * SX + 1.2 < T_MAX * SX:
            out.append(r'\node[anchor=west, font=\fontsize{5.5}{6}\selectfont\bfseries, text=%s] '
                       r'at (%.3f,%.3f) {%s};' % (col, d * SX + 0.18, ya, lab_w))
        else:
            out.append(r'\node[anchor=south east, font=\fontsize{5.5}{6}\selectfont\bfseries, '
                       r'text=%s, inner sep=1pt] at (%.3f,%.3f) {%s};'
                       % (col, d * SX - 0.20, ya + 0.02, lab_w))
    # arrival line through every row
    out.append(r'\draw[busred, densely dashed, line width=0.6pt] (%.3f,%.3f) -- (%.3f,%.3f);'
               % (arr * SX, 1.66, arr * SX, ys[-1] - 0.04))
    out.append(r'\node[font=\fontsize{5.5}{6}\selectfont, text=busred, anchor=south] at (%.3f,%.3f) '
               r'{bus arrives};' % (max(arr * SX, 0.45), 1.64))
    # what the action changed: outline + brace + label BELOW the action row
    if p.get('brace'):
        r_i, t0, t1, txt = p['brace']
        y = ys[r_i]
        out.append(r'\draw[Highlight, line width=1.0pt] (%.3f,%.3f) rectangle (%.3f,%.3f);'
                   % (t0 * SX, y, t1 * SX, y + ROW_H))
        out.append(r'\draw[Highlight, line width=0.7pt, decorate, '
                   r'decoration={brace, amplitude=2.2pt, mirror}] (%.3f,%.3f) -- (%.3f,%.3f);'
                   % (t0 * SX, y - 0.05, t1 * SX, y - 0.05))
        out.append(r'\node[font=\fontsize{5.8}{6.5}\selectfont\bfseries, text=Highlight, anchor=north] '
                   r'at (%.3f,%.3f) {%s};' % ((t0 + t1) / 2 * SX, y - 0.13, txt))
    # outcome + note under the axis
    if p.get('gain') == 'cross':
        res = r'bus unaffected; cross street served $\delta$ sooner'
    elif len(waits) == 2:
        res = r'bus wait %d\,s $\rightarrow$ %d\,s' % (round(waits[0]), round(waits[1]))
    else:
        res = r'bus wait %d\,s' % round(waits[0])
    out.append(r'\node[anchor=north west, align=left, text width=%.2fcm, '
               r'font=\fontsize{6.2}{7.4}\selectfont, text=black!80] at (0,%.3f) '
               r'{\textbf{%s}: %s};' % (T_MAX * SX, -0.98, res, ' '.join(p['note'])))
    return out, waits


def axis(y):
    out = [r'\draw[black!45, line width=0.4pt] (0,%.3f) -- (%.3f,%.3f);' % (y, T_MAX * SX, y)]
    for t in range(0, T_MAX + 1, 16):
        out.append(r'\draw[black!45, line width=0.4pt] (%.3f,%.3f) -- (%.3f,%.3f) '
                   r'node[below, font=\fontsize{5.5}{6}\selectfont, text=black!60] {%d};'
                   % (t * SX, y, t * SX, y - 0.06, t))
    out.append(r'\node[font=\fontsize{5.5}{6}\selectfont, text=black!60, anchor=west] at (%.3f,%.3f) {s};'
               % (T_MAX * SX + 0.05, y - 0.18))
    return out


def build():
    col_w = T_MAX * SX + 1.45              # bars + row-label space of the next column
    row_h = 4.05
    out = ['% generated by make_fig_tsp_actions.py -- edit the generator, not this file',
           r'\begin{tikzpicture}[decoration={brace}]']
    if 'decorations.pathreplacing' not in out[1]:
        pass
    summary = {}
    for i, p in enumerate(PANELS):
        cx = (i % 2) * col_w
        cy = -(i // 2) * row_h
        body, waits = panel(p)
        out.append(r'\begin{scope}[shift={(%.3f,%.3f)}]' % (cx, cy))
        out.extend(body)
        n_rows = len(p['rows'])
        out.extend(axis(-0.62))
        out.append(r'\end{scope}')
        summary[p['key']] = waits
    # legend
    ly = -(len(PANELS) // 2) * row_h + 1.95
    leg = [
        (r'\fill[corridorgreen!72] (0,0) rectangle (0.4,0.22);', 'bus (main) phase green B'),
        (r'\fill[carblue!30] (0,0) rectangle (0.4,0.22);', r'cross-street green X, X$_1$, X$_2$'),
        (r'\fill[orange!45] (0,0) rectangle (0.4,0.22);', 'intergreen (amber + all-red)'),
        (r'\draw[busred, densely dashed, line width=0.6pt] (0.2,-0.05) -- (0.2,0.27);', 'bus arrives'),
        (r'\node[draw=busred!80!black, fill=busred!75, rounded corners=0.8pt, minimum width=0.30cm, '
         r'minimum height=0.15cm, inner sep=0pt] at (0.2,0.11) {};', 'bus departs (each row)'),
        (r'\draw[Highlight, line width=0.9pt] (0,0) rectangle (0.4,0.22);', 'what the action changed'),
    ]
    for j, (glyph, txt) in enumerate(leg):
        x = (j % 3) * 5.4
        y = ly - (j // 3) * 0.42
        out.append(r'\begin{scope}[shift={(%.2f,%.2f)}]%s\node[anchor=west, '
                   r'font=\fontsize{6.5}{7.5}\selectfont] at (0.5,0.11) {%s};\end{scope}'
                   % (x, y, glyph, txt))
    out.append(r'\end{tikzpicture}')
    return '\n'.join(out) + '\n', summary


PREVIEW = r"""\documentclass[letterpaper,8pt]{extarticle}
\usepackage[left=.65in,top=.65in,bottom=.65in,right=.65in]{geometry}
\usepackage{tikz}
\usetikzlibrary{arrows.meta, decorations.pathreplacing}
\definecolor{busred}{RGB}{200,40,40}
\definecolor{carblue}{RGB}{40,80,180}
\definecolor{corridorgreen}{RGB}{40,150,80}
\definecolor{Highlight}{HTML}{580F8B}
\pagestyle{empty}
\begin{document}
\begin{figure}[p]\centering
\input{fig_tsp_actions.tex}
\caption{CAPTION}
\end{figure}
\end{document}
"""

CAPTION = (
    r"What each TSP action does to the signal timing. Each panel is one junction: "
    r"the \emph{plan} row is the timing that runs without the action and the row "
    r"below it is the same cycle with the action applied, on a common 0--64\,s "
    r"axis. Green bars are the bus (main) phase \textsf{B}, blue bars the cross-street "
    r"phases \textsf{X}, orange the intergreens. The dashed red line is the bus "
    r"arrival; the bus glyph marks when it leaves on each row and the red arrow is "
    r"its wait. The purple outline and brace mark exactly what the action changed. "
    r"(a) Without action a bus that arrives just after its green waits a full red. "
    r"(b) \texttt{GE} holds the bus green $\delta$ longer so the bus clears; the "
    r"cross green is shortened by $\delta$ to recover the cycle. "
    r"(c) \texttt{GR} cuts the running cross green by $\delta$ so the bus green "
    r"starts $\delta$ sooner. "
    r"(d) \texttt{INS} (phase insertion, PI) inserts a short bus phase inside the "
    r"cross green, serving the bus this cycle instead of the next. "
    r"(e) \texttt{ER} ends the bus green early once the bus has passed and hands "
    r"the time to the cross street. "
    r"(f) \texttt{VP} skips an empty phase, removing it and one intergreen from the "
    r"ring. "
    r"(g) \texttt{PT} rotates the phase order so the bus phase is served first, "
    r"with the same greens. "
    r"(h) Offset correction shifts the downstream junction's green band by $\Delta$ "
    r"so the bus arriving from upstream meets green. Timings are schematic; waits "
    r"are computed from the drawn timing.")


def main():
    tex, summary = build()
    with open(os.path.join(HERE, 'fig_tsp_actions.tex'), 'w') as fh:
        fh.write(tex)
    with open(os.path.join(HERE, 'fig_tsp_actions_caption.tex'), 'w') as fh:
        fh.write(CAPTION + '\n')
    if '--preview' in sys.argv:
        with open(os.path.join(HERE, 'fig_tsp_actions_preview.tex'), 'w') as fh:
            fh.write(PREVIEW.replace('CAPTION', CAPTION))
    for k, w in summary.items():
        print('panel %s waits %s' % (k, ['%g' % x for x in w]))


if __name__ == '__main__':
    main()
