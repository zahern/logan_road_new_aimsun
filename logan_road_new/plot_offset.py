"""
plot_offset.py — Green-wave offset dashboard
=============================================
Reads  logs/green_offsets_*.csv  and generates  offset_dashboard.html
with four tabs:

  1. Offset time-series — offset_s per bus per junction-pair over simulation time
  2. Offset summary bar — mean / median / std per junction-pair × experiment
  3. Implied speed — dist_m / offset_s compared to target corridor speed (40 km/h)
  4. Space-time heatmap — grant time per bus per junction (green-wave waterfall)

Usage:
    python plot_offset.py [--log-dir logs] [--out offset_dashboard.html]
"""

import os
import glob
import argparse
import re
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

TARGET_SPEED_MS = 40.0 / 3.6  # ≈ 11.11 m/s  (corridor design speed)
TARGET_SPEED_LABEL = "40 km/h target"


# ---------------------------------------------------------------------------
def load_offsets(log_dir: str) -> pd.DataFrame:
    pattern = os.path.join(log_dir, "green_offsets_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f)
            # Infer experiment tag from filename if column missing
            if "experiment" not in df.columns:
                m = re.search(r"green_offsets_(.+?)_\d{8}", os.path.basename(f))
                df["experiment"] = m.group(1) if m else os.path.basename(f)
            frames.append(df)
        except Exception as e:
            print(f"[WARN] Could not read {f}: {e}")
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    # Normalise column names
    out.columns = [c.strip() for c in out.columns]
    # Derived columns
    if "speed_est_ms" not in out.columns and "dist_m" in out.columns and "offset_s" in out.columns:
        out["speed_est_ms"] = out["dist_m"] / out["offset_s"].clip(lower=0.1)
    if "pair" not in out.columns:
        out["pair"] = out["from_jct"].astype(str) + "→" + out["to_jct"].astype(str)
    if "speed_kmh" not in out.columns:
        out["speed_kmh"] = out["speed_est_ms"] * 3.6
    return out


# ---------------------------------------------------------------------------
def build_dashboard(df: pd.DataFrame, out_path: str):
    experiments = sorted(df["experiment"].unique())
    pairs       = sorted(df["pair"].unique())
    colours = [
        "#2196F3","#F44336","#4CAF50","#FF9800","#9C27B0",
        "#00BCD4","#E91E63","#8BC34A","#FFC107","#3F51B5",
    ]
    exp_colour = {e: colours[i % len(colours)] for i, e in enumerate(experiments)}

    # ── Tab 1: Offset time-series ──────────────────────────────────────────
    fig_ts = go.Figure()
    for exp in experiments:
        sub = df[df["experiment"] == exp]
        for pair in pairs:
            p_sub = sub[sub["pair"] == pair].sort_values("sim_time_s")
            if p_sub.empty:
                continue
            fig_ts.add_trace(go.Scatter(
                x=p_sub["sim_time_s"],
                y=p_sub["offset_s"],
                mode="markers+lines",
                name=f"{exp} | {pair}",
                marker=dict(size=6),
                line=dict(color=exp_colour[exp], width=1, dash="dot"),
                hovertemplate=(
                    "t=%{x:.0f}s<br>offset=%{y:.1f}s<br>"
                    "bus=%{customdata[0]}<br>dist=%{customdata[1]:.0f}m<extra></extra>"
                ),
                customdata=p_sub[["veh_id", "dist_m"]].values,
                legendgroup=exp,
                showlegend=True,
            ))
    fig_ts.update_layout(
        title="Green-wave offsets over simulation time",
        xaxis_title="Simulation time (s)",
        yaxis_title="Offset (s) — time between successive junction grants",
        hovermode="closest",
        template="plotly_white",
        height=550,
    )

    # ── Tab 2: Summary bar chart ───────────────────────────────────────────
    fig_bar = go.Figure()
    grp = df.groupby(["experiment", "pair"])["offset_s"].agg(
        ["mean", "median", "std", "count"]).reset_index()
    grp["std"] = grp["std"].fillna(0.0)
    for exp in experiments:
        sg = grp[grp["experiment"] == exp]
        fig_bar.add_trace(go.Bar(
            name=f"{exp} mean",
            x=sg["pair"],
            y=sg["mean"],
            error_y=dict(type="data", array=sg["std"].tolist(), visible=True),
            marker_color=exp_colour[exp],
            opacity=0.85,
            legendgroup=exp,
            hovertemplate="pair=%{x}<br>mean=%{y:.1f}s<br>n=%{customdata}<extra></extra>",
            customdata=sg["count"].values,
        ))
    fig_bar.update_layout(
        barmode="group",
        title="Mean offset by junction pair (± 1 std)",
        xaxis_title="Junction pair (from → to)",
        yaxis_title="Mean offset (s)",
        template="plotly_white",
        height=480,
    )

    # ── Tab 3: Implied speed ───────────────────────────────────────────────
    fig_spd = go.Figure()
    for exp in experiments:
        sub = df[df["experiment"] == exp]
        for pair in pairs:
            p_sub = sub[sub["pair"] == pair]
            if p_sub.empty:
                continue
            fig_spd.add_trace(go.Box(
                y=p_sub["speed_kmh"],
                name=f"{exp} | {pair}",
                marker_color=exp_colour[exp],
                legendgroup=exp,
                boxmean=True,
                hovertemplate="speed=%{y:.1f} km/h<extra></extra>",
            ))
    # Target speed reference line
    fig_spd.add_hline(
        y=TARGET_SPEED_MS * 3.6,
        line_dash="dash",
        line_color="green",
        annotation_text=TARGET_SPEED_LABEL,
        annotation_position="right",
    )
    fig_spd.update_layout(
        title="Implied travel speed (dist ÷ offset) — should be near 40 km/h for good wave",
        yaxis_title="Speed (km/h)",
        template="plotly_white",
        height=500,
    )

    # ── Tab 4: Space-time grant waterfall ──────────────────────────────────
    # For each experiment, plot grant_to_t (x) vs to_jct position (y) coloured by bus.
    # Build corridor position mapping from dist_m if available, else ordinal.
    fig_st = go.Figure()
    # Build ordinal junction order from route order within each group
    jct_ids_ordered: list = []
    if "from_jct" in df.columns and "to_jct" in df.columns:
        all_jcts = sorted(set(df["from_jct"].tolist() + df["to_jct"].tolist()))
        jct_ids_ordered = all_jcts
    jct_y = {j: i for i, j in enumerate(jct_ids_ordered)}

    for exp in experiments:
        sub = df[df["experiment"] == exp]
        buses = sorted(sub["veh_id"].unique())
        bus_colours = [colours[i % len(colours)] for i in range(len(buses))]
        bus_col_map = dict(zip(buses, bus_colours))
        for bus in buses:
            b_sub = sub[sub["veh_id"] == bus].sort_values("grant_to_t", errors="ignore")
            if b_sub.empty:
                # Build from sim_time_s if grant_to_t not present
                b_sub = sub[sub["veh_id"] == bus].sort_values("sim_time_s")
            x_vals = (b_sub["grant_to_t"].tolist()
                      if "grant_to_t" in b_sub.columns else b_sub["sim_time_s"].tolist())
            y_vals = [jct_y.get(j, j) for j in b_sub["to_jct"]]
            fig_st.add_trace(go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="lines+markers",
                name=f"{exp} bus={bus}",
                marker=dict(size=8, color=bus_col_map[bus]),
                line=dict(color=bus_col_map[bus]),
                legendgroup=f"{exp}_{bus}",
                hovertemplate=(
                    "grant_t=%{x:.0f}s<br>jct=%{customdata[0]}<br>"
                    f"exp={exp}<br>bus={bus}<extra></extra>"
                ),
                customdata=b_sub[["to_jct"]].values,
            ))
    fig_st.update_layout(
        title="Space-time grant diagram — each line is a bus through the corridor",
        xaxis_title="Grant time (simulation seconds)",
        yaxis_title="Junction (ordinal corridor position)",
        yaxis=dict(
            tickmode="array",
            tickvals=list(jct_y.values()),
            ticktext=[str(j) for j in jct_y.keys()],
        ),
        template="plotly_white",
        height=550,
    )

    # ── Assemble into tabbed HTML ──────────────────────────────────────────
    def fig_html(fig: go.Figure) -> str:
        return fig.to_html(full_html=False, include_plotlyjs=False)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Green-Wave Offset Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  body {{ font-family: Arial, sans-serif; margin: 10px; background: #f9f9f9; }}
  h1 {{ color: #333; }}
  .tab-bar {{ display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }}
  .tab-btn {{
    padding: 8px 18px; cursor: pointer;
    background: #ddd; border: none; border-radius: 4px 4px 0 0;
    font-size: 14px;
  }}
  .tab-btn.active {{ background: #2196F3; color: white; }}
  .tab-content {{ display: none; background: white; padding: 12px; border-radius: 0 4px 4px 4px; box-shadow: 0 1px 4px rgba(0,0,0,.1); }}
  .tab-content.active {{ display: block; }}
</style>
</head>
<body>
<h1>Green-Wave Offset Dashboard</h1>
<p>Source files: <code>logs/green_offsets_*.csv</code></p>
<div class="tab-bar">
  <button class="tab-btn active" onclick="showTab('ts', this)">Offset Time-Series</button>
  <button class="tab-btn"        onclick="showTab('bar', this)">Summary Bar</button>
  <button class="tab-btn"        onclick="showTab('spd', this)">Implied Speed</button>
  <button class="tab-btn"        onclick="showTab('st', this)">Space-Time Diagram</button>
</div>
<div id="tab-ts" class="tab-content active">{fig_html(fig_ts)}</div>
<div id="tab-bar" class="tab-content">{fig_html(fig_bar)}</div>
<div id="tab-spd" class="tab-content">{fig_html(fig_spd)}</div>
<div id="tab-st"  class="tab-content">{fig_html(fig_st)}</div>
<script>
function showTab(name, btn) {{
  document.querySelectorAll('.tab-content').forEach(d => d.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)
    print(f"Dashboard written → {out_path}  ({len(df)} offset records, "
          f"{df['veh_id'].nunique()} buses, {len(pairs)} junction pairs)")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Green-wave offset dashboard")
    ap.add_argument("--log-dir", default="logs",  help="Folder containing green_offsets_*.csv")
    ap.add_argument("--out",     default="offset_dashboard.html")
    args = ap.parse_args()

    df = load_offsets(args.log_dir)
    if df.empty:
        print(
            "[INFO] No green_offsets_*.csv files found.\n"
            "       Run a HARMONY_COORD simulation first to generate offset data.\n"
            f"       Expected pattern: {os.path.join(args.log_dir, 'green_offsets_*.csv')}"
        )
        return

    build_dashboard(df, args.out)


if __name__ == "__main__":
    main()
