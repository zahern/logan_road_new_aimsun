"""
plot_shockwave.py
=================
Shockwave / queue profile dashboard for Logan Rd TSP simulations.

Generates an HTML dashboard with:
  - Animated bar charts of main/side section queues per intersection
  - Shockwave trajectory profiles (LWR triangular model)
  - Timeline of bus detections and TSP events per intersection
  - Dropdowns: select bus vehicle, select intersection, select run
  - Multi-strategy queue estimation diagnostics

Usage:
    python plot_shockwave.py
    python plot_shockwave.py --log-dir logs --out shockwave_dashboard.html
"""

import os
import sys
import glob
import argparse
import math
import json
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
import plotly.express as px
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOG_DIR   = os.path.join(os.path.dirname(__file__), "logs")
OUT_HTML  = os.path.join(os.path.dirname(__file__), "shockwave_dashboard.html")

# LWR triangular model parameters (should match intersection_controller.py)
K_JAM   = 200.0   # jam density  (veh/km/lane)
K_SAT   = 35.0    # saturation density (veh/km/lane)
Q_SAT   = 1800.0  # saturation flow   (veh/h/lane)
VF      = Q_SAT / K_SAT        # free-flow speed (km/h)  ≈ 51.4 km/h
W       = -Q_SAT / (K_JAM - K_SAT)  # backward wave speed (km/h, negative)

JUNCTION_LABELS = {
    39606:   "Jct 39606 (KG A1)",
    39590:   "Jct 39590 (KG A2)",
    36393:   "Jct 36393 (KG A3)",
    36385:   "Jct 36385 (KG A4)",
    39593:   "Jct 39593 (KG A5)",
    39576:   "Jct 39576 (KG B1)",
    39578:   "Jct 39578 (KG B2)",
    39587:   "Jct 39587 (KG B3)",
    1043762: "Jct 1043762 (KG B4)",
    39569:   "Jct 39569 (KG B5)",
    39572:   "Jct 39572 (KG B6)",
    38339:   "Jct 38339 (KG B7)",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def latest_file(pattern: str, n: int = 1) -> list:
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return files[:n]


def load_queue_snapshots(log_dir: str) -> dict:
    """Load all queue_snapshot CSV files from log_dir.  Returns dict[experiment -> df]."""
    dfs = {}
    for f in sorted(glob.glob(os.path.join(log_dir, "queue_snapshot_*.csv"))):
        exp = Path(f).stem.replace("queue_snapshot_", "")
        try:
            df = pd.read_csv(f)
            df['experiment'] = exp
            dfs[exp] = df
        except Exception as e:
            print(f"Warning: could not load {f}: {e}")
    return dfs


def load_detection_points(log_dir: str) -> dict:
    """Load all detection_points CSV files.  Returns dict[experiment -> df]."""
    dfs = {}
    for f in sorted(glob.glob(os.path.join(log_dir, "detection_points_*.csv"))):
        exp = Path(f).stem.replace("detection_points_", "")
        try:
            df = pd.read_csv(f)
            df['experiment'] = exp
            dfs[exp] = df
        except Exception as e:
            print(f"Warning: could not load {f}: {e}")
    return dfs


def load_wave_events(log_dir: str) -> dict:
    """Load corridor wave events."""
    dfs = {}
    for f in sorted(glob.glob(os.path.join(log_dir, "corridor_wave_events_*.csv"))):
        exp = Path(f).stem.replace("corridor_wave_events_", "")
        try:
            df = pd.read_csv(f)
            df['experiment'] = exp
            dfs[exp] = df
        except Exception as e:
            print(f"Warning: could not load {f}: {e}")
    return dfs


# ---------------------------------------------------------------------------
# Shockwave profile computation
# ---------------------------------------------------------------------------

def compute_shockwave_profile(
    q_arrive: float,   # approach flow (veh/h)
    t_red: float,      # red duration (s)
    t_green: float,    # green duration (s)
    k_jam:  float = K_JAM,
    k_sat:  float = K_SAT,
    q_sat:  float = Q_SAT,
    t_step: float = 1.0,   # time resolution (s)
):
    """
    Compute the LWR triangular shockwave profile.

    Returns
    -------
    t_arr  : np.ndarray   time values (s, from red start)
    q_arr  : np.ndarray   queue length in vehicles at each time step
    notes  : dict         key wave times and speeds
    """
    if q_arrive <= 0 or t_red <= 0:
        n = int((t_red + t_green) / max(t_step, 0.1)) + 1
        return np.linspace(0, t_red + t_green, n), np.zeros(n), {}

    # LWR triangular model
    vf_km_s = (q_sat / k_sat) / 3600.0       # free-flow speed in km/s
    w_km_s  = (q_sat / (k_jam - k_sat)) / 3600.0  # backward wave speed (km/s, positive magnitude)

    k_arrive = q_arrive / 3600.0 / max(vf_km_s, 1e-9)   # arriving density (veh/km)
    k_arrive = min(k_arrive, k_sat)

    # Backward shockwave speed (positive = growing away from stop line)
    # w_back = (q_arrive/3600 - 0) / (k_arrive - k_jam)  → negative km/s → magnitude:
    w_back = (q_arrive / 3600.0) / max(k_jam - k_arrive, 0.1)   # km/s magnitude

    # During red: queue grows from stop line backwards
    # Queue length at time t: L(t) = w_back * t  (km)
    # Queue in vehicles: N(t) = L(t) * k_jam

    # After green starts: discharge wave propagates backward through queue
    # Discharge (forward) shockwave speed (between queue and discharge zone):
    #   w_fwd = (q_sat - q_arrive) / (k_sat - k_arrive)
    w_fwd = (q_sat - q_arrive) / 3600.0 / max(k_sat - k_arrive, 0.1)  # km/s magnitude

    # Time to clear queue (from green start):
    # Queue at green start: L_max = w_back * t_red
    # Clearance: L(t) = L_max - (w_fwd - w_back) * (t - t_red)  → 0 when t = t_red + L_max/(w_fwd - w_back)
    L_max = w_back * t_red   # km
    t_clear = L_max / max(w_fwd - w_back, 1e-9)   # s from green start

    t_arr = np.arange(0, t_red + t_green + t_step, t_step)
    q_arr = np.zeros(len(t_arr))

    for i, t in enumerate(t_arr):
        if t <= t_red:
            # Red phase: queue growing
            q_arr[i] = (w_back * t) * k_jam        # vehicles in queue
        else:
            dt_green = t - t_red
            if dt_green < t_clear:
                q_arr[i] = max(0.0, (L_max - (w_fwd - w_back) * dt_green) * k_jam)
            else:
                q_arr[i] = 0.0  # queue cleared

    notes = {
        'w_back_kmh': w_back * 3600.0,
        'w_fwd_kmh':  w_fwd  * 3600.0,
        'L_max_m':    L_max  * 1000.0,
        'N_max_veh':  L_max  * k_jam,
        't_clear_s':  t_clear,
        'k_arrive':   k_arrive,
    }
    return t_arr, q_arr, notes


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

def build_queue_bar_figure(queue_dfs: dict, experiments: list, junctions: list) -> go.Figure:
    """Bar chart of queue evolution per intersection, animated over time."""
    if not queue_dfs:
        fig = go.Figure()
        fig.add_annotation(text="No queue snapshot data found", x=0.5, y=0.5,
                           showarrow=False, font_size=16)
        return fig

    exp = experiments[0]
    df  = queue_dfs.get(exp, pd.DataFrame())
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text=f"No data for experiment {exp}", x=0.5, y=0.5,
                           showarrow=False, font_size=16)
        return fig

    # Downsample to ~60 time points
    times = sorted(df['sim_time_s'].unique())
    if len(times) > 120:
        step = max(1, len(times) // 120)
        times = times[::step]
    df = df[df['sim_time_s'].isin(times)]

    fig = go.Figure()
    jct_labels = [JUNCTION_LABELS.get(j, str(j)) for j in junctions]

    frames = []
    for t in times:
        td = df[df['sim_time_s'] == t]
        q_main_vals = []
        q_side_vals = []
        sw_q_main   = []
        sw_q_side   = []
        for jct in junctions:
            row = td[td['junction_id'] == jct]
            if row.empty:
                q_main_vals.append(0); q_side_vals.append(0)
                sw_q_main.append(0);   sw_q_side.append(0)
            else:
                q_main_vals.append(float(row.iloc[0].get('queue_main', 0) or 0))
                q_side_vals.append(float(row.iloc[0].get('queue_side', 0) or 0))
                sw_q_main.append(float(row.iloc[0].get('sw_q_main', 0) or 0))
                sw_q_side.append(float(row.iloc[0].get('sw_q_side', 0) or 0))
        frames.append(go.Frame(
            data=[
                go.Bar(name='Main (snapshot)', x=jct_labels, y=q_main_vals,
                       marker_color='steelblue', offsetgroup='a'),
                go.Bar(name='Side (snapshot)', x=jct_labels, y=q_side_vals,
                       marker_color='coral', offsetgroup='a', base=q_main_vals),
                go.Bar(name='Main (shockwave)', x=jct_labels, y=sw_q_main,
                       marker_color='royalblue', opacity=0.5, offsetgroup='b'),
                go.Bar(name='Side (shockwave)', x=jct_labels, y=sw_q_side,
                       marker_color='tomato', opacity=0.5, offsetgroup='b',
                       base=sw_q_main),
            ],
            name=str(t),
            layout=go.Layout(title_text=f"Queue at t={t:.0f}s ({exp})")
        ))

    # Initial frame
    t0 = times[0] if times else 0
    td0 = df[df['sim_time_s'] == t0]
    for jct in junctions:
        row = td0[td0['junction_id'] == jct]
        if not row.empty:
            break

    fig = go.Figure(
        data=frames[0].data if frames else [],
        frames=frames,
        layout=go.Layout(
            title=f"Queue per Intersection — {exp}",
            barmode='group',
            xaxis_title="Intersection",
            yaxis_title="Queued Vehicles",
            height=500,
            updatemenus=[{
                "buttons": [
                    {"args": [None, {"frame": {"duration": 200, "redraw": True},
                                     "fromcurrent": True}],
                     "label": "▶ Play", "method": "animate"},
                    {"args": [[None], {"frame": {"duration": 0, "redraw": True},
                                       "mode": "immediate", "transition": {"duration": 0}}],
                     "label": "⏸ Pause", "method": "animate"},
                ],
                "direction": "left", "pad": {"r": 10, "t": 87},
                "showactive": False, "type": "buttons", "x": 0.1, "y": 0,
            }],
            sliders=[{
                "active": 0,
                "steps": [{"args": [[f.name], {"frame": {"duration": 200, "redraw": True},
                                               "mode": "immediate",
                                               "transition": {"duration": 0}}],
                            "label": f.name, "method": "animate"}
                           for f in frames],
                "x": 0.1, "len": 0.9, "y": 0,
            }],
        )
    )
    return fig


def build_shockwave_profile_figure(
    queue_dfs: dict,
    detection_dfs: dict,
    exp: str,
    jct_id: int,
    bus_id: int = None,
) -> go.Figure:
    """
    Shockwave trajectory diagram for a single intersection.

    Shows:
    - Queue length over time (from snapshot + shockwave model)
    - LWR theoretical queue profile for each red phase where bus was detected
    - Bus arrival time markers
    - Phase red/green timeline
    """
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=["Queue Length (vehicles)", "Approach Flow & Shockwave Speeds"],
        row_heights=[0.65, 0.35],
        vertical_spacing=0.1,
    )

    df_q = queue_dfs.get(exp, pd.DataFrame())
    df_d = detection_dfs.get(exp, pd.DataFrame())

    jct_label = JUNCTION_LABELS.get(jct_id, str(jct_id))
    fig.update_layout(
        title=f"Shockwave Profile — {jct_label} ({exp})",
        height=700,
        hovermode="x unified",
        legend=dict(orientation="h", y=-0.15),
    )

    if df_q.empty:
        fig.add_annotation(text="No queue data", x=0.5, y=0.5, showarrow=False,
                           row=1, col=1, font_size=14)
        return fig

    jq = df_q[df_q['junction_id'] == jct_id].copy()
    if jq.empty:
        fig.add_annotation(text=f"No data for jct={jct_id}", x=0.5, y=0.5,
                           showarrow=False, row=1, col=1, font_size=14)
        return fig

    jq = jq.sort_values('sim_time_s')

    # ── Row 1: Queue length ──
    # Snapshot counts (physical vehicle scan)
    fig.add_trace(go.Scatter(
        x=jq['sim_time_s'], y=jq.get('queue_main', pd.Series(dtype=float)).fillna(0),
        name='Main queue (snapshot)', mode='lines',
        line=dict(color='steelblue', width=2),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=jq['sim_time_s'], y=jq.get('queue_side', pd.Series(dtype=float)).fillna(0),
        name='Side queue (snapshot)', mode='lines',
        line=dict(color='coral', width=2),
    ), row=1, col=1)

    # Shockwave-estimated queues
    if 'sw_q_main' in jq.columns:
        fig.add_trace(go.Scatter(
            x=jq['sim_time_s'], y=jq['sw_q_main'].fillna(0),
            name='Main queue (shockwave)', mode='lines',
            line=dict(color='navy', width=1.5, dash='dot'),
        ), row=1, col=1)
    if 'sw_q_side' in jq.columns:
        fig.add_trace(go.Scatter(
            x=jq['sim_time_s'], y=jq['sw_q_side'].fillna(0),
            name='Side queue (shockwave)', mode='lines',
            line=dict(color='firebrick', width=1.5, dash='dot'),
        ), row=1, col=1)

    # ── LWR theoretical profile at each red onset ──
    # Detect red phase start times from phase transitions in the queue snapshot
    if 'sw_red_s' in jq.columns and 'sw_flow_main' in jq.columns:
        # Find rows where sw_red_s resets to a small value (new red phase)
        prev_red = jq['sw_red_s'].shift(1, fill_value=999)
        red_starts = jq[jq['sw_red_s'] < prev_red - 10.0]
        for _, rs_row in red_starts.head(8).iterrows():
            t_rs = float(rs_row['sim_time_s'])
            q_arr = float(rs_row.get('sw_flow_main', 0) or 0)
            if q_arr < 10:
                q_arr = 400.0
            t_red_est = float(rs_row.get('sw_red_s', 30) or 30)
            t_green_est = 30.0
            t_profile, q_profile, notes = compute_shockwave_profile(
                q_arrive=q_arr, t_red=t_red_est, t_green=t_green_est)
            t_abs = t_rs + t_profile
            hover_text = (
                f"LWR profile<br>"
                f"q_arrive={q_arr:.0f} veh/h<br>"
                f"w_back={notes.get('w_back_kmh', 0):.1f} km/h<br>"
                f"w_fwd={notes.get('w_fwd_kmh', 0):.1f} km/h<br>"
                f"L_max={notes.get('L_max_m', 0):.0f} m<br>"
                f"N_max={notes.get('N_max_veh', 0):.0f} veh<br>"
                f"t_clear={notes.get('t_clear_s', 0):.1f} s"
            )
            fig.add_trace(go.Scatter(
                x=t_abs, y=q_profile,
                name=f"LWR t={t_rs:.0f}s",
                mode='lines',
                line=dict(color='orange', width=1.5, dash='dash'),
                hovertemplate=hover_text + "<extra></extra>",
                legendgroup='lwr',
                showlegend=(rs_row is red_starts.head(1).iloc[0]),
            ), row=1, col=1)

    # ── Bus detection markers ──
    if not df_d.empty:
        jd = df_d[df_d['junction_id'] == jct_id].copy()
        if bus_id and bus_id > 0:
            jd = jd[jd['veh_id'] == bus_id]
        if not jd.empty:
            fig.add_trace(go.Scatter(
                x=jd['sim_time_s'], y=[1.5] * len(jd),
                mode='markers+text', name='Bus detection',
                marker=dict(symbol='triangle-up', size=10, color='green'),
                text=[str(v) for v in jd['veh_id']],
                textposition='top center',
                hovertemplate='Bus %{text} at t=%{x:.1f}s<extra></extra>',
            ), row=1, col=1)

    # ── Row 2: Flow and shockwave speeds ──
    if 'sw_flow_main' in jq.columns:
        fig.add_trace(go.Scatter(
            x=jq['sim_time_s'], y=jq['sw_flow_main'].fillna(0),
            name='Main approach flow (veh/h)', mode='lines',
            line=dict(color='teal', width=1.5),
        ), row=2, col=1)
    if 'sw_flow_side' in jq.columns:
        fig.add_trace(go.Scatter(
            x=jq['sim_time_s'], y=jq['sw_flow_side'].fillna(0),
            name='Side flow (veh/h)', mode='lines',
            line=dict(color='orangered', width=1.5),
        ), row=2, col=1)
    if 'sw_density_main' in jq.columns:
        fig.add_trace(go.Scatter(
            x=jq['sim_time_s'], y=jq['sw_density_main'].fillna(0) * 10,  # scale to plot
            name='Main density ×10 (veh/km)', mode='lines',
            line=dict(color='purple', width=1.2, dash='dot'),
        ), row=2, col=1)

    # ── Shockwave speed annotations ──
    # Backward wave speed = Q_arrive / (K_jam - K_arrive)
    if 'sw_flow_main' in jq.columns and 'sw_density_main' in jq.columns:
        _f = jq['sw_flow_main'].fillna(0)
        _k = jq['sw_density_main'].fillna(0)
        _w_back = _f / 3600.0 / np.maximum(K_JAM - _k, 1.0) * 3600.0  # km/h
        fig.add_trace(go.Scatter(
            x=jq['sim_time_s'], y=_w_back,
            name='Backward wave speed (km/h)',
            mode='lines', line=dict(color='darkred', width=1.2),
            visible='legendonly',
        ), row=2, col=1)

    fig.update_yaxes(title_text="Queue (vehicles)", row=1, col=1)
    fig.update_yaxes(title_text="Flow (veh/h)", row=2, col=1)
    fig.update_xaxes(title_text="Simulation time (s)", row=2, col=1)

    return fig


def build_bus_detection_timeline(
    detection_dfs: dict,
    wave_dfs: dict,
    exp: str,
    jct_id: int = None,
    bus_id: int = None,
) -> go.Figure:
    """
    Timeline of bus detections and wave events for a given intersection or bus.
    """
    df_d = detection_dfs.get(exp, pd.DataFrame())
    df_w = wave_dfs.get(exp, pd.DataFrame())

    fig = go.Figure()
    fig.update_layout(
        title=f"Bus Detection Timeline — {exp}"
               + (f" jct={jct_id}" if jct_id else "")
               + (f" bus={bus_id}" if bus_id else ""),
        height=400,
        xaxis_title="Simulation time (s)",
        yaxis_title="Junction ID",
        hovermode="closest",
    )

    if df_d.empty:
        fig.add_annotation(text="No detection data", x=0.5, y=0.5, showarrow=False)
        return fig

    dd = df_d.copy()
    if jct_id:
        dd = dd[dd['junction_id'] == jct_id]
    if bus_id and bus_id > 0:
        dd = dd[dd['veh_id'] == bus_id]

    tiers = dd['tier'].unique() if 'tier' in dd.columns else ['IC-detect']
    colors = px.colors.qualitative.Plotly
    for ti, tier in enumerate(tiers):
        td = dd[dd['tier'] == tier] if 'tier' in dd.columns else dd
        fig.add_trace(go.Scatter(
            x=td['sim_time_s'],
            y=td['junction_id'],
            mode='markers',
            name=tier,
            marker=dict(size=8, color=colors[ti % len(colors)], symbol='circle'),
            text=[f"bus={v} phase={p}" for v, p in
                  zip(td.get('veh_id', []), td.get('signal_phase', []))],
            hovertemplate="t=%{x:.1f}s jct=%{y}<br>%{text}<extra></extra>",
        ))

    # Wave grant events
    if not df_w.empty:
        dw = df_w[df_w['event'].isin(['grant', 'prearm_fired', 'prearm_success'])]
        if jct_id:
            dw = dw[(dw['source_jct'] == jct_id) | (dw['target_jct'] == jct_id)]
        if bus_id and bus_id > 0:
            dw = dw[dw['veh_id'] == bus_id]
        ev_colors = {'grant': 'green', 'prearm_fired': 'orange', 'prearm_success': 'blue'}
        for ev, grp in dw.groupby('event'):
            fig.add_trace(go.Scatter(
                x=grp['sim_time_s'], y=grp['target_jct'],
                mode='markers', name=ev,
                marker=dict(size=12, color=ev_colors.get(ev, 'grey'),
                            symbol='diamond', line=dict(width=1, color='black')),
                hovertemplate=f"{ev} t=%{{x:.1f}}s jct=%{{y}}<extra></extra>",
            ))

    return fig


# ---------------------------------------------------------------------------
# Full shockwave equation annotation panel
# ---------------------------------------------------------------------------

def build_shockwave_equations_panel(
    q_arrive: float = 400.0,
    t_red: float = 45.0,
    t_green: float = 30.0,
    k_jam: float = K_JAM,
    k_sat: float = K_SAT,
    q_sat: float = Q_SAT,
) -> go.Figure:
    """
    Illustrative shockwave profile with LWR equation annotations.
    Fixed-parameter demo panel showing the theory.
    """
    t_arr, q_arr, notes = compute_shockwave_profile(q_arrive, t_red, t_green, k_jam, k_sat, q_sat)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=t_arr, y=q_arr, mode='lines',
        line=dict(color='darkblue', width=3),
        name='Queue length N(t)',
        hovertemplate="t=%{x:.1f}s  N=%{y:.1f} veh<extra></extra>",
    ))

    # Phase background shading
    fig.add_vrect(x0=0, x1=t_red, fillcolor='red', opacity=0.08, line_width=0,
                  annotation_text="RED", annotation_position="top left")
    fig.add_vrect(x0=t_red, x1=t_red + t_green, fillcolor='green', opacity=0.08, line_width=0,
                  annotation_text="GREEN", annotation_position="top left")

    # Max queue marker
    t_max_idx = int(t_red / 1.0)
    if t_max_idx < len(t_arr):
        fig.add_trace(go.Scatter(
            x=[t_arr[t_max_idx]], y=[q_arr[t_max_idx]],
            mode='markers+text',
            marker=dict(color='red', size=14, symbol='diamond'),
            text=[f"N_max = {q_arr[t_max_idx]:.0f} veh"],
            textposition='top right',
            name='Max queue',
        ))

    # Equation annotations
    w_back = notes.get('w_back_kmh', 0)
    w_fwd  = notes.get('w_fwd_kmh',  0)
    L_max  = notes.get('L_max_m',    0)
    N_max  = notes.get('N_max_veh',  0)
    t_cl   = notes.get('t_clear_s',  0)
    k_arr  = notes.get('k_arrive',   0)

    eq_lines = [
        f"<b>LWR Triangular Model</b>",
        f"",
        f"Approach flow:  q = {q_arrive:.0f} veh/h",
        f"Saturation flow: q_s = {q_sat:.0f} veh/h",
        f"Jam density:     k_j = {k_jam:.0f} veh/km",
        f"Sat density:     k_s = {k_sat:.0f} veh/km",
        f"",
        f"Arriving density:",
        f"  k_arr = q / v_f = {k_arr:.1f} veh/km",
        f"",
        f"Backward wave speed:",
        f"  w_b = q / (k_j − k_arr) = {w_back:.1f} km/h",
        f"",
        f"Max queue length:",
        f"  L_max = |w_b| × t_red = {L_max:.0f} m",
        f"  N_max = L_max × k_j = {N_max:.0f} veh",
        f"",
        f"Forward shockwave speed:",
        f"  w_f = (q_s − q) / (k_s − k_arr) = {w_fwd:.1f} km/h",
        f"",
        f"Queue clearance time:",
        f"  t_clear = L_max / (w_f − |w_b|) = {t_cl:.1f} s",
    ]

    fig.add_annotation(
        x=1.01, y=0.99, xref='paper', yref='paper',
        text="<br>".join(eq_lines),
        showarrow=False, align='left',
        bgcolor='lightyellow', bordercolor='goldenrod', borderwidth=1,
        font=dict(family='monospace', size=11),
        xanchor='left', yanchor='top',
    )

    fig.update_layout(
        title="Shockwave Profile — LWR Triangular Model",
        xaxis_title="Time from red start (s)",
        yaxis_title="Queue length (vehicles)",
        height=500,
        margin=dict(r=350),
    )
    return fig


# ---------------------------------------------------------------------------
# Multi-strategy diagnostic table
# ---------------------------------------------------------------------------

def build_strategy_table(queue_dfs: dict, exp: str) -> go.Figure:
    """
    A table summarising queue estimation strategy used per intersection.
    """
    df = queue_dfs.get(exp, pd.DataFrame())
    if df.empty or 'sw_strat_main' not in df.columns:
        fig = go.Figure()
        fig.add_annotation(text="No strategy data (run with updated intersection_controller.py)",
                           x=0.5, y=0.5, showarrow=False)
        return fig

    # Latest snapshot for each junction
    latest = df.groupby('junction_id').last().reset_index()

    jcts   = [JUNCTION_LABELS.get(j, str(j)) for j in latest['junction_id']]
    s_main = list(latest.get('sw_strat_main', pd.Series(['?'] * len(latest))))
    s_side = list(latest.get('sw_strat_side', pd.Series(['?'] * len(latest))))
    f_main = [f"{v:.0f}" for v in latest.get('sw_flow_main', pd.Series([0]*len(latest))).fillna(0)]
    d_main = [f"{v:.2f}" for v in latest.get('sw_density_main', pd.Series([0]*len(latest))).fillna(0)]
    f_side = [f"{v:.0f}" for v in latest.get('sw_flow_side', pd.Series([0]*len(latest))).fillna(0)]
    q_main = [f"{v:.1f}" for v in latest.get('sw_q_main', pd.Series([0]*len(latest))).fillna(0)]
    q_side = [f"{v:.1f}" for v in latest.get('sw_q_side', pd.Series([0]*len(latest))).fillna(0)]

    fig = go.Figure(data=[go.Table(
        header=dict(
            values=["Intersection", "Main Strategy", "Side Strategy",
                    "Flow Main (veh/h)", "Density Main (veh/km)",
                    "Flow Side (veh/h)", "SW Queue Main", "SW Queue Side"],
            fill_color='paleturquoise', align='left', font_size=12,
        ),
        cells=dict(
            values=[jcts, s_main, s_side, f_main, d_main, f_side, q_main, q_side],
            fill_color='lavender', align='left', font_size=11,
        ),
    )])
    fig.update_layout(title=f"Queue Estimation Strategy Summary — {exp}", height=400)
    return fig


# ---------------------------------------------------------------------------
# Main dashboard builder
# ---------------------------------------------------------------------------

def build_dashboard(log_dir: str, out_html: str):
    print(f"Loading data from: {log_dir}")

    queue_dfs     = load_queue_snapshots(log_dir)
    detection_dfs = load_detection_points(log_dir)
    wave_dfs      = load_wave_events(log_dir)

    experiments = sorted(queue_dfs.keys()) or sorted(detection_dfs.keys()) or ['unknown']
    junctions   = sorted(JUNCTION_LABELS.keys())

    print(f"  Experiments: {experiments}")
    print(f"  Queue files:     {len(queue_dfs)}")
    print(f"  Detection files: {len(detection_dfs)}")

    # Build all figures
    figures = {}

    for exp in experiments:
        # 1. Animated queue bar chart
        figures[f'queue_bar_{exp}'] = build_queue_bar_figure(
            queue_dfs, [exp], junctions)

        # 2. Shockwave profile per junction (first 4 junctions by default)
        for jct in junctions[:4]:
            key = f'sw_profile_{exp}_{jct}'
            figures[key] = build_shockwave_profile_figure(
                queue_dfs, detection_dfs, exp, jct)

        # 3. Detection timeline
        figures[f'detection_{exp}'] = build_bus_detection_timeline(
            detection_dfs, wave_dfs, exp)

        # 4. Strategy table
        figures[f'strat_{exp}'] = build_strategy_table(queue_dfs, exp)

    # 5. LWR equation panel (demo, using typical values)
    figures['lwr_demo'] = build_shockwave_equations_panel()

    # Assemble HTML with JS dropdowns
    _build_html(figures, experiments, junctions, detection_dfs, out_html)
    print(f"\nDashboard written: {out_html}")


def _build_html(figures: dict, experiments: list, junctions: list,
                detection_dfs: dict, out_html: str):
    """Assemble single-file HTML with embedded Plotly figures and JS tabs."""
    import plotly.io as pio

    # Collect all bus IDs across all experiments
    all_bus_ids = set()
    for exp, df in detection_dfs.items():
        if 'veh_id' in df.columns:
            all_bus_ids.update(df['veh_id'].unique())
    all_bus_ids = sorted(all_bus_ids)

    html_parts = ["""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Shockwave Dashboard — Logan Road</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; }
    .header { background: #1a3a5c; color: white; padding: 16px 24px; }
    .header h1 { margin:0; font-size:22px; }
    .controls { background: #e8ecf0; padding: 12px 24px; display:flex; gap:16px; flex-wrap:wrap; }
    .controls label { font-weight:bold; font-size:13px; }
    .controls select { padding:6px; border-radius:4px; border:1px solid #aaa; font-size:13px; min-width:180px; }
    .tab-bar { background:#2c5282; display:flex; padding:0 16px; overflow-x:auto; }
    .tab { color:#c0d8f0; padding:10px 18px; cursor:pointer; font-size:13px; white-space:nowrap; }
    .tab.active { background:white; color:#1a3a5c; font-weight:bold; border-top:3px solid #e57340; }
    .tab:hover { background:#3a6898; }
    .panel { display:none; padding:12px; }
    .panel.active { display:block; }
    .plot-container { background:white; border-radius:6px; box-shadow:0 1px 4px rgba(0,0,0,.15); margin-bottom:12px; }
    .info-box { background:#fffde7; border:1px solid #f9c74f; border-radius:6px; padding:12px 16px; margin:8px 0; font-size:13px; }
    .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  </style>
</head>
<body>
  <div class="header">
    <h1>Shockwave Dashboard — Logan Road Corridor</h1>
  </div>

  <div class="controls">
    <div>
      <label for="sel_exp">Experiment / Run:</label><br>
      <select id="sel_exp" onchange="onSelChange()">
"""]

    for exp in experiments:
        html_parts.append(f'        <option value="{exp}">{exp}</option>\n')
    html_parts.append("      </select>\n    </div>\n")

    html_parts.append("""    <div>
      <label for="sel_jct">Intersection:</label><br>
      <select id="sel_jct" onchange="onSelChange()">
        <option value="all">All intersections</option>
""")
    for jct in junctions:
        lbl = JUNCTION_LABELS.get(jct, str(jct))
        html_parts.append(f'        <option value="{jct}">{lbl}</option>\n')
    html_parts.append("      </select>\n    </div>\n")

    html_parts.append("""    <div>
      <label for="sel_bus">Bus vehicle:</label><br>
      <select id="sel_bus" onchange="onSelChange()">
        <option value="0">All buses</option>
""")
    for bid in all_bus_ids[:60]:
        html_parts.append(f'        <option value="{bid}">Bus {bid}</option>\n')
    html_parts.append("      </select>\n    </div>\n  </div>\n")

    # Tabs
    tabs = [
        ("tab_queue",  "Queue Bar Charts"),
        ("tab_sw",     "Shockwave Profiles"),
        ("tab_detect", "Bus Detection Timeline"),
        ("tab_strat",  "Queue Strategy Diagnostics"),
        ("tab_lwr",    "Shockwave Equations"),
    ]
    html_parts.append('<div class="tab-bar">\n')
    for tid, tlabel in tabs:
        active = ' class="tab active"' if tid == tabs[0][0] else ' class="tab"'
        html_parts.append(f'  <div{active} onclick="showTab(\'{tid}\')" id="tabBtn_{tid}">{tlabel}</div>\n')
    html_parts.append('</div>\n')

    # --- Embed figures as divs ---
    div_map = {}  # figure_key -> div_id

    # Helper: serialize figure to div
    def fig_div(fig_key: str, fig: go.Figure) -> str:
        did = f"fig_{fig_key}"
        div_map[fig_key] = did
        return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                           div_id=did, default_width='100%', default_height='100%')

    # Include plotlyjs once
    html_parts.append('<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>\n')

    # Panel: Queue bar charts
    html_parts.append('<div id="tab_queue" class="panel active">\n')
    html_parts.append('<div class="info-box">Queue bar charts show physical snapshot counts (solid) and shockwave-estimated counts (transparent). '
                      'Use the Play button to animate over simulation time.</div>\n')
    for exp in experiments:
        key = f'queue_bar_{exp}'
        if key in figures:
            html_parts.append(f'<div class="plot-container" data-exp="{exp}">\n')
            html_parts.append(fig_div(key, figures[key]))
            html_parts.append('</div>\n')
    html_parts.append('</div>\n')

    # Panel: Shockwave profiles
    html_parts.append('<div id="tab_sw" class="panel">\n')
    html_parts.append('<div class="info-box">Shockwave profiles per intersection. '
                      'Blue dotted = shockwave-estimated queue. Orange dashed = LWR theoretical profile at each red phase. '
                      'Green triangles = bus detections.</div>\n')
    for exp in experiments:
        html_parts.append(f'<div class="grid2" data-exp="{exp}">\n')
        for jct in junctions[:8]:
            key = f'sw_profile_{exp}_{jct}'
            if key in figures:
                html_parts.append(f'<div class="plot-container" data-jct="{jct}">\n')
                html_parts.append(fig_div(key, figures[key]))
                html_parts.append('</div>\n')
        html_parts.append('</div>\n')
    html_parts.append('</div>\n')

    # Panel: Detection timeline
    html_parts.append('<div id="tab_detect" class="panel">\n')
    for exp in experiments:
        key = f'detection_{exp}'
        if key in figures:
            html_parts.append(f'<div class="plot-container" data-exp="{exp}">\n')
            html_parts.append(fig_div(key, figures[key]))
            html_parts.append('</div>\n')
    html_parts.append('</div>\n')

    # Panel: Strategy diagnostics
    html_parts.append('<div id="tab_strat" class="panel">\n')
    html_parts.append('<div class="info-box">Queue estimation strategies per intersection: <br>'
                      '<b>snapshot</b> = AKIVehStateGetVehicleInfSection scan (v&lt;5 km/h) &nbsp;|&nbsp; '
                      '<b>shockwave</b> = LWR model from approach flow + red time &nbsp;|&nbsp; '
                      '<b>SideUpFlow</b> = SideUpFlowList from _sample_side_sections &nbsp;|&nbsp; '
                      '<b>default400</b> = urban default 400 veh/h (all side sections virtual)</div>\n')
    for exp in experiments:
        key = f'strat_{exp}'
        if key in figures:
            html_parts.append(f'<div class="plot-container" data-exp="{exp}">\n')
            html_parts.append(fig_div(key, figures[key]))
            html_parts.append('</div>\n')
    html_parts.append('</div>\n')

    # Panel: LWR equations
    html_parts.append('<div id="tab_lwr" class="panel">\n')
    html_parts.append('<div class="info-box">'
                      'LWR triangular flow model used for all shockwave calculations. '
                      'Adjust q_arrive and phase timing to explore different scenarios.</div>\n')
    if 'lwr_demo' in figures:
        html_parts.append('<div class="plot-container">\n')
        html_parts.append(fig_div('lwr_demo', figures['lwr_demo']))
        html_parts.append('</div>\n')
    html_parts.append('</div>\n')

    # JS
    html_parts.append("""
<script>
function showTab(id) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.getElementById('tabBtn_' + id).classList.add('active');
}

function onSelChange() {
  const exp = document.getElementById('sel_exp').value;
  const jct = document.getElementById('sel_jct').value;
  // Highlight matching panels (simple visibility by data-exp attribute)
  document.querySelectorAll('[data-exp]').forEach(el => {
    el.style.display = (el.dataset.exp === exp || exp === 'all') ? '' : 'none';
  });
  document.querySelectorAll('[data-jct]').forEach(el => {
    el.style.display = (jct === 'all' || el.dataset.jct === jct) ? '' : 'none';
  });
}
</script>
</body></html>
""")

    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(''.join(html_parts))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate shockwave dashboard')
    parser.add_argument('--log-dir', default=LOG_DIR, help='Directory containing log CSVs')
    parser.add_argument('--out', default=OUT_HTML, help='Output HTML file path')
    args = parser.parse_args()

    build_dashboard(args.log_dir, args.out)
