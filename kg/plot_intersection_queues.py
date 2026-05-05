"""
plot_intersection_queues.py
===========================
Per-intersection queue dashboard for Logan Rd TSP simulations.

Two data sources:
  1. logs/queue_snapshot_*.csv  — per-second queue_main/queue_side time-series
  2. results/**/section_stats.csv — time-averaged AvgQueue_veh per section

Generates: intersection_queues_dashboard.html

Tabs:
  1. Queue Bar Chart    – average main+side queue per intersection, all experiments
  2. Queue Time-Series  – queue_main / queue_side vs sim_time_s per intersection
  3. Section Queue Map  – AvgQueue_veh from section_stats, grouped by intersection
  4. Delay Breakdown    – delay_total_s / delay_bus_s / delay_car_s per intersection
  5. TSP State Timeline – tsp_state and corridor_bus_count per intersection

Usage:
    python plot_intersection_queues.py
    python plot_intersection_queues.py --log-dir logs --results-dir results --out intersection_queues_dashboard.html
"""

import os
import sys
import glob
import argparse
from pathlib import Path

# Inject the shared project venv so pandas/plotly/etc. are importable when this
# script is called from inside Aimsun (which uses a minimal Python environment).
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

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOG_DIR     = os.path.join(os.path.dirname(__file__), "logs")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
OUT_HTML    = os.path.join(os.path.dirname(__file__), "intersection_queues_dashboard.html")

JUNCTION_LABELS = {
    39606:   "39606 (A1)",
    39590:   "39590 (A2)",
    36393:   "36393 (A3)",
    36385:   "36385 (A4)",
    39593:   "39593 (A5)",
    39576:   "39576 (B1)",
    39578:   "39578 (B2)",
    39587:   "39587 (B3)",
    1043762: "1043762 (B4)",
    39569:   "39569 (B5)",
    39572:   "39572 (B6)",
    38339:   "38339 (B7)",
}

CORRIDOR_A = [39606, 39590, 36393, 36385, 39593]
CORRIDOR_B = [39576, 39578, 39587, 1043762, 39569, 39572, 38339]
CORRIDOR_ORDER = CORRIDOR_A + CORRIDOR_B

STRATEGY_COLORS = {
    "NORMAL":         "#4C72B0",
    "HARMONY_COORD":  "#DD8452",
    "DYNAOPAC_COORD": "#55A868",
    "DYNAOPAC_COORD_SHOCKWAVE": "#C44E52",
}
DEFAULT_PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52",
    "#8172B2", "#937860", "#DA8BC3", "#8C8C8C",
]

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_queue_snapshots(log_dir: str) -> dict:
    """Return dict[experiment_label -> DataFrame] from queue_snapshot_*.csv."""
    dfs = {}
    for f in sorted(glob.glob(os.path.join(log_dir, "queue_snapshot_*.csv"))):
        exp = Path(f).stem.replace("queue_snapshot_", "")
        # Strip trailing timestamp so we get a clean experiment name
        parts = exp.rsplit("_", 2)
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            exp = parts[0]
        try:
            df = pd.read_csv(f)
            df["experiment"] = exp
            if exp in dfs:
                dfs[exp] = pd.concat([dfs[exp], df], ignore_index=True)
            else:
                dfs[exp] = df
        except Exception as e:
            print(f"Warning: could not load {f}: {e}")
    return dfs


def load_section_stats(results_dir: str) -> pd.DataFrame:
    """Return combined DataFrame from all results/**/section_stats.csv."""
    frames = []
    for f in sorted(glob.glob(os.path.join(results_dir, "**", "section_stats.csv"), recursive=True)):
        try:
            df = pd.read_csv(f, on_bad_lines="skip")
            # Derive experiment label from parent folder name
            df["experiment"] = Path(f).parent.name
            frames.append(df)
        except Exception as e:
            print(f"Warning: could not load {f}: {e}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Tab 1: Average queue bar chart (main vs side per intersection)
# ---------------------------------------------------------------------------

def make_avg_queue_bar(snap_dfs: dict) -> go.Figure:
    """Grouped bar chart: mean queue_main and queue_side per intersection."""
    jct_order = [j for j in CORRIDOR_ORDER if j in JUNCTION_LABELS]
    experiments = list(snap_dfs.keys())

    # Assign colours
    color_map = {e: STRATEGY_COLORS.get(e, DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)])
                 for i, e in enumerate(experiments)}

    fig = go.Figure()

    for exp in experiments:
        df = snap_dfs[exp]
        color = color_map[exp]
        means_main = []
        means_side = []
        labels      = []
        for jct in jct_order:
            sub = df[df["junction_id"] == jct]
            means_main.append(sub["queue_main"].mean() if len(sub) else 0.0)
            means_side.append(sub["queue_side"].mean() if len(sub) else 0.0)
            labels.append(JUNCTION_LABELS.get(jct, str(jct)))

        fig.add_trace(go.Bar(
            name=f"{exp} – main",
            x=labels, y=means_main,
            marker_color=color, opacity=0.9,
            legendgroup=exp,
        ))
        fig.add_trace(go.Bar(
            name=f"{exp} – side",
            x=labels, y=means_side,
            marker_color=color, opacity=0.45,
            marker_pattern_shape="/",
            legendgroup=exp,
        ))

    fig.update_layout(
        title="Average Queue Length per Intersection (main=solid, side=hatched)",
        xaxis_title="Intersection",
        yaxis_title="Queue (veh)",
        barmode="group",
        legend=dict(groupclick="toggleitem"),
        height=520,
    )
    return fig


# ---------------------------------------------------------------------------
# Tab 2: Queue time-series per intersection
# ---------------------------------------------------------------------------

def make_queue_timeseries(snap_dfs: dict) -> go.Figure:
    """Facet grid: queue_main and queue_side vs sim_time_s for each intersection."""
    jct_order = [j for j in CORRIDOR_ORDER if j in JUNCTION_LABELS]
    n_jct = len(jct_order)
    experiments = list(snap_dfs.keys())
    color_map = {e: STRATEGY_COLORS.get(e, DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)])
                 for i, e in enumerate(experiments)}

    fig = make_subplots(
        rows=n_jct, cols=1,
        subplot_titles=[JUNCTION_LABELS.get(j, str(j)) for j in jct_order],
        shared_xaxes=True,
        vertical_spacing=0.02,
    )

    for row_idx, jct in enumerate(jct_order, start=1):
        for exp in experiments:
            df = snap_dfs[exp]
            sub = df[df["junction_id"] == jct].sort_values("sim_time_s")
            if len(sub) == 0:
                continue
            color = color_map[exp]
            show_leg = (row_idx == 1)
            fig.add_trace(go.Scatter(
                x=sub["sim_time_s"], y=sub["queue_main"],
                name=f"{exp} main", legendgroup=f"{exp}_main",
                mode="lines", line=dict(color=color, width=1.5),
                showlegend=show_leg,
            ), row=row_idx, col=1)
            fig.add_trace(go.Scatter(
                x=sub["sim_time_s"], y=sub["queue_side"],
                name=f"{exp} side", legendgroup=f"{exp}_side",
                mode="lines", line=dict(color=color, width=1.5, dash="dot"),
                showlegend=show_leg,
            ), row=row_idx, col=1)

    fig.update_layout(
        title="Queue Length Time-Series per Intersection (solid=main, dashed=side)",
        height=260 * n_jct,
        showlegend=True,
    )
    fig.update_xaxes(title_text="Simulation time (s)", row=n_jct, col=1)
    for row_idx in range(1, n_jct + 1):
        fig.update_yaxes(title_text="Queue (veh)", row=row_idx, col=1)
    return fig


# ---------------------------------------------------------------------------
# Tab 3: Section-level average queue from section_stats.csv
# ---------------------------------------------------------------------------

def make_section_queue_bar(sec_df: pd.DataFrame) -> go.Figure:
    """Bar chart of AvgQueue_veh per section, coloured by IsMain, grouped by experiment."""
    if sec_df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No section_stats.csv data found.", showarrow=False,
                           font=dict(size=16), xref="paper", yref="paper", x=0.5, y=0.5)
        return fig

    jct_order = [j for j in CORRIDOR_ORDER if j in JUNCTION_LABELS]
    experiments = sorted(sec_df["experiment"].unique())
    color_map = {e: STRATEGY_COLORS.get(e, DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)])
                 for i, e in enumerate(experiments)}

    fig = make_subplots(
        rows=len(experiments), cols=1,
        subplot_titles=experiments,
        shared_xaxes=False,
        vertical_spacing=0.08,
    )

    for row_idx, exp in enumerate(experiments, start=1):
        sub = sec_df[sec_df["experiment"] == exp].copy()
        # Aggregate across replications: mean AvgQueue_veh per section
        grp = (sub.groupby(["IntersectionID", "SectionID", "IsMain"])
               ["AvgQueue_veh"].mean().reset_index())

        # Sort by corridor order
        grp["_order"] = grp["IntersectionID"].map(
            {j: i for i, j in enumerate(jct_order)}).fillna(999)
        grp = grp.sort_values(["_order", "IsMain", "SectionID"])

        x_labels = [
            f"{JUNCTION_LABELS.get(r.IntersectionID, str(r.IntersectionID))}\n§{r.SectionID}"
            f"{'(M)' if r.IsMain else '(S)'}"
            for _, r in grp.iterrows()
        ]
        color = color_map[exp]
        colors = [color if r.IsMain else color.replace("#", "#88")
                  for _, r in grp.iterrows()]
        # Fallback simple shading for non-plotly-hex colours
        bar_colors_main = [color if r.IsMain else "rgba(150,150,150,0.6)"
                           for _, r in grp.iterrows()]

        fig.add_trace(go.Bar(
            x=x_labels, y=grp["AvgQueue_veh"].tolist(),
            marker_color=bar_colors_main,
            name=exp, legendgroup=exp, showlegend=(row_idx == 1),
        ), row=row_idx, col=1)

    fig.update_layout(
        title="Average Queue per Section from section_stats (M=main, S=side)",
        height=420 * len(experiments),
        showlegend=True,
    )
    for row_idx in range(1, len(experiments) + 1):
        fig.update_yaxes(title_text="Avg Queue (veh)", row=row_idx, col=1)
    return fig


# ---------------------------------------------------------------------------
# Tab 4: Delay breakdown (total / bus / car) per intersection
# ---------------------------------------------------------------------------

def make_delay_bar(snap_dfs: dict) -> go.Figure:
    """Grouped bar: mean delay_total_s, delay_bus_s, delay_car_s per intersection."""
    jct_order   = [j for j in CORRIDOR_ORDER if j in JUNCTION_LABELS]
    experiments = list(snap_dfs.keys())
    color_map   = {e: STRATEGY_COLORS.get(e, DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)])
                   for i, e in enumerate(experiments)}

    fig = go.Figure()
    for exp in experiments:
        df = snap_dfs[exp]
        labels_x, totals, buses, cars = [], [], [], []
        for jct in jct_order:
            sub = df[df["junction_id"] == jct]
            labels_x.append(JUNCTION_LABELS.get(jct, str(jct)))
            totals.append(sub["delay_total_s"].mean() if "delay_total_s" in sub.columns and len(sub) else 0.0)
            buses.append(sub["delay_bus_s"].mean()   if "delay_bus_s"   in sub.columns and len(sub) else 0.0)
            cars.append(sub["delay_car_s"].mean()    if "delay_car_s"   in sub.columns and len(sub) else 0.0)

        color = color_map[exp]
        fig.add_trace(go.Bar(name=f"{exp} – total", x=labels_x, y=totals,
                             marker_color=color, opacity=0.9, legendgroup=exp))
        fig.add_trace(go.Bar(name=f"{exp} – bus",   x=labels_x, y=buses,
                             marker_color=color, opacity=0.5, marker_pattern_shape="x",
                             legendgroup=exp))
        fig.add_trace(go.Bar(name=f"{exp} – car",   x=labels_x, y=cars,
                             marker_color=color, opacity=0.3, marker_pattern_shape=".",
                             legendgroup=exp))

    fig.update_layout(
        title="Mean Delay per Intersection (total / bus / car)",
        xaxis_title="Intersection",
        yaxis_title="Delay (s)",
        barmode="group",
        height=520,
    )
    return fig


# ---------------------------------------------------------------------------
# Tab 5: TSP state + corridor bus count per intersection (heatmap)
# ---------------------------------------------------------------------------

def make_tsp_state_heatmap(snap_dfs: dict) -> go.Figure:
    """Heatmap of tsp_state over time, faceted by experiment and intersection."""
    if not snap_dfs:
        fig = go.Figure()
        fig.add_annotation(text="No snapshot data.", showarrow=False,
                           font=dict(size=16), xref="paper", yref="paper", x=0.5, y=0.5)
        return fig

    jct_order   = [j for j in CORRIDOR_ORDER if j in JUNCTION_LABELS]
    experiments = list(snap_dfs.keys())
    n_exp       = len(experiments)
    n_jct       = len(jct_order)

    fig = make_subplots(
        rows=n_exp, cols=n_jct,
        subplot_titles=[
            f"{exp}\n{JUNCTION_LABELS.get(j,'')}"
            for exp in experiments
            for j   in jct_order
        ],
        shared_xaxes="all",
        shared_yaxes=False,
        vertical_spacing=0.06,
        horizontal_spacing=0.01,
    )

    for row_idx, exp in enumerate(experiments, start=1):
        df = snap_dfs[exp]
        for col_idx, jct in enumerate(jct_order, start=1):
            sub = df[df["junction_id"] == jct].sort_values("sim_time_s")
            if len(sub) == 0:
                continue
            # Encode tsp_state as numeric (0=IDLE/NORMAL, 1=GE, 2=INS, 3=coord)
            state_map = {"NORMAL": 0, "IDLE": 0, "GE": 1, "INS": 2,
                         "COORD": 3, "HARMONY": 3, "PREARM": 2}
            if "tsp_state" in sub.columns:
                z_vals = sub["tsp_state"].map(
                    lambda s: state_map.get(str(s).upper(), 0) if pd.notna(s) else 0
                ).tolist()
            else:
                z_vals = [0] * len(sub)
            fig.add_trace(go.Heatmap(
                x=sub["sim_time_s"].tolist(),
                y=[JUNCTION_LABELS.get(jct, str(jct))],
                z=[z_vals],
                colorscale=[[0, "lightgrey"], [0.33, "#4C72B0"],
                            [0.66, "#DD8452"], [1.0, "#55A868"]],
                zmin=0, zmax=3,
                showscale=(row_idx == 1 and col_idx == 1),
                colorbar=dict(
                    tickvals=[0, 1, 2, 3],
                    ticktext=["IDLE", "GE", "INS", "COORD"],
                    len=0.3,
                ),
            ), row=row_idx, col=col_idx)

    fig.update_layout(
        title="TSP State over Time (0=IDLE, 1=GE, 2=INS, 3=COORD)",
        height=max(300, 200 * n_exp),
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Build and write dashboard
# ---------------------------------------------------------------------------

def build_dashboard(log_dir: str, results_dir: str, out_html: str) -> None:
    print(f"Loading queue snapshots from: {log_dir}")
    snap_dfs = load_queue_snapshots(log_dir)

    print(f"Loading section stats from:   {results_dir}")
    sec_df = load_section_stats(results_dir)

    if not snap_dfs:
        print("WARNING: No queue_snapshot_*.csv files found — only section stats tab will have data.")

    experiments = list(snap_dfs.keys()) or ["(none)"]
    print(f"Experiments found: {experiments}")

    # Build all tabs
    print("Building Tab 1: average queue bar chart …")
    fig_bar = make_avg_queue_bar(snap_dfs) if snap_dfs else _empty_fig("No snapshot data")

    print("Building Tab 2: queue time-series …")
    fig_ts = make_queue_timeseries(snap_dfs) if snap_dfs else _empty_fig("No snapshot data")

    print("Building Tab 3: section queue bar …")
    fig_sec = make_section_queue_bar(sec_df)

    print("Building Tab 4: delay breakdown …")
    fig_delay = make_delay_bar(snap_dfs) if snap_dfs else _empty_fig("No snapshot data")

    print("Building Tab 5: TSP state heatmap …")
    fig_tsp = make_tsp_state_heatmap(snap_dfs) if snap_dfs else _empty_fig("No snapshot data")

    # Assemble into tabbed HTML
    tabs = [
        ("Queue Bar Chart",    fig_bar),
        ("Queue Time-Series",  fig_ts),
        ("Section Queue Map",  fig_sec),
        ("Delay Breakdown",    fig_delay),
        ("TSP State Timeline", fig_tsp),
    ]
    html = _build_tabbed_html(tabs, title="Logan Rd – Intersection Queue Dashboard")

    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"\nDashboard written -> {out_html}")


def _empty_fig(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False,
                       font=dict(size=16), xref="paper", yref="paper", x=0.5, y=0.5)
    return fig


def _build_tabbed_html(tabs: list, title: str) -> str:
    """Wrap multiple plotly figures in a single HTML with JS-driven tabs."""
    import plotly.io as pio

    tab_buttons = []
    tab_divs    = []
    first = True
    for i, (label, fig) in enumerate(tabs):
        tid    = f"tab{i}"
        active = "active" if first else ""
        tab_buttons.append(
            f'<button class="tablink {active}" onclick="openTab(event,\'{tid}\')">{label}</button>'
        )
        div_style = "display:block" if first else "display:none"
        inner     = pio.to_html(fig, full_html=False, include_plotlyjs=False)
        tab_divs.append(
            f'<div id="{tid}" class="tabcontent" style="{div_style}">{inner}</div>'
        )
        first = False

    buttons_html = "\n    ".join(tab_buttons)
    divs_html    = "\n  ".join(tab_divs)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f7f7f7; }}
    h1   {{ background: #2c3e50; color: #fff; margin: 0; padding: 12px 20px; font-size: 1.2em; }}
    .tabbar {{ background: #34495e; overflow: hidden; }}
    .tablink {{ background: #34495e; color: #ccc; border: none; cursor: pointer;
               padding: 12px 18px; font-size: 0.95em; }}
    .tablink:hover, .tablink.active {{ background: #2c3e50; color: #fff; }}
    .tabcontent {{ padding: 12px; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <div class="tabbar">
    {buttons_html}
  </div>
  {divs_html}
  <script>
    function openTab(evt, tabId) {{
      var contents = document.getElementsByClassName("tabcontent");
      for (var i = 0; i < contents.length; i++) contents[i].style.display = "none";
      var links = document.getElementsByClassName("tablink");
      for (var i = 0; i < links.length; i++) links[i].classList.remove("active");
      document.getElementById(tabId).style.display = "block";
      evt.currentTarget.classList.add("active");
    }}
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Logan Rd intersection queue dashboard")
    parser.add_argument("--log-dir",     default=LOG_DIR,     help="Directory with queue_snapshot_*.csv")
    parser.add_argument("--results-dir", default=RESULTS_DIR, help="Directory tree with section_stats.csv")
    parser.add_argument("--out",         default=OUT_HTML,    help="Output HTML path")
    args = parser.parse_args()

    build_dashboard(args.log_dir, args.results_dir, args.out)
