"""Draw the CTM cells on the actual KG link, to scale.

Panel (a): the real link s21546 (248 m, 2 lanes), rotated horizontal so the cells
read left-to-right like the schematic, with the k cells that
``ctm_lightsim._geom_parts`` creates drawn across the carriageway, junction boxes
at each end, a scale bar and the travel direction.
Panel (b): where that link sits in the corridor, zoomed to a 700 m window.

k follows the engine exactly:  k = ceil(length / (vf*dt)), capped at 12.
Drawn cell width is length/k (27.5 m); the engine's nominal L is vf*dt (27.8 m).
"""
from __future__ import annotations

import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle, FancyArrowPatch

plt.rcParams.update({"font.family": "serif", "text.usetex": False, "font.size": 8.5})

NET = Path("_sumo_snaps/kg.net.xml")
VF = 13.89          # m/s == 50 km/h
DT = 2.0
CELL = VF * DT      # 27.78 m nominal
MAX_CELLS = 12
LANE_W = 3.5        # m
WINDOW = 320.0      # m half-width of the locator (700 made the link a lone
                    # bar in an empty square: s21546 is a cordon stub, so
                    # everything beyond it is outside the modelled network)


def load_net():
    root = ET.parse(str(NET)).getroot()
    junc = {}
    for j in root.findall("junction"):
        jid = j.get("id", "")
        if jid.startswith(":"):
            continue
        junc[jid] = (float(j.get("x", 0.0)), float(j.get("y", 0.0)))

    edges = {}
    for e in root.findall("edge"):
        eid = e.get("id", "")
        if eid.startswith(":") or e.get("function") == "internal":
            continue
        lanes = e.findall("lane")
        if not lanes:
            continue
        length = float(e.get("length") or lanes[0].get("length") or 0.0)
        shape = lanes[0].get("shape")
        pts = [tuple(float(v) for v in p.split(",")) for p in shape.split()] if shape else []
        if len(pts) < 2:
            pts = [junc[e.get("from")], junc[e.get("to")]]
        edges[eid] = dict(id=eid, frm=e.get("from"), to=e.get("to"),
                          lanes=len(lanes), length=length, pts=pts,
                          speed=float(lanes[0].get("speed") or VF))
    return junc, edges


def cumlen(pts):
    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + math.hypot(pts[i][0] - pts[i - 1][0],
                                    pts[i][1] - pts[i - 1][1]))
    return d


def point_at(pts, cum, s):
    s = min(max(s, 0.0), cum[-1])
    for i in range(1, len(cum)):
        if cum[i] >= s:
            t = (s - cum[i - 1]) / max(cum[i] - cum[i - 1], 1e-9)
            return (pts[i - 1][0] + t * (pts[i][0] - pts[i - 1][0]),
                    pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1]))
    return pts[-1]


def normal_at(pts, cum, s):
    a = point_at(pts, cum, max(s - 1.0, 0.0))
    b = point_at(pts, cum, min(s + 1.0, cum[-1]))
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return (-dy / n, dx / n)


def rotate(pts, ang):
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    ca, sa = math.cos(ang), math.sin(ang)
    return [((p[0] - cx) * ca - (p[1] - cy) * sa + cx,
             (p[0] - cx) * sa + (p[1] - cy) * ca + cy) for p in pts]


def main():
    junc, edges = load_net()

    two = [e for e in edges.values() if e["lanes"] == 2 and e["length"] > 40]
    pick = min(two, key=lambda e: abs(e["length"] - 248.0))
    # engine rule: ceil(int(length) / int(vf*dt)), because _geom_parts
    # truncates both operands before dividing
    k_raw = math.ceil(int(pick["length"]) / int(CELL))
    k = max(1, min(int(k_raw), MAX_CELLS))
    print("edge %s  %.2f m  %d lanes  %s -> %s  -> k=%d"
          % (pick["id"], pick["length"], pick["lanes"], pick["frm"], pick["to"], k))

    # rotate so the link runs left-to-right
    raw = pick["pts"]
    theta = math.atan2(raw[-1][1] - raw[0][1], raw[-1][0] - raw[0][0])
    pts = rotate(raw, -theta)
    cum = cumlen(pts)
    total = cum[-1]
    half = LANE_W * pick["lanes"] / 2.0
    cell_w = total / k

    fig = plt.figure(figsize=(11.0, 3.5))
    gs = fig.add_gridspec(1, 2, width_ratios=[2.9, 1.0], wspace=0.04)
    ax = fig.add_subplot(gs[0, 0])
    axl = fig.add_subplot(gs[0, 1])

    # ---- (a) the road with its cells ------------------------------------- #
    left, right = [], []
    for s in [i * 1.0 for i in range(int(total) + 1)] + [total]:
        p = point_at(pts, cum, s)
        n = normal_at(pts, cum, s)
        left.append((p[0] + half * n[0], p[1] + half * n[1]))
        right.append((p[0] - half * n[0], p[1] - half * n[1]))
    ax.add_patch(Polygon(left + right[::-1], closed=True, facecolor="#E8E3DC",
                         edgecolor="#8D6E63", lw=0.8, zorder=1))

    if pick["lanes"] >= 2:                       # lane divider
        mid = [point_at(pts, cum, s) for s in [i * 1.0 for i in range(int(total) + 1)]]
        ax.plot([p[0] for p in mid], [p[1] for p in mid], color="white",
                lw=0.6, ls=(0, (4, 3)), zorder=2)

    bounds = [i * total / k for i in range(k + 1)]
    for s in bounds[1:-1]:                       # cell boundaries
        p = point_at(pts, cum, s)
        n = normal_at(pts, cum, s)
        ax.plot([p[0] - half * n[0], p[0] + half * n[0]],
                [p[1] - half * n[1], p[1] + half * n[1]],
                color="#4E342E", lw=1.1, zorder=3)

    for i in range(k):                           # cell numbers, below the band
        s = 0.5 * (bounds[i] + bounds[i + 1])
        p = point_at(pts, cum, s)
        n = normal_at(pts, cum, s)
        ax.text(p[0] - (half + 7.0) * n[0], p[1] - (half + 7.0) * n[1], str(i + 1),
                ha="center", va="center", fontsize=6.8, color="#4E342E", zorder=4)

    for name, at, dy in ((pick["frm"], pts[0], 1), (pick["to"], pts[-1], 1)):
        ax.add_patch(Rectangle((at[0] - 8, at[1] - 8), 16, 16, facecolor="#CFD8DC",
                               edgecolor="#37474F", lw=1.0, zorder=5))
        ax.text(at[0], at[1] + 15 * dy, name, ha="center", va="bottom",
                fontsize=7.2, color="#263238", zorder=5)

    # travel direction, offset above the band so it crosses nothing
    p0 = point_at(pts, cum, 0.22 * total)
    n0 = normal_at(pts, cum, 0.22 * total)
    p1 = point_at(pts, cum, 0.55 * total)
    n1 = normal_at(pts, cum, 0.55 * total)
    off = half + 11.0
    ax.add_patch(FancyArrowPatch((p0[0] + off * n0[0], p0[1] + off * n0[1]),
                                 (p1[0] + off * n1[0], p1[1] + off * n1[1]),
                                 arrowstyle="-|>", mutation_scale=11, lw=1.2,
                                 color="#1565C0", zorder=6))
    ax.text((p0[0] + p1[0]) / 2 + off * n0[0], (p0[1] + p1[1]) / 2 + off * n0[1] + 5,
            "direction of travel", ha="center", va="bottom", fontsize=6.8,
            color="#1565C0")

    # dimension line under cell 1
    a = point_at(pts, cum, bounds[0])
    b = point_at(pts, cum, bounds[1])
    ydim = a[1] - half - 18.0
    ax.annotate("", xy=(a[0], ydim), xytext=(b[0], ydim),
                arrowprops=dict(arrowstyle="<|-|>", lw=0.7, color="#8D6E63",
                                mutation_scale=7))
    ax.text((a[0] + b[0]) / 2, ydim - 4, "%.1f m" % cell_w, ha="center", va="top",
            fontsize=6.8, color="#4E342E")

    # scale bar
    x0 = min(p[0] for p in left) - 6
    y0 = min(p[1] for p in right) - 34
    ax.plot([x0, x0 + 50], [y0, y0], color="#263238", lw=2.4, solid_capstyle="butt")
    ax.text(x0 + 25, y0 + 3, "50 m", ha="center", va="bottom", fontsize=6.8)

    ax.set_title("(a)  %d cells on the real link  (%s, %.0f m, %d lanes)"
                 % (k, pick["id"], pick["length"], pick["lanes"]),
                 fontsize=8.5, loc="left")
    ax.text(0.0, -0.20,
            "k = ceil(int(length)/int(L)) = %d cells;  drawn cell = length/k = %.1f m;  nominal L = 27.8 m" % (k, cell_w),
            transform=ax.transAxes, fontsize=6.8, style="italic", color="#4E342E")
    ax.set_aspect("equal")
    ax.set_axis_off()

    # ---- (b) locator, zoomed --------------------------------------------- #
    cxp = sum(p[0] for p in raw) / len(raw)
    cyp = sum(p[1] for p in raw) / len(raw)
    for e in edges.values():
        xs = [p[0] for p in e["pts"]]
        ys = [p[1] for p in e["pts"]]
        if max(xs) < cxp - WINDOW or min(xs) > cxp + WINDOW:
            continue
        if max(ys) < cyp - WINDOW or min(ys) > cyp + WINDOW:
            continue
        axl.plot(xs, ys, color="#B0BEC5", lw=0.6, alpha=0.8, zorder=1)
    xs_raw = [p[0] for p in raw]
    ys_raw = [p[1] for p in raw]
    # white casing first: the link must read as lying ON the grey network,
    # not as a bar dropped beside it
    axl.plot(xs_raw, ys_raw, color="white", lw=5.4, zorder=2,
             solid_capstyle="round")
    axl.plot(xs_raw, ys_raw, color="#C0504D", lw=3.0,
             zorder=3, solid_capstyle="round")
    axl.scatter([raw[0][0], raw[-1][0]], [raw[0][1], raw[-1][1]], s=16,
                color="#37474F", zorder=4)
    # mark a cordon end explicitly, so the empty side of the panel reads as
    # "outside the model" rather than "the link left the road"
    for _n in (pick["frm"], pick["to"]):
        if _n.startswith("x") and _n in junc:
            _p = junc[_n]
            axl.scatter([_p[0]], [_p[1]], s=26, marker="^", color="#548235",
                        zorder=5)
            axl.annotate("cordon", _p, textcoords="offset points",
                         xytext=(6, 3), fontsize=6.4, color="#2E5020",
                         zorder=6)
    axl.set_xlim(cxp - WINDOW, cxp + WINDOW)
    axl.set_ylim(cyp - WINDOW, cyp + WINDOW)
    axl.set_title("(b)  where it sits (±%d m)" % WINDOW, fontsize=8.5, loc="left")
    axl.set_aspect("equal")
    axl.set_axis_off()

    # Render to a scratch file, then copy over the canonical PNG. A viewer
    # holding ctm_cells_on_road.png open makes PIL's save fail with
    # OSError 22 on Windows, which used to abort the script after the whole
    # figure had been drawn.
    _tmp = "_ctm_out.png"
    plt.savefig(_tmp, dpi=300, bbox_inches="tight", facecolor="white")
    try:
        shutil.copyfile(_tmp, "ctm_cells_on_road.png")
        print("saved ctm_cells_on_road.png")
    except OSError as _e:
        print("[WARN] could not overwrite ctm_cells_on_road.png (%s); "
              "fresh render left in %s -- close any viewer holding the PNG "
              "and rerun to update it" % (_e, _tmp))


if __name__ == "__main__":
    main()
