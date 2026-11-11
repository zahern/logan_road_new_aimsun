"""make_logan_context_figure.py -- geographic + functional context for Logan Road.

Two panels, matching the Kelvin Grove context figure:

  (a) OpenStreetMap basemap of the corridor, with the 13 signalised
      intersections as green dots labelled by Aimsun junction ID.
  (b) Functional schematic in route order (north at top).

Junction positions are recovered from the run telemetry, not hand-typed:
logan_road_new/logs/detection_points_*.geojson carries one point per detected
vehicle, tagged with junction_id, in EPSG:32756. A few points in that export
sit in a mixed frame, so each junction is reduced to the MEDIAN easting and
northing. The model splits several physical intersections across multiple
Aimsun junction IDs, so IDs within CLUSTER_M of one another are merged into a
single dot; the schematic lists every ID in the compound.

    python make_logan_context_figure.py
    -> logan_corridor_context.pdf / .png
"""
import collections
import glob
import io
import json
import math
import os
import statistics as st

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import requests
from PIL import Image
from pyproj import Transformer

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_PDF = os.path.join(ROOT, "logan_corridor_context.pdf")
OUT_PNG = os.path.join(ROOT, "logan_corridor_context.png")

CLUSTER_M = 150.0          # junction IDs closer than this are one intersection
ZOOM = 15
PAD_M = 330.0              # basemap margin beyond the junction envelope
TILE_URL = "https://tile.openstreetmap.org/%d/%d/%d.png"
UA = "bcc113-logan-corridor-figure/1.0 (research figure; contact: local)"

GREEN = "#1E8F4E"
DOT_EDGE = "#FFFFFF"
INK = "#1A1A1A"
GREY = "#555555"

plt.rcParams.update({
    "font.family": "Arial",
    "font.size": 7,
    "axes.labelsize": 7,
    "axes.titlesize": 7.5,
    "legend.fontsize": 6.5,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02,
})

TO_LL = Transformer.from_crs(32756, 4326, always_xy=True)   # UTM 56S -> WGS84
TO_MC = Transformer.from_crs(4326, 3857, always_xy=True)    # WGS84 -> Web Mercator


# --------------------------------------------------------------- junction data
def load_intersections():
    src = sorted(glob.glob(os.path.join(
        ROOT, "logan_road_new", "logs", "detection_points_*.geojson")))[-1]
    pts = collections.defaultdict(list)
    with open(src) as fh:
        for feat in json.load(fh)["features"]:
            x, y = feat["geometry"]["coordinates"]
            pts[feat["properties"]["junction_id"]].append((x, y))

    # median position per Aimsun junction ID (robust to the mixed-frame points)
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
        out.append({"ids": sorted(members), "lon": lon, "lat": lat})
    out.sort(key=lambda r: -r["lat"])          # north -> south = route order
    for n, r in enumerate(out, 1):
        r["j"] = n
        r["mx"], r["my"] = TO_MC.transform(r["lon"], r["lat"])
        r["primary"] = r["ids"][0]
        r["idtxt"] = "/".join(str(i) for i in r["ids"])
    return src, out


# ------------------------------------------------------------------- basemap
def merc_tile_range(x0, x1, y0, y1, z):
    world = 2 * math.pi * 6378137.0
    span = world / 2 ** z
    tx0 = int(math.floor((x0 + world / 2) / span))
    tx1 = int(math.floor((x1 + world / 2) / span))
    ty0 = int(math.floor((world / 2 - y1) / span))
    ty1 = int(math.floor((world / 2 - y0) / span))
    return tx0, tx1, ty0, ty1, span


def fetch_basemap(x0, x1, y0, y1, z):
    tx0, tx1, ty0, ty1, span = merc_tile_range(x0, x1, y0, y1, z)
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    canvas = Image.new("RGB", (nx * 256, ny * 256), "white")
    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    n = 0
    for i, tx in enumerate(range(tx0, tx1 + 1)):
        for k, ty in enumerate(range(ty0, ty1 + 1)):
            r = sess.get(TILE_URL % (z, tx, ty), timeout=20)
            if r.status_code == 200:
                canvas.paste(Image.open(io.BytesIO(r.content)).convert("RGB"),
                             (i * 256, k * 256))
                n += 1
    if n == 0:
        raise SystemExit("no OSM tiles fetched -- check network access")
    world = 2 * math.pi * 6378137.0
    ext = (-world / 2 + tx0 * span, -world / 2 + (tx1 + 1) * span,
           world / 2 - (ty1 + 1) * span, world / 2 - ty0 * span)
    print("basemap: %d tiles at z%d, %dx%d px" % (n, z, canvas.width, canvas.height))
    return canvas, ext


# --------------------------------------------------------------------- figure
def main():
    src, ints = load_intersections()
    print("source:", os.path.relpath(src, ROOT))
    print("%d intersections from %d Aimsun junction IDs"
          % (len(ints), sum(len(r["ids"]) for r in ints)))
    for r in ints:
        print("  J%-2d %8.5f %9.5f  %s" % (r["j"], r["lat"], r["lon"], r["idtxt"]))

    lat0 = st.mean(r["lat"] for r in ints)
    pad = PAD_M / math.cos(math.radians(lat0))      # Mercator is scale-inflated
    x0 = min(r["mx"] for r in ints) - pad
    x1 = max(r["mx"] for r in ints) + pad
    y0 = min(r["my"] for r in ints) - pad
    y1 = max(r["my"] for r in ints) + pad
    img, ext = fetch_basemap(x0, x1, y0, y1, ZOOM)

    fig = plt.figure(figsize=(7.1, 4.75))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 0.60], wspace=0.04)
    ax = fig.add_subplot(gs[0])
    axs = fig.add_subplot(gs[1])

    # ---- (a) geographic context
    ax.imshow(img, extent=ext, zorder=0, interpolation="bilinear")
    xs = [r["mx"] for r in ints]
    ys = [r["my"] for r in ints]
    ax.plot(xs, ys, "-", color="#2B2B2B", lw=1.0, alpha=0.55, zorder=2,
            solid_capstyle="round")
    ax.scatter(xs, ys, s=34, c=GREEN, edgecolors=DOT_EDGE, linewidths=0.6,
               zorder=5)
    for r in ints:
        right = (r["j"] % 2 == 0)
        dx = 100 if right else -100
        dy = 55 if r["j"] % 3 else -55     # stagger at-both-sides pairs
        ha = "left" if right else "right"
        ax.annotate(str(r["primary"]), (r["mx"], r["my"]),
                    xytext=(r["mx"] + dx, r["my"] + dy), textcoords="data",
                    fontsize=4.9, color="#0F3D22", ha=ha, va="center",
                    zorder=6,
                    arrowprops=dict(arrowstyle="-", color="0.45", lw=0.4,
                                    shrinkA=0.5, shrinkB=2.5),
                    bbox=dict(boxstyle="round,pad=0.10", fc="white", ec="none",
                              alpha=0.78))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("(a)  Logan Road corridor: %d signalised intersections\n"
                 "on OpenStreetMap; dots labelled with Aimsun junction ID"
                 % len(ints), loc="left", pad=4)

    # all three annotations are anchored to the VISIBLE limits, not the tile grid
    xw, yw = x1 - x0, y1 - y0

    # scale bar (500 m of ground distance, converted to Mercator units)
    sb = 500.0 / math.cos(math.radians(lat0))
    sx, sy = x0 + 0.06 * xw, y0 + 0.055 * yw
    ax.plot([sx, sx + sb], [sy, sy], color=INK, lw=1.6, zorder=7,
            solid_capstyle="butt")
    ax.text(sx + sb / 2, sy + 0.012 * yw, "500 m",
            ha="center", va="bottom", fontsize=5, color=INK, zorder=7)

    # north arrow
    nx_, ny_ = x1 - 0.08 * xw, y1 - 0.21 * yw
    ax.annotate("", xy=(nx_, ny_ + 0.09 * yw), xytext=(nx_, ny_),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=0.8,
                                mutation_scale=7), zorder=7)
    ax.text(nx_, ny_ + 0.10 * yw, "N", ha="center", va="bottom",
            fontsize=5.5, color=INK, zorder=7)
    ax.text(x1, y0 + 0.014 * yw, "© OpenStreetMap contributors", ha="right",
            va="bottom", fontsize=4.0, color="#333333", zorder=7,
            bbox=dict(boxstyle="square,pad=0.10", fc="white", ec="none",
                      alpha=0.70))

    # ---- (b) functional schematic
    n = len(ints)
    axs.set_xlim(-1.05, 1.55)
    axs.set_ylim(-0.9, n + 0.45)
    axs.plot([0, 0], [-0.55, n - 0.45], color=INK, lw=2.2, solid_capstyle="round",
             zorder=1)
    for k, r in enumerate(ints):
        y = n - 1 - k
        for sgn in (-1, 1):
            axs.plot([0, sgn * 0.42], [y, y], color=INK, lw=0.9, zorder=2)
            axs.plot([sgn * 0.42, sgn * 0.42], [y, y], color=INK, lw=0.9)
        axs.scatter([0], [y], s=26, c=GREEN, edgecolors=DOT_EDGE, linewidths=0.5,
                    zorder=4)
        axs.text(-0.50, y, "J%d" % r["j"], ha="right", va="center", fontsize=6.2,
                 color=INK)
        axs.text(0.50, y, r["idtxt"], ha="left", va="center", fontsize=4.9,
                 color="#0F3D22" if "/" not in r["idtxt"] else GREY)
    axs.annotate("", xy=(0, n + 0.22), xytext=(0, n - 0.55),
                 arrowprops=dict(arrowstyle="-|>", color=INK, lw=0.7,
                                 mutation_scale=6))
    axs.text(0.06, n + 0.10, "N", fontsize=5.5, va="bottom", color=INK)
    axs.text(-0.5, -0.62, "main road", fontsize=4.8, color=GREY, ha="right")
    axs.text(0.5, -0.62, "Aimsun IDs", fontsize=4.8, color=GREY, ha="left")
    axs.set_axis_off()
    axs.set_title("(b)  Functional schematic, route order\n"
                  "(compound intersections show every Aimsun ID)", loc="left", pad=4)

    fig.savefig(OUT_PDF)
    fig.savefig(OUT_PNG, dpi=300)
    plt.close(fig)
    print("wrote", os.path.basename(OUT_PDF), os.path.getsize(OUT_PDF) // 1024, "KB")
    print("wrote", os.path.basename(OUT_PNG), os.path.getsize(OUT_PNG) // 1024, "KB")


if __name__ == "__main__":
    main()
