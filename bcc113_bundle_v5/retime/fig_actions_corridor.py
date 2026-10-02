#!/usr/bin/env python3
"""fig_actions_corridor.py -- emit a top-down "actions change per intersection"
TikZ figure from per-junction TSP action counts.

Draws the corridor spine in route order (same convention as the paper's
Logan/KG schematic figures), each managed junction a circle colored by its
DOMINANT action family with the action count beneath, plus a legend. The
distribution is read from an Aimsun log's [DECISION] ledger (--log), default
to an illustrative example so the mechanism is visible even before a run.

Usage: python fig_actions_corridor.py [--log LOG] [--order '1/17249,2/17308,...']
Output: the LaTeX figure block on stdout (paste into main.tex).
"""
import re
import sys
import collections

ROUTE_ORDER = [17249, 17308, 17383, 17498, 17628, 17963, 18044, 18942,
               19185, 19196, 19363, 19474, 19882, 20270, 20280, 20283,
               20844, 21197, 21553, 21847, 21895, 22232, 22603]

# Illustrative per-junction action counts (one Logan run's ledger; the figure
# is a mechanism illustration, counts are not a comparative result).
ILLUSTRATIVE = {
    17249: {"INS": 14, "VP": 3, "GR": 2, "ER": 1},
    17308: {"GR": 2},
    17383: {"VP": 2},
    17498: {"INS": 12, "ER": 2, "VP": 1, "GR": 1, "PT": 1},
    17628: {"VP": 6, "INS": 2, "PT": 3, "ER": 2, "GR": 2},
    17963: {"INS": 4, "VP": 3},
    18044: {"VP": 4, "INS": 4, "GR": 1},
    18942: {"GR": 2, "INS": 2, "ER": 22, "VP": 4, "PT": 2},
    19185: {"INS": 21, "GR": 2, "VP": 1},
    19196: {"VP": 4, "PT": 3, "ER": 4},
    19363: {"INS": 16, "GE": 2, "VP": 4, "PT": 1, "GR": 3},
    19474: {"INS": 8, "VP": 3, "PT": 2, "GR": 3, "ER": 1},
    19882: {"INS": 2, "GR": 5, "VP": 1, "ER": 9},
    20270: {"GR": 32, "ER": 4, "INS": 5, "VP": 8},
    20280: {"GR": 4, "VP": 3, "PT": 1, "OC": 2, "INS": 11},
    20283: {"PT": 18, "INS": 11, "VP": 9, "GR": 10},
    20844: {"INS": 16, "VP": 2, "GE": 3},
    21197: {"GR": 3, "INS": 1, "VP": 6, "ER": 9, "PT": 1},
    21553: {"INS": 7, "GR": 11, "PT": 9, "ER": 4},
    21847: {"VP": 7, "GR": 11, "INS": 5, "PT": 8, "ER": 10},
    21895: {"VP": 3, "PT": 23, "GR": 13, "INS": 5, "ER": 2},
    22232: {"GR": 20, "INS": 5, "VP": 5, "PT": 16, "ER": 1},
    22603: {"INS": 6, "VP": 6, "GR": 20, "ER": 6, "PT": 4},
}

FILL = {"GE": "corridorgreen!80!black", "INS": "carblue!75!black",
        "ER": "busred!75!black", "GR": "grviol!70!black",
        "VP": "orange!80!black", "PT": "teal!70!black",
        "OC": "gray!60", "NA": "white"}
COLOR_NAME = {"GE": "green ext.", "INS": "insert", "ER": "early red",
              "GR": "realloc.", "VP": "skip", "PT": "rotate", "OC": "offset"}


def parse_log(path):
    per = collections.defaultdict(collections.Counter)
    for line in open(path, encoding="utf-8", errors="replace"):
        if "[DECISION]" not in line:
            continue
        m = re.search(r"inter=(\d+) .*action=([A-Z]+)", line)
        if not m:
            continue
        per[int(m.group(1))][m.group(2)] += 1
    return per


def dominant(c):
    return max(c.items(), key=lambda kv: kv[1])[0] if c else "NA"


def main(argv):
    log = None
    it = iter(argv)
    for a in it:
        if a == "--log":
            log = next(it)
    data = parse_log(log) if log else ILLUSTRATIVE
    order = ROUTE_ORDER
    n = len(order)
    xstep = 0.70
    span = (n - 1) * xstep + 0.8

    print("\\begin{figure}[ht]")
    print("\\centering")
    print("\\begin{tikzpicture}[")
    print("    roadbed/.style={draw=gray!22, line width=11pt, line cap=round},")
    print("    busline/.style={draw=busred, line width=1.8pt, ->, >=stealth},")
    print("    jn/.style={draw=black!80, circle, minimum size=0.60cm, inner sep=0pt, font=\\scriptsize\\bfseries, text=white, line width=0.9pt},")
    print("    aid/.style={font=\\tiny\\ttfamily, text=black!75},")
    print("    cnt/.style={font=\\tiny, text=black!80},")
    print("]")
    print(f"  % --- corridor spine, {n} route junctions, top-down (schematic) ---")
    print(f"  \\draw[roadbed] (-0.5,0.6) -- ({span:.2f},0.6);")
    print(f"  \\draw[busline] (-0.5,0.6) -- ({span:.2f},0.6);")
    for i, j in enumerate(order):
        xp = i * xstep
        print(f"  \\draw[gray!55, line width=1.1pt, line cap=round] ({xp:.2f},0.80) -- ({xp:.2f},1.35);")
    print("  % --- junctions colored by dominant action family ---")
    for i, j in enumerate(order):
        xp = i * xstep
        c = data.get(j) or {}
        dom = dominant(c)
        fill = FILL.get(dom, "white")
        tot = sum(c.values())
        print(f"  \\node[jn, fill={fill}] at ({xp:.2f},0.6) {{{i + 1}}};")
        if tot:
            print(f"  \\node[cnt, anchor=north] at ({xp:.2f},0.28) {{{tot}}};")
        print(f"  \\node[aid] at ({xp:.2f},0.02) {{{j}}};")
    print("  % --- legend (framed) ---")
    print("  \\node[draw=gray!50, rounded corners=3pt, fill=gray!5, inner sep=6pt, anchor=north west] at (-0.5,-0.85) {")
    print("    \\begin{tikzpicture}[font=\\scriptsize")
    print("      lj/.style={draw=black!80, circle, minimum size=0.45cm, inner sep=0pt, font=\\scriptsize\\bfseries, text=white, line width=0.8pt},")
    print("    ]")
    col = 0
    for k, cname in COLOR_NAME.items():
        x = col % 3 * 4.4
        y = -(col // 3) * 0.55
        print(f"      \\node[lj, fill={FILL[k]}] at ({x}, {y}) {{}};")
        print(f"      \\node[anchor=west] at ({x + 0.5}, {y}) {{{cname}}};")
        col += 1
    print("      \\node[anchor=west] at (0, -1.45) {\\itshape\\textcolor{gray}{Top-down, not to scale; left-to-right = route order. Circle = dominant action at that junction, number below = total actions, under = Aimsun ID.}};")
    print("    \\end{tikzpicture}")
    print("  };")
    print("\\end{tikzpicture}")
    print("\\caption{How TSP actions change from intersection to intersection (top-down,"
          " schematic).  Each junction's dominant action family is shown, with the"
          " action count and Aimsun ID beneath.  The mix is heterogeneous along the"
          " corridor: reallocation and phase rotation cluster where cross-street"
          " queues dominate, insertions where through buses are held, skips and early"
          " reds where phases are empty -- the same action set, differently deployed"
          " junction by junction.  Counts are illustrative of one run, not a"
          " comparative result.}")
    print("\\end{figure}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))