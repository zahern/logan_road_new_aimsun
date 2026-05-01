"""
plot_compare_runs.py
====================
Comparison dashboard for multiple Logan Road TSP simulation runs.

Reads detection CSVs and (optionally) batch_results.csv / simulation_results.csv
to produce a side-by-side comparison of key metrics:

  • Green arrival rate per junction and per run (bar chart)
  • Mean green rate across corridor (summary table)
  • Total passenger delay        (from simulation_results.csv)
  • Total bus delay              (from simulation_results.csv)
  • Total main-street delay      (from simulation_results.csv)
  • Total side-street delay      (from simulation_results.csv)
  • Corridor occupancy / density (from simulation_results.csv)
  • Number of TSP-prioritised buses

Usage (standalone)
------------------
  python plot_compare_runs.py \\
      --runs "Baseline=logs/detection_points_A.csv" \\
             "Coordinated=logs/detection_points_B.csv" \\
      --results logs/batch_results.csv \\
      --out     comparison.png

Or import and call directly:
  from plot_compare_runs import compare
  compare([
      ("Baseline",    "logs/detection_points_A.csv"),
      ("Coordinated", "logs/detection_points_B.csv"),
  ], batch_csv="logs/batch_results.csv", out_path="comparison.png")
"""

import os
import sys
import csv
import glob
import argparse
import math

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# Add Aimsun packages path before importing matplotlib
_AIMSUN_PACKAGES = r"C:\AimsunPackages"
if os.path.isdir(_AIMSUN_PACKAGES) and _AIMSUN_PACKAGES not in sys.path:
    sys.path.insert(0, _AIMSUN_PACKAGES)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches

# Reuse detection-loading and TSP-bus logic from plot_green_wave
from plot_green_wave import (
    _load_detections,
    _junctions_from_detections,
    _find_tsp_vehicles,
    _phase_at_stopline,
    _geographic_junction_order,
    INTERSECTIONS_CONFIG,
    ALL_CORRIDOR_JCTS,
)

# ── Metric columns to extract from batch_results.csv / simulation_results.csv ─
# Map: display_name → list of candidate column names (first match wins)
METRIC_COLUMNS = {
    "Total pax delay (veh·h)":  ["stats_total_pax_delay_vh",
                                   "stats_TotalDelay",  "json_total_delay"],
    "Bus delay (veh·h)":        ["stats_bus_delay_vh",
                                   "stats_BusDelay",    "json_bus_delay"],
    "Main-street delay (veh·h)":["stats_main_delay_vh",
                                   "stats_MainDelay",   "json_main_delay"],
    "Side-street delay (veh·h)":["stats_side_delay_vh",
                                   "stats_SideDelay",   "json_side_delay"],
    "Corridor density (veh/km)":["stats_corridor_density",
                                   "stats_Density",     "json_density"],
    "TSP grants":               ["stats_tsp_grants",
                                   "json_tsp_grants"],
    "Coord pre-arms":           ["stats_coord_prearms",
                                   "json_coord_prearms"],
}

# Colour palette for runs
_PALETTE = [
    "#42a5f5", "#ef5350", "#66bb6a", "#ffa726",
    "#ab47bc", "#26c6da", "#d4e157", "#ff7043",
]


# =============================================================================
# Helpers
# =============================================================================

def _get_cmap(name: str, n: int):
    try:
        return matplotlib.colormaps[name].resampled(max(n, 2))
    except (AttributeError, KeyError):
        pass
    try:
        return plt.cm.get_cmap(name, max(n, 2))
    except Exception:
        return plt.cm.get_cmap("tab10")


def _load_batch_csv(path: str) -> list:
    """Load batch_results.csv → list of row dicts."""
    if not path or not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f)]


def _find_metric(row: dict, candidates: list):
    """Return the first matching metric value from a batch-results row."""
    for col in candidates:
        val = row.get(col)
        if val is not None and val != "":
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def _compute_green_stats(rows: list) -> tuple:
    """
    Given detection rows for ONE run, return:
      (tsp_vids, per_junction_green_pct, mean_green_pct, ordered_jcts)
    """
    tsp_vids = _find_tsp_vehicles(rows)
    tsp_rows = [r for r in rows if r["vid"] in tsp_vids]

    # geographic ordering
    junctions = _junctions_from_detections(rows)
    jcts_in   = sorted(set(r["jct"] for r in tsp_rows))
    ordered   = _geographic_junction_order(junctions, jcts_in)

    stats: dict = {}
    for r in tsp_rows:
        jid = r["jct"]
        if jid not in stats:
            stats[jid] = {"green": 0, "orange": 0, "red": 0}
        p = _phase_at_stopline(r)
        key = "green" if p == "green" else "orange" if p == "orange" else "red"
        stats[jid][key] += 1

    green_pct: dict = {}
    for jid in jcts_in:
        tot = sum(stats.get(jid, {}).values())
        g   = stats.get(jid, {}).get("green",  0)
        o   = stats.get(jid, {}).get("orange", 0)
        green_pct[jid] = 100 * (g + o) / tot if tot else 0

    mean_g = sum(green_pct.values()) / len(green_pct) if green_pct else 0.0
    return tsp_vids, green_pct, mean_g, ordered


# =============================================================================
# Main comparison function
# =============================================================================

def compare(run_specs: list,
            batch_csv: str = None,
            out_path: str = None) -> None:
    """
    Build a comparison dashboard.

    Parameters
    ----------
    run_specs : list of (label, detection_csv_path) tuples.
                  E.g. [("Baseline", "logs/det_A.csv"),
                        ("Coord",    "logs/det_B.csv")]
    batch_csv : path to batch_results.csv (optional; enables delay/density panels)
    out_path  : output PNG path (default: comparison_dashboard.png in script dir)
    """
    if not run_specs:
        print("[compare] No runs specified — nothing to plot.")
        return

    if out_path is None:
        out_path = os.path.join(_SCRIPT_DIR, "logs", "comparison_dashboard.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # ── Load detection data ───────────────────────────────────────────────────
    run_data = []
    for label, det_csv in run_specs:
        rows = _load_detections(det_csv)
        if not rows:
            print(f"[compare] WARNING: no rows loaded from {det_csv}")
        tsp_vids, green_pct, mean_g, ordered = _compute_green_stats(rows)
        run_data.append({
            "label":    label,
            "rows":     rows,
            "tsp_vids": tsp_vids,
            "green_pct": green_pct,
            "mean_g":   mean_g,
            "ordered":  ordered,
            "n_tsp":    len(tsp_vids),
        })

    # ── Load batch metrics (optional) ────────────────────────────────────────
    batch_rows = _load_batch_csv(batch_csv)
    # Match batch rows to run labels by run_experiment column
    batch_by_label: dict = {}
    for brow in batch_rows:
        lbl = brow.get("run_experiment") or brow.get("run_strategy") or ""
        batch_by_label.setdefault(lbl, []).append(brow)

    def _best_batch(label: str) -> dict:
        """Find the batch row most likely belonging to this run label."""
        rows = batch_by_label.get(label, [])
        if rows:
            return rows[0]
        # Try partial match
        for k, v in batch_by_label.items():
            if label.lower() in k.lower() or k.lower() in label.lower():
                return v[0]
        return {}

    # ── All junctions across runs ─────────────────────────────────────────────
    all_jcts = sorted({j for d in run_data for j in d["green_pct"].keys()})
    junctions_combined = _junctions_from_detections(
        [r for d in run_data for r in d["rows"]])
    ordered_all = _geographic_junction_order(junctions_combined, all_jcts)

    # ── Figure layout ─────────────────────────────────────────────────────────
    n_metrics = sum(1 for d in run_data
                    if any(_find_metric(_best_batch(d["label"]), c) is not None
                           for c in METRIC_COLUMNS.values()))
    has_metrics = n_metrics > 0

    fig_h = 11 if not has_metrics else 15
    fig = plt.figure(figsize=(18, fig_h))
    fig.patch.set_facecolor("#12122a")

    if has_metrics:
        gs = gridspec.GridSpec(3, 2,
                               height_ratios=[2.2, 1.0, 1.2],
                               hspace=0.45, wspace=0.30,
                               left=0.08, right=0.97, top=0.92, bottom=0.06)
        ax_jct    = fig.add_subplot(gs[0, :])   # green rate per junction
        ax_summ   = fig.add_subplot(gs[1, 0])   # summary table
        ax_mean   = fig.add_subplot(gs[1, 1])   # mean green rate bar
        ax_delay  = fig.add_subplot(gs[2, 0])   # delay metrics
        ax_other  = fig.add_subplot(gs[2, 1])   # density / TSP counts
    else:
        gs = gridspec.GridSpec(2, 2,
                               height_ratios=[2.5, 1.0],
                               hspace=0.40, wspace=0.30,
                               left=0.08, right=0.97, top=0.92, bottom=0.06)
        ax_jct   = fig.add_subplot(gs[0, :])
        ax_summ  = fig.add_subplot(gs[1, 0])
        ax_mean  = fig.add_subplot(gs[1, 1])
        ax_delay = ax_other = None

    # ── Panel 1: green rate per junction, grouped bars ────────────────────────
    ax_jct.set_facecolor("#1a1a30")
    n_runs = len(run_data)
    bar_w  = 0.75 / max(n_runs, 1)
    colors = [_PALETTE[i % len(_PALETTE)] for i in range(n_runs)]
    xs = list(range(len(ordered_all)))

    for i, d in enumerate(run_data):
        vals = [d["green_pct"].get(j, 0) for j in ordered_all]
        off  = (i - n_runs / 2 + 0.5) * bar_w
        bars = ax_jct.bar([x + off for x in xs], vals, bar_w,
                           color=colors[i], alpha=0.82, label=d["label"])
        # value labels
        for bar in bars:
            h = bar.get_height()
            if h >= 5:
                ax_jct.text(bar.get_x() + bar.get_width() / 2, h + 1,
                            f"{h:.0f}", ha="center", fontsize=6.5,
                            color="#ccccee")

    ax_jct.set_xticks(xs)
    ax_jct.set_xticklabels([f"jct {j}" for j in ordered_all],
                            rotation=40, ha="right", fontsize=8, color="#9090cc")
    ax_jct.set_ylim(0, 115)
    ax_jct.axhline(50, color="#555577", lw=0.8, ls="--")
    ax_jct.axhline(80, color="#337733", lw=0.7, ls=":", alpha=0.7)
    ax_jct.set_ylabel("Green / coord arrival rate (%)", fontsize=9, color="#ccccee")
    ax_jct.set_title("Green-pass rate by corridor junction", fontsize=11,
                     color="#e8e8ff", pad=8)
    ax_jct.legend(fontsize=9, facecolor="#1a1a30",
                  labelcolor="#ccccee", edgecolor="#333355")
    ax_jct.tick_params(colors="#9090cc")
    for sp in ax_jct.spines.values():
        sp.set_color("#2a2a50")
    ax_jct.grid(axis="y", color="#2a2a44", lw=0.5, alpha=0.4)

    # ── Panel 2: summary table ─────────────────────────────────────────────────
    ax_summ.set_facecolor("#12122a")
    ax_summ.axis("off")

    header = ["Run", "Avg green%", "#TSP buses", "# events"]
    rows_t = []
    for d in run_data:
        n_events = sum(1 for r in d["rows"] if r["vid"] in d["tsp_vids"])
        rows_t.append([d["label"],
                       f"{d['mean_g']:.1f}%",
                       str(d["n_tsp"]),
                       str(n_events)])

    tbl = ax_summ.table(cellText=rows_t, colLabels=header,
                         loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1.2, 1.8)
    for (row_i, col_i), cell in tbl.get_celld().items():
        cell.set_facecolor("#1a1a38" if row_i % 2 == 0 else "#12122a")
        cell.set_text_props(color="#ccccee")
        cell.set_edgecolor("#333355")
    ax_summ.set_title("Summary", fontsize=10, color="#e8e8ff")

    # ── Panel 3: mean green rate horizontal bar ────────────────────────────────
    ax_mean.set_facecolor("#1a1a30")
    ys_m = list(range(n_runs))
    mean_vals = [d["mean_g"] for d in run_data]
    hbars = ax_mean.barh(ys_m, mean_vals, 0.55,
                          color=colors[:n_runs], alpha=0.82)
    ax_mean.set_yticks(ys_m)
    ax_mean.set_yticklabels([d["label"] for d in run_data],
                             fontsize=8.5, color="#9090cc")
    ax_mean.set_xlim(0, 110)
    ax_mean.axvline(50, color="#555577", lw=0.8, ls="--")
    ax_mean.set_xlabel("Mean green arrival rate (%)", fontsize=9, color="#ccccee")
    ax_mean.set_title("Overall corridor green rate", fontsize=10,
                      color="#e8e8ff", pad=6)
    for bar in hbars:
        ax_mean.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                     f"{bar.get_width():.1f}%", va="center",
                     fontsize=8.5, color="#ccccee")
    ax_mean.tick_params(colors="#9090cc")
    for sp in ax_mean.spines.values():
        sp.set_color("#2a2a50")

    # ── Panel 4 & 5: delay / density metrics (if batch_csv available) ─────────
    if has_metrics and ax_delay is not None:
        delay_metrics = [
            "Total pax delay (veh·h)",
            "Bus delay (veh·h)",
            "Main-street delay (veh·h)",
            "Side-street delay (veh·h)",
        ]
        other_metrics = [
            "Corridor density (veh/km)",
            "TSP grants",
            "Coord pre-arms",
        ]

        def _draw_metric_panel(ax, metric_names):
            ax.set_facecolor("#1a1a30")
            x_base  = list(range(len(metric_names)))
            bar_w_m = 0.7 / max(n_runs, 1)
            found_any = False
            for i, d in enumerate(run_data):
                brow = _best_batch(d["label"])
                vals = []
                for mname in metric_names:
                    v = _find_metric(brow, METRIC_COLUMNS.get(mname, []))
                    vals.append(v if v is not None else 0.0)
                if any(v != 0 for v in vals):
                    found_any = True
                off = (i - n_runs / 2 + 0.5) * bar_w_m
                ax.bar([x + off for x in x_base], vals, bar_w_m,
                       color=colors[i], alpha=0.82, label=d["label"])
            if not found_any:
                ax.text(0.5, 0.5, "No batch metrics available\n(run with batch_runner.py)",
                        ha="center", va="center", transform=ax.transAxes,
                        fontsize=9, color="#888899")
            ax.set_xticks(x_base)
            ax.set_xticklabels(metric_names, rotation=30, ha="right",
                               fontsize=7.5, color="#9090cc")
            ax.legend(fontsize=7, facecolor="#1a1a30",
                      labelcolor="#ccccee", edgecolor="#333355")
            ax.tick_params(colors="#9090cc")
            for sp in ax.spines.values():
                sp.set_color("#2a2a50")
            ax.grid(axis="y", color="#2a2a44", lw=0.5, alpha=0.4)

        _draw_metric_panel(ax_delay, delay_metrics)
        ax_delay.set_title("Delay metrics (from batch results)", fontsize=9,
                           color="#e8e8ff", pad=5)

        _draw_metric_panel(ax_other, other_metrics)
        ax_other.set_title("Operational metrics", fontsize=9,
                           color="#e8e8ff", pad=5)

    # ── Title ─────────────────────────────────────────────────────────────────
    run_labels = " vs ".join(d["label"] for d in run_data)
    fig.suptitle(f"TSP Strategy Comparison: {run_labels}",
                 fontsize=13, color="#e8e8ff", y=0.97)

    plt.savefig(out_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[compare] Saved: {out_path}")


# =============================================================================
# Auto-discovery helper for the latest N detection CSVs
# =============================================================================

def compare_latest_runs(n: int = 2,
                         log_dir: str = None,
                         batch_csv: str = None,
                         out_path: str = None) -> None:
    """
    Convenience wrapper: compare the n most-recent detection_points CSVs
    found in log_dir (default: <script_dir>/logs).
    """
    if log_dir is None:
        log_dir = os.path.join(_SCRIPT_DIR, "logs")

    csvs = sorted(glob.glob(os.path.join(log_dir, "detection_points_*.csv")))
    if not csvs:
        print(f"[compare_latest] No detection CSVs found in {log_dir}")
        return

    selected = csvs[-n:]   # take the n most recent
    specs    = [(os.path.basename(p).replace("detection_points_", "")
                                    .replace(".csv", ""),
                 p)
                for p in selected]

    if batch_csv is None:
        candidate = os.path.join(log_dir, "batch_results.csv")
        if os.path.isfile(candidate):
            batch_csv = candidate

    if out_path is None:
        out_path = os.path.join(log_dir, "comparison_dashboard.png")

    compare(specs, batch_csv=batch_csv, out_path=out_path)


# =============================================================================
# CLI entry point
# =============================================================================

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Compare green-wave performance across simulation runs")
    ap.add_argument("--runs", nargs="+", metavar="LABEL=CSV",
                    help="One or more label=csv_path pairs, e.g. "
                         "'Baseline=logs/det_A.csv'")
    ap.add_argument("--latest", type=int, default=0,
                    help="Compare the N most recent detection CSVs "
                         "(alternative to --runs)")
    ap.add_argument("--results", default=None,
                    help="Path to batch_results.csv for delay metrics")
    ap.add_argument("--out", default=None,
                    help="Output PNG path")
    ap.add_argument("--log_dir", default=None,
                    help="Log directory (default: <script_dir>/logs)")
    args = ap.parse_args()

    if args.latest:
        compare_latest_runs(
            n       = args.latest,
            log_dir = args.log_dir,
            batch_csv = args.results,
            out_path  = args.out,
        )
    elif args.runs:
        specs = []
        for item in args.runs:
            if "=" in item:
                lbl, path = item.split("=", 1)
                specs.append((lbl.strip(), path.strip()))
            else:
                specs.append((os.path.basename(item), item))
        compare(specs, batch_csv=args.results, out_path=args.out)
    else:
        ap.print_help()
