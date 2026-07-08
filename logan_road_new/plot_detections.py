"""
plot_detections.py
==================
Standalone script — run from the command line OR called automatically by
intersection_controller.py at the end of a simulation (AAPIFinish).

Usage
-----
    python plot_detections.py [detection_csv] [junction_csv] [out_png] [out_html]

Outputs
-------
  <stem>.png      — Model-coordinate plot (always produced).
                    Blue squares = intersections; coloured circles = detections.
                    Intersections are the spatial reference — no reprojection needed.

  <stem>_osm.png  — Same content reprojected onto an OSM tile background.
                    Requires:  pip install contextily pyproj

  <stem>.html     — Interactive folium map with click-for-detail popups.
                    Requires:  pip install folium pyproj

Coordinate system
-----------------
SE Queensland (Logan Road) uses GDA2020 MGA Zone 56 — EPSG:7856.
Edit AIMSUN_CRS below if your model uses a different projection.
"""

import os
import sys
import csv
import glob

_AIMSUN_PACKAGES = r"C:\AimsunPackages"
if os.path.isdir(_AIMSUN_PACKAGES) and _AIMSUN_PACKAGES not in sys.path:
    sys.path.insert(0, _AIMSUN_PACKAGES)

# Inject the shared project venv so contextily/folium/pyproj/etc. are importable
# when this script is called from inside Aimsun.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
for _vsp in [
    os.path.join(_THIS_DIR, '..', 'logan_road_new', '.venv', 'Lib', 'site-packages'),
    os.path.join(_THIS_DIR, '.venv', 'Lib', 'site-packages'),
]:
    _vsp = os.path.normpath(_vsp)
    if os.path.isdir(_vsp) and _vsp not in sys.path:
        sys.path.insert(1, _vsp)
        break
del _THIS_DIR, _vsp

# ── Projection used in the Aimsun model ───────────────────────────────────────
AIMSUN_CRS = "EPSG:7856"   # GDA2020 MGA Zone 56 (SE QLD)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _find_latest(log_dir: str, pattern: str) -> str | None:
    files = sorted(glob.glob(os.path.join(log_dir, pattern)))
    return files[-1] if files else None


def _load_detections(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "t":    float(row["sim_time_s"]),
                    "jct":  int(row["junction_id"]),
                    "vid":  int(row["veh_id"]),
                    "x":    float(row["x"]),
                    "y":    float(row["y"]),
                    "tier": row["tier"],
                })
            except (KeyError, ValueError):
                continue
    return rows


def _load_junctions(path: str) -> dict[int, tuple[float, float]]:
    junctions: dict[int, tuple[float, float]] = {}
    if not path or not os.path.isfile(path):
        return junctions
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                junctions[int(row["junction_id"])] = (
                    float(row["x"]), float(row["y"]))
            except (KeyError, ValueError):
                continue
    return junctions


# ---------------------------------------------------------------------------
# Shared colour helpers
# ---------------------------------------------------------------------------

_TIER_COLORS_MPL = [
    ("#e53935", lambda t: "IC-detect" in t or "PT-coord" in t),
    ("#8e24aa", lambda t: "coord-prearm" in t),
    ("#fb8c00", lambda t: "sec" in t),
    ("#fdd835", lambda t: "det" in t),
]
_FALLBACK_COLORS = ["#00897b", "#1e88e5", "#d81b60", "#6d4c41"]

def _mpl_color(tier: str, idx: int = 0) -> str:
    for color, test in _TIER_COLORS_MPL:
        if test(tier):
            return color
    return _FALLBACK_COLORS[idx % len(_FALLBACK_COLORS)]


def _tier_label(tier: str) -> str:
    if "IC-detect" in tier or "PT-coord" in tier:
        return "Bus detected (PT/IC scan)"
    if "coord-prearm" in tier:
        return "Pre-armed by coordinator"
    if "sec" in tier:
        return "Bus detected (section scan)"
    if "det" in tier:
        return "Bus detected (detector)"
    return f"Bus detected ({tier})"


# ---------------------------------------------------------------------------
# Plot 1 — model coordinates (always works, no reprojection)
# ---------------------------------------------------------------------------

def plot_model_coords(rows: list[dict], junctions: dict,
                      out_path: str, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe

    # Exclude (0,0) placeholder points that have no real coordinates
    valid       = [r for r in rows if not (r["x"] == 0.0 and r["y"] == 0.0)]
    n_placeholders = len(rows) - len(valid)

    fig, ax = plt.subplots(figsize=(16, 12))
    ax.set_facecolor("#f0f0f0")
    ax.set_aspect("equal")

    # Intersection centroids — blue squares, labelled
    jct_added = False
    for jid, (jx, jy) in junctions.items():
        ax.plot(jx, jy, "s", color="#1a73e8", markersize=14,
                markeredgecolor="white", markeredgewidth=1.5, zorder=4,
                label="Intersection" if not jct_added else "")
        jct_added = True
        ax.annotate(
            str(jid), (jx, jy),
            textcoords="offset points", xytext=(0, 10),
            ha="center", fontsize=7, fontweight="bold", color="#1a73e8",
            path_effects=[pe.withStroke(linewidth=2, foreground="white")],
            zorder=5,
        )

    # Detection points grouped by normalised tier label
    groups: dict[str, list] = {}
    for r in valid:
        groups.setdefault(_tier_label(r["tier"]), []).append(r)

    for idx, (label, pts) in enumerate(groups.items()):
        col = _mpl_color(pts[0]["tier"], idx)
        ax.scatter([p["x"] for p in pts], [p["y"] for p in pts],
                   c=col, s=55, zorder=6, alpha=0.85,
                   edgecolors="white", linewidths=0.5,
                   label=f"{label} (n={len(pts)})")

    # Thin grey lines from each detection to its junction
    for r in valid:
        jxy = junctions.get(r["jct"])
        if jxy:
            ax.plot([r["x"], jxy[0]], [r["y"], jxy[1]],
                    color="grey", lw=0.4, alpha=0.3, zorder=2)

    if n_placeholders:
        ax.text(0.02, 0.02,
                f"Note: {n_placeholders} point(s) had no XY (junction XY not "
                "resolved in model) — omitted",
                transform=ax.transAxes, fontsize=8, color="#c62828", va="bottom")

    # Scale bar — 8 % of x range
    xl, xr = ax.get_xlim()
    yl, yr = ax.get_ylim()
    sb  = (xr - xl) * 0.08
    sbx = xl + (xr - xl) * 0.05
    sby = yl + (yr - yl) * 0.03
    ax.plot([sbx, sbx + sb], [sby, sby], "k-", lw=3, zorder=7)
    ax.text(sbx + sb / 2, sby + (yr - yl) * 0.012,
            f"{sb:.0f} m", ha="center", fontsize=7)

    ax.set_title(title, fontsize=12, pad=10)
    ax.set_xlabel("Easting (model units)", fontsize=9)
    ax.set_ylabel("Northing (model units)", fontsize=9)
    ax.ticklabel_format(style="plain", axis="both")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9, markerscale=1.2)
    ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[plot_detections] Model-coord PNG: {out_path}")


# ---------------------------------------------------------------------------
# Plot 2 — OSM tile overlay (requires contextily + pyproj)
# ---------------------------------------------------------------------------

def plot_osm(rows: list[dict], junctions: dict,
             out_path: str, title: str) -> None:
    import contextily as ctx  # type: ignore[import-untyped]
    import pyproj              # type: ignore[import-untyped]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe

    transformer = pyproj.Transformer.from_crs(
        AIMSUN_CRS, "EPSG:3857", always_xy=True)

    def _proj(px: float, py: float) -> tuple[float, float]:
        return transformer.transform(px, py)

    valid = [r for r in rows if not (r["x"] == 0.0 and r["y"] == 0.0)]

    fig, ax = plt.subplots(figsize=(16, 12))

    for jid, (jx, jy) in junctions.items():
        mx, my = _proj(jx, jy)
        ax.plot(mx, my, "s", color="#1a73e8", markersize=12,
                markeredgecolor="white", markeredgewidth=1.5, zorder=5)
        ax.annotate(str(jid), (mx, my),
                    textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=7, fontweight="bold", color="#1a73e8",
                    path_effects=[pe.withStroke(linewidth=2, foreground="white")],
                    zorder=6)

    groups: dict[str, list] = {}
    for r in valid:
        groups.setdefault(_tier_label(r["tier"]), []).append(r)

    for idx, (label, pts) in enumerate(groups.items()):
        col = _mpl_color(pts[0]["tier"], idx)
        proj_pts = [_proj(p["x"], p["y"]) for p in pts]
        mxs = [pt[0] for pt in proj_pts]
        mys = [pt[1] for pt in proj_pts]
        ax.scatter(mxs, mys, c=col, s=60, zorder=6, alpha=0.85,
                   edgecolors="white", linewidths=0.5,
                   label=f"{label} (n={len(pts)})")

    try:
        ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik,
                        zoom="auto", crs="EPSG:3857")
    except Exception as tile_err:
        ax.set_facecolor("#d8e8f0")
        ax.text(0.5, 0.5, f"OSM tiles unavailable:\n{tile_err}",
                transform=ax.transAxes, ha="center", va="center",
                fontsize=9, color="grey")

    ax.set_title(f"{title}  [{AIMSUN_CRS} → OSM]", fontsize=11)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[plot_detections] OSM PNG: {out_path}")


# ---------------------------------------------------------------------------
# Plot 3 — Self-contained HTML (no CDN, no external dependencies)
# ---------------------------------------------------------------------------

def plot_html(rows: list[dict], junctions: dict,
              out_path: str, title: str) -> None:
    """
    Generate a fully self-contained HTML report.

    Embeds the model-coordinate PNG as a base64 data URI so the file opens
    correctly from disk without any CDN or internet access.  Below the map
    image, a searchable/sortable table lists every detection event.

    No external libraries required beyond matplotlib (already imported).
    """
    import base64
    import io
    import html as _html

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe

    valid = [r for r in rows if not (r["x"] == 0.0 and r["y"] == 0.0)]

    # ── 1. Render the model-coords plot to a base64 PNG ─────────────────────
    fig, ax = plt.subplots(figsize=(16, 10))
    ax.set_facecolor("#f0f0f0")
    ax.set_aspect("equal")

    jct_added = False
    for jid, (jx, jy) in junctions.items():
        ax.plot(jx, jy, "s", color="#1a73e8", markersize=14,
                markeredgecolor="white", markeredgewidth=1.5, zorder=4,
                label="Intersection" if not jct_added else "")
        jct_added = True
        ax.annotate(
            str(jid), (jx, jy),
            textcoords="offset points", xytext=(0, 10),
            ha="center", fontsize=7, fontweight="bold", color="#1a73e8",
            path_effects=[pe.withStroke(linewidth=2, foreground="white")],
            zorder=5,
        )

    groups: dict = {}
    for r in valid:
        groups.setdefault(_tier_label(r["tier"]), []).append(r)

    for idx, (label, pts) in enumerate(groups.items()):
        col = _mpl_color(pts[0]["tier"], idx)
        ax.scatter([p["x"] for p in pts], [p["y"] for p in pts],
                   c=col, s=55, zorder=6, alpha=0.85,
                   edgecolors="white", linewidths=0.5,
                   label=f"{label} (n={len(pts)})")

    for r in valid:
        jxy = junctions.get(r["jct"])
        if jxy:
            ax.plot([r["x"], jxy[0]], [r["y"], jxy[1]],
                    color="grey", lw=0.4, alpha=0.3, zorder=2)

    ax.set_title(title, fontsize=11)
    ax.set_xlabel("Easting (model units)", fontsize=9)
    ax.set_ylabel("Northing (model units)", fontsize=9)
    ax.ticklabel_format(style="plain", axis="both")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode("ascii")

    # ── 2. Build detection table rows ────────────────────────────────────────
    sorted_rows = sorted(rows, key=lambda r: r["t"])
    table_rows_html = ""
    for r in sorted_rows:
        row_color = {
            "IC-detect": "#fde8e8",
            "PT-coord":  "#fde8e8",
            "coord-prearm": "#f3e5f5",
            "sec":       "#fff3e0",
        }.get(r["tier"].split("/")[0], "#ffffff")
        table_rows_html += (
            f'<tr style="background:{row_color}">'
            f'<td>{r["t"]:.1f}</td>'
            f'<td>{r["jct"]}</td>'
            f'<td>{r["vid"]}</td>'
            f'<td>{_html.escape(r["tier"])}</td>'
            f'<td>{r["x"]:.1f}</td>'
            f'<td>{r["y"]:.1f}</td>'
            f'</tr>\n'
        )

    # ── 3. Assemble self-contained HTML ──────────────────────────────────────
    esc_title = _html.escape(title)
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{esc_title}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 16px; background: #fafafa; }}
  h2   {{ color: #1a237e; }}
  img  {{ max-width: 100%; border: 1px solid #ccc; border-radius: 4px;
          box-shadow: 2px 2px 6px rgba(0,0,0,.15); }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 24px;
           font-size: 13px; }}
  th   {{ background: #1a237e; color: white; padding: 6px 10px;
          text-align: left; cursor: pointer; }}
  td   {{ padding: 4px 10px; border-bottom: 1px solid #ddd; }}
  tr:hover td {{ background: #e8eaf6 !important; }}
  input {{ margin-bottom: 8px; padding: 6px; width: 300px;
           border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }}
  .legend {{ display:flex; gap:16px; flex-wrap:wrap;
             margin: 12px 0; font-size:13px; }}
  .dot {{ display:inline-block; width:12px; height:12px;
          border-radius:50%; margin-right:4px; vertical-align:middle; }}
</style>
</head>
<body>
<h2>{esc_title}</h2>
<div class="legend">
  <span><span class="dot" style="background:#1a73e8"></span>Intersection centroid</span>
  <span><span class="dot" style="background:#e53935"></span>Bus detected (PT/IC scan)</span>
  <span><span class="dot" style="background:#8e24aa"></span>Coordinator pre-arm</span>
  <span><span class="dot" style="background:#fb8c00"></span>Section scan</span>
  <span><span class="dot" style="background:#fdd835"></span>Detector rising-edge</span>
</div>
<img src="data:image/png;base64,{img_b64}" alt="Detection map">

<h3>Detection Events ({len(rows)} total)</h3>
<input type="text" id="searchBox" onkeyup="filterTable()"
       placeholder="Filter by junction, vehicle, tier ...">
<table id="detTable">
<thead>
<tr>
  <th onclick="sortTable(0)">Sim time (s) &#9650;</th>
  <th onclick="sortTable(1)">Junction</th>
  <th onclick="sortTable(2)">Vehicle ID</th>
  <th onclick="sortTable(3)">Tier</th>
  <th onclick="sortTable(4)">X (model)</th>
  <th onclick="sortTable(5)">Y (model)</th>
</tr>
</thead>
<tbody>
{table_rows_html}
</tbody>
</table>

<script>
function filterTable() {{
  var input = document.getElementById("searchBox").value.toLowerCase();
  var rows = document.getElementById("detTable").getElementsByTagName("tr");
  for (var i = 1; i < rows.length; i++) {{
    var txt = rows[i].textContent.toLowerCase();
    rows[i].style.display = txt.includes(input) ? "" : "none";
  }}
}}
function sortTable(col) {{
  var table = document.getElementById("detTable");
  var rows = Array.from(table.getElementsByTagName("tr")).slice(1);
  var asc = table.getAttribute("data-sort-col") == col &&
            table.getAttribute("data-sort-asc") == "1" ? -1 : 1;
  table.setAttribute("data-sort-col", col);
  table.setAttribute("data-sort-asc", asc == 1 ? "1" : "0");
  rows.sort(function(a, b) {{
    var av = a.cells[col].textContent.trim();
    var bv = b.cells[col].textContent.trim();
    var an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc * (an - bn);
    return asc * av.localeCompare(bv);
  }});
  rows.forEach(function(r) {{ table.tBodies[0].appendChild(r); }});
}}
</script>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)
    print(f"[plot_detections] HTML (self-contained): {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(csv_path: str = None, junc_csv: str = None,
        out_png: str = None, out_html: str = None) -> None:

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

    if csv_path is None:
        csv_path = _find_latest(log_dir, "detection_points_*.csv")
    if csv_path is None:
        print("[plot_detections] No detection_points CSV found in", log_dir)
        return

    rows = _load_detections(csv_path)
    if not rows:
        print(f"[plot_detections] CSV empty or unreadable: {csv_path}")
        return
    print(f"[plot_detections] {len(rows)} detection events from {csv_path}")

    # Find companion junction centroids file
    if junc_csv is None:
        stem = os.path.basename(csv_path)
        ts   = stem.replace("detection_points_", "").replace(".csv", "")
        candidate = os.path.join(log_dir, f"junction_centroids_{ts}.csv")
        junc_csv = candidate if os.path.isfile(candidate) else \
                   _find_latest(log_dir, "junction_centroids_*.csv")

    junctions = _load_junctions(junc_csv)
    if junctions:
        print(f"[plot_detections] {len(junctions)} junctions from {junc_csv}")
    else:
        print("[plot_detections] No junction centroids file — intersection "
              "markers will be absent")

    stem     = os.path.splitext(csv_path)[0]
    out_png  = out_png  or f"{stem}.png"
    out_osm  = f"{stem}_osm.png"
    out_html = out_html or f"{stem}.html"

    title = (
        f"Bus Detection Points  |  {len(rows)} events  |  "
        f"{len(set(r['vid'] for r in rows))} buses  |  "
        f"{len(junctions)} intersections"
    )

    # 1. Model-coordinate PNG — always produced
    try:
        plot_model_coords(rows, junctions, out_png, title)
    except Exception as err:
        import traceback
        print(f"[plot_detections] Model PNG failed: {err}\n{traceback.format_exc()}")

    # 2. OSM tile PNG — optional
    try:
        plot_osm(rows, junctions, out_osm, title)
    except ImportError as err:
        print(f"[plot_detections] OSM PNG skipped ({err}). "
              "Install with: pip install contextily pyproj")
    except Exception as err:
        print(f"[plot_detections] OSM PNG failed: {err}")

    # 3. Self-contained HTML — always produced (stdlib + matplotlib only)
    try:
        plot_html(rows, junctions, out_html, title)
    except Exception as err:
        import traceback
        print(f"[plot_detections] HTML failed: {err}\n{traceback.format_exc()}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Plot Aimsun bus detection points")
    ap.add_argument("csv_path",  nargs="?", help="detection_points CSV")
    ap.add_argument("junc_csv",  nargs="?", help="junction_centroids CSV")
    ap.add_argument("out_png",   nargs="?", help="output PNG path")
    ap.add_argument("out_html",  nargs="?", help="output HTML path")
    args = ap.parse_args()
    run(args.csv_path, args.junc_csv, args.out_png, args.out_html)
