"""make_logan_corridor_map.py -- Logan Road corridor context map, KG-figure style.

Matches the Kelvin Grove figure used in the preprint (corridor_kg_bw2_hires.pdf):

  greyscale OSM street network drawn as vectors (major = black, minor = dark
  grey, local = pale grey), green dots at the signalised intersections with the
  Aimsun ID in a small white box, bold corridor title, north arrow, legend,
  OSM attribution. Portrait, 5.5 x 10 in, vector PDF for \\includegraphics.

Junction positions come from the run telemetry, not hand typing:
logan_road_new/logs/detection_points_*.geojson holds one point per detected
vehicle tagged with junction_id in EPSG:32756. A few points in that export sit
in a mixed frame, so each ID is reduced to its MEDIAN easting/northing. The
model splits several physical intersections across multiple Aimsun IDs. With
CLUSTER_M = 0 every ID gets its own dot, and labels are placed by a greedy
collision-avoiding search: the three near-duplicate pairs (4--13 m apart) sit on
top of one another at this scale, so each label is pushed clear on a leader
line instead of overprinting its neighbour.

    python make_logan_corridor_map.py
    -> corridor_logan_bw2_hires.pdf / .png
"""
import collections
import glob
import json
import math
import os
import statistics as st

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from pyproj import Transformer

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_PDF = os.path.join(ROOT, "corridor_logan_bw2_hires.pdf")
OUT_PNG = os.path.join(ROOT, "corridor_logan_bw2_hires.png")

CLUSTER_M = 0.0      # metres; 0 = every Aimsun ID gets its own dot
PAD_M = 300.0

GREEN = "#2E9E4F"
GREEN_HALO = "#FFFFFF"
TITLE_C = "#111827"
MAJOR_C = "#000000"
MINOR_C = "#3A3A3A"
LOCAL_C = "#D2D2D2"

MAJOR = {"motorway", "motorway_link", "trunk", "trunk_link",
         "primary", "primary_link"}
MINOR = {"secondary", "secondary_link", "tertiary", "tertiary_link"}
SKIP = {"footway", "path", "cycleway", "steps", "pedestrian", "bridleway",
        "corridor", "track", "construction", "proposed", "raceway", "busway"}

TO_LL = Transformer.from_crs(32756, 4326, always_xy=True)
TO_MC = Transformer.from_crs(4326, 3857, always_xy=True)

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
})


# --------------------------------------------------------------- intersections
def _valid_utm(x, y):
    """False for telemetry that is not a position in EPSG:32756 metres.

    The export holds a handful of (0, 0) rows tagged coord-prearm-*: a failed
    coordinate write, not a location. Left in, they pull a junction's median
    toward the origin -- 18942 moves 20.5 m and 21895 9.1 m -- so they are
    dropped before the medians, not after.
    """
    return 1.0e5 <= x <= 8.0e5 and 5.0e6 <= y <= 8.0e6


def load_intersections():
    src = sorted(glob.glob(os.path.join(
        ROOT, "logan_road_new", "logs", "detection_points_*.geojson")))[-1]
    pts = collections.defaultdict(list)
    dropped = 0
    with open(src) as fh:
        for feat in json.load(fh)["features"]:
            x, y = feat["geometry"]["coordinates"]
            if not _valid_utm(x, y):
                dropped += 1
                continue
            pts[feat["properties"]["junction_id"]].append((x, y))
    if dropped:
        print("dropped %d mixed-frame point(s) before taking medians" % dropped)
    pos = {j: (st.median([p[0] for p in v]), st.median([p[1] for p in v]))
           for j, v in pts.items()}

    ids = sorted(pos)
    parent = {i: i for i in ids}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]) < CLUSTER_M:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

    groups = collections.defaultdict(list)
    for i in ids:
        groups[find(i)].append(i)

    out = []
    for members in groups.values():
        x = st.mean(pos[m][0] for m in members)
        y = st.mean(pos[m][1] for m in members)
        lon, lat = TO_LL.transform(x, y)
        mx, my = TO_MC.transform(lon, lat)
        out.append({"ids": sorted(members), "lon": lon, "lat": lat,
                    "mx": mx, "my": my})
    out.sort(key=lambda r: -r["lat"])
    return src, out


# ------------------------------------------------------------------ osm roads
def road_segments(west, south, east, north):
    import osmnx as ox
    G = ox.graph_from_bbox(bbox=(west, south, east, north), network_type="all",
                           simplify=True, truncate_by_edge=True)
    res = ox.graph_to_gdfs(G, nodes=False)
    edges = res if not isinstance(res, tuple) else res[1]   # osmnx 2.x returns one frame
    buckets = {"major": [], "minor": [], "local": []}
    for geom, hw in zip(edges.geometry, edges["highway"]):
        tags = set(hw) if isinstance(hw, (list, tuple)) else {hw}
        if tags & SKIP:
            continue
        (buckets["major"] if tags & MAJOR else
         buckets["minor"] if tags & MINOR else buckets["local"])
        key = ("major" if tags & MAJOR else
               "minor" if tags & MINOR else "local")
        xs, ys = zip(*list(geom.coords))
        mx, my = TO_MC.transform(xs, ys)
        buckets[key].append(list(zip(mx, my)))
    return G, buckets


# --------------------------------------------------------------------- labels
LABEL_FS = 4.6
LABEL_RINGS_PT = (4, 6, 9, 13, 18, 24, 31, 39, 48, 58, 70, 84, 100)
LABEL_ANGLES_DEG = (0, -20, 20, -40, 40, -60, 60, -80, 80, -100, 100,
                    -120, 120, -140, 140, 180)
SIBLING_PX = 12.0   # dots closer than this on screen are the same blob


def _crowded(ints, radius_m=25.0):
    """Junctions with a neighbour within radius_m: the ones whose labels must be
    separated, so they are placed first while there is room around them."""
    out = set()
    for i, a in enumerate(ints):
        for b in ints[i + 1:]:
            if math.hypot(a["mx"] - b["mx"], a["my"] - b["my"]) < radius_m:
                out.add(id(a))
                out.add(id(b))
    return out


PAD_PT = 3.2        # label box padding: bbox pad + border, in points
GAP_PT = 1.0        # minimum clear space between two label boxes
DOT_R_PT = 4.2      # marker radius to keep clear, in points


def place_labels(ax, fig, ints):
    """Greedy label placement, all arithmetic in axes fractions.

    The three near-duplicate pairs sit 4--13 m apart, which at this scale is a
    fraction of a millimetre, so the labels cannot be offset in data units.
    Each label gets the nearest free slot: rings around its own dot first, then
    a full grid over the frame if no ring slot is free. A leader line is drawn
    whenever the label ends up more than a few points away from its dot.

    Label sizes come from TextPath (points) divided by the axes size (points),
    so no renderer state is involved and the result cannot depend on when the
    canvas was last drawn.
    """
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    fig.canvas.draw()
    ax_w_pt = ax.bbox.width * 72.0 / fig.dpi
    ax_h_pt = ax.bbox.height * 72.0 / fig.dpi
    inv = ax.transAxes.inverted()

    items = []
    for r in ints:
        d = ax.transData.transform((r["mx"], r["my"]))
        fx, fy = inv.transform(d)
        items.append((r, (float(fx), float(fy))))

    crowded = _crowded(ints)
    items.sort(key=lambda it: (id(it[0]) not in crowded, -it[0]["my"]))
    dots = [d for _, d in items]

    font = FontProperties(family="DejaVu Sans", size=LABEL_FS)
    sib = SIBLING_PX * 72.0 / fig.dpi / ax_w_pt

    boxes = []
    n_grid = 0
    for r, (fx, fy) in items:
        text = "/".join(str(i) for i in r["ids"])
        tp = TextPath((0, 0), text, prop=font).get_extents()
        w = (tp.width + PAD_PT + GAP_PT) / ax_w_pt
        h = (tp.height + PAD_PT + GAP_PT) / ax_h_pt

        far = [d for d in dots if math.hypot(d[0] - fx, d[1] - fy) > sib]

        def fits(cx, cy):
            x0, y0 = cx - w / 2.0, cy - h / 2.0
            x1, y1 = cx + w / 2.0, cy + h / 2.0
            m = 0.004
            if x0 < m or y0 < m or x1 > 1.0 - m or y1 > 1.0 - m:
                return False
            for b in boxes:
                if x0 < b[2] and b[0] < x1 and y0 < b[3] and b[1] < y1:
                    return False
            for d in far:
                # keep clear of the marker itself, not only its centre: a box
                # that clips a dot hides the junction it is meant to name
                gx = max(x0 - d[0], 0.0, d[0] - x1) * ax_w_pt
                gy = max(y0 - d[1], 0.0, d[1] - y1) * ax_h_pt
                if math.hypot(gx, gy) < DOT_R_PT:
                    return False
            return True

        best = None
        for rad in LABEL_RINGS_PT:
            rx, ry = rad / ax_w_pt, rad / ax_h_pt
            for ang in LABEL_ANGLES_DEG:
                a = math.radians(ang)
                cx, cy = fx + rx * math.cos(a), fy + ry * math.sin(a)
                if fits(cx, cy):
                    best = (cx, cy, rad)
                    break
            if best:
                break

        if best is None:
            n_grid += 1
            bestd = None
            step = 0.01
            gy = 0.0
            while gy <= 1.0:
                gx = 0.0
                while gx <= 1.0:
                    if fits(gx, gy):
                        d = math.hypot((gx - fx) * ax_w_pt, (gy - fy) * ax_h_pt)
                        if bestd is None or d < bestd:
                            bestd, best = d, (gx, gy, d)
                    gx += step
                gy += step

        dx_pt = (best[0] - fx) * ax_w_pt
        dy_pt = (best[1] - fy) * ax_h_pt
        dist = math.hypot(dx_pt, dy_pt)
        ax.annotate(
            text, (r["mx"], r["my"]), xytext=(dx_pt, dy_pt),
            textcoords="offset points", ha="center", va="center",
            fontsize=LABEL_FS, color="#111111", zorder=6,
            arrowprops=(dict(arrowstyle="-", lw=0.35, color="#8A8A8A",
                             shrinkA=0.0, shrinkB=2.0)
                        if dist > 6.0 else None),
            bbox=dict(boxstyle="round,pad=0.28", fc="white",
                      ec="#9A9A9A", lw=0.45, alpha=0.95))
        boxes.append((best[0] - w / 2.0, best[1] - h / 2.0,
                      best[0] + w / 2.0, best[1] + h / 2.0))

    if n_grid:
        print("labels resolved by the grid search: %d" % n_grid)


# -------------------------------------------------------------------- drawing
def main():
    src, ints = load_intersections()
    n_ids = sum(len(r["ids"]) for r in ints)
    print("source:", os.path.relpath(src, ROOT))
    print("%d intersections from %d Aimsun junction IDs" % (len(ints), n_ids))

    lat0 = st.mean(r["lat"] for r in ints)
    pad = PAD_M / math.cos(math.radians(lat0))
    x0 = min(r["mx"] for r in ints) - pad
    x1 = max(r["mx"] for r in ints) + pad
    y0 = min(r["my"] for r in ints) - pad
    y1 = max(r["my"] for r in ints) + pad
    to_ll = Transformer.from_crs(3857, 4326, always_xy=True)
    west, south = to_ll.transform(x0, y0)
    east, north = to_ll.transform(x1, y1)

    G, buckets = road_segments(west, south, east, north)
    print("osm edges: major %d, minor %d, local %d"
          % tuple(len(buckets[k]) for k in ("major", "minor", "local")))

    fig, ax = plt.subplots(figsize=(5.5, 10))
    ax.set_facecolor("white")
    ax.add_collection(LineCollection(buckets["local"], colors=LOCAL_C,
                                     linewidths=0.32, zorder=1))
    ax.add_collection(LineCollection(buckets["minor"], colors=MINOR_C,
                                     linewidths=0.7, zorder=2))
    ax.add_collection(LineCollection(buckets["major"], colors=MAJOR_C,
                                     linewidths=1.5, zorder=3))

    xs = [r["mx"] for r in ints]
    ys = [r["my"] for r in ints]
    ax.scatter(xs, ys, s=150, c=GREEN_HALO, linewidths=0, zorder=4)
    ax.scatter(xs, ys, s=52, c=GREEN, edgecolors="#1B6B36", linewidths=0.5,
               zorder=5)

    span_x, span_y = x1 - x0, y1 - y0
    place_labels(ax, fig, ints)

    # north arrow: top-RIGHT, the top-left is where the first junctions sit
    ax_x, ax_y = x0 + 0.93 * span_x, y1 - 0.115 * span_y
    ax.annotate("", xy=(ax_x, ax_y + 0.075 * span_y), xytext=(ax_x, ax_y),
                arrowprops=dict(arrowstyle="-|>", color="black", lw=2.4,
                                mutation_scale=16), zorder=7)
    ax.text(ax_x, ax_y + 0.082 * span_y, "N", ha="center", va="bottom",
            fontsize=8, fontweight="bold", color="black", zorder=7)

    # legend, bottom-left
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], color=MAJOR_C, lw=1.5, label="Major road"),
        Line2D([0], [0], color=MINOR_C, lw=0.8, label="Minor road"),
        Line2D([0], [0], color=LOCAL_C, lw=0.8, label="Local street"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=GREEN,
               markeredgecolor="#1B6B36", markersize=6, label="Intersection"),
    ]
    leg = ax.legend(handles=handles, loc="lower left", frameon=True,
                    facecolor="white", edgecolor="#9A9A9A", framealpha=0.95,
                    fontsize=6.4, handlelength=1.9, borderpad=0.42,
                    labelspacing=0.28, handletextpad=0.6)
    leg.set_zorder(8)

    ax.text(x1, y0, "© OpenStreetMap contributors", ha="right", va="bottom",
            fontsize=5.2, style="italic", color="#555555", zorder=7)

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_axis_off()
    subtitle = ("%d Aimsun junctions" % n_ids if n_ids == len(ints) else
                "%d Aimsun junctions at %d map points" % (n_ids, len(ints)))
    ax.set_title("Logan Road Corridor\n" + subtitle,
                 fontsize=12.5, fontweight="bold", color=TITLE_C, pad=8,
                 linespacing=1.25)

    fig.savefig(OUT_PDF)
    fig.savefig(OUT_PNG, dpi=300)
    plt.close(fig)
    print("wrote", os.path.basename(OUT_PDF), os.path.getsize(OUT_PDF) // 1024, "KB")
    print("wrote", os.path.basename(OUT_PNG), os.path.getsize(OUT_PNG) // 1024, "KB")


if __name__ == "__main__":
    main()
