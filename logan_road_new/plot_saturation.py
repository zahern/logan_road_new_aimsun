"""
Saturation / Macroscopic Fundamental Diagram (MFD) plot.

Shows each experiment as a point on the Flow–Density plane and overlays the
theoretical Greenshields capacity curve so you can see whether DCTSP_MARL is
pushing the network toward or away from saturation.

Also produces a companion Flow–Delay scatter so "flow maintained at lower delay"
is visually obvious.

Usage:
    python plot_saturation.py                        # auto-discover
    python plot_saturation.py batch_results.csv out.html
"""

import os, sys, csv, math, json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

_batch_csv = os.path.join(SCRIPT_DIR, "batch_results.csv")
_out_html  = os.path.join(SCRIPT_DIR, "saturation_mfd.html")
if len(sys.argv) >= 2: _batch_csv = sys.argv[1]
if len(sys.argv) >= 3: _out_html  = sys.argv[2]

# ── helpers ────────────────────────────────────────────────────────────────────
def _f(v, d=None):
    try:
        fv = float(v)
        return fv if math.isfinite(fv) else d
    except Exception:
        return d

def _load(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

# ── Greenshields MFD curve ─────────────────────────────────────────────────────
def _greenshields_curve(vf_kmh=60.0, kj_vkm=100.0, n=120):
    """
    Greenshields linear speed-density model:
        v(k) = vf × (1 – k/kj)
        q(k) = k × v(k) = vf × k × (1 – k/kj)
    Returns (k_vals, q_vals) lists.
    """
    ks = [kj_vkm * i / n for i in range(n + 1)]
    qs = [vf_kmh * k * (1 - k / kj_vkm) for k in ks]
    return ks, qs

# ── colours ────────────────────────────────────────────────────────────────────
EXP_COLOURS = {
    "NO_TSP":         "#9E9E9E",
    "DCTSP_MARL":     "#E91E63",
    "HARMONY_COORD":  "#4CAF50",
    "HARMONY_INDEP":  "#2196F3",
    "DRL_DENSITY":    "#FF9800",
    "GLOBAL_REWARD":  "#9C27B0",
    "LOCAL_REWARD":   "#00BCD4",
}
DEFAULT_C = "#607D8B"

# ── load + aggregate ───────────────────────────────────────────────────────────
rows = _load(_batch_csv)
if not rows:
    print(f"[plot_saturation] no data in {_batch_csv}")
    sys.exit(0)

# Columns to read (try multiple aliases)
def _pick(row, *keys, d=None):
    for k in keys:
        v = _f(row.get(k), None)
        if v is not None:
            return v
    return d

by_exp = {}
for r in rows:
    if _f(r.get("run_success", "1"), 1) < 0.5:
        continue
    exp = r.get("run_experiment", r.get("run_strategy", "?")).strip()
    density  = _pick(r, "aimsun_avg_density_vkm",  "stats_Net_Density_All",   d=None)
    flow     = _pick(r, "aimsun_total_flow_veh",                               d=None)
    speed    = _pick(r, "aimsun_avg_speed_kmh",    "stats_Net_AvgSpeed_kmh",   d=None)
    delay    = _pick(r, "aimsun_avg_delay_s_km",   "stats_Net_Delay_All",       d=None)
    veh_km_h = _pick(r, "aimsun_total_veh_km_h",                               d=None)
    avg_bus_tt = _pick(r, "stats_AvgBusTT_s",                                  d=None)
    objective  = _pick(r, "stats_Objective_PaxPerDelayHr",                     d=None)
    if exp not in by_exp:
        by_exp[exp] = []
    by_exp[exp].append(dict(
        density=density, flow=flow, speed=speed, delay=delay,
        veh_km_h=veh_km_h, avg_bus_tt=avg_bus_tt, objective=objective,
        seed=r.get("run_seed", "?"),
    ))

if not by_exp:
    print("[plot_saturation] no valid rows after filtering")
    sys.exit(0)

# ── Theoretical MFD ─────────────────────────────────────────────────────────
# Estimate free-flow speed from NO_TSP if available, else default 50 km/h
_vf = 50.0
if "NO_TSP" in by_exp:
    spds = [p["speed"] for p in by_exp["NO_TSP"] if p["speed"] is not None]
    if spds: _vf = max(spds)

_kj = 120.0   # jam density veh/km (typical urban)
_curve_k, _curve_q = _greenshields_curve(_vf, _kj)
_curve_v = [(_q / _k if _k > 0 else _vf) for _k, _q in zip(_curve_k, _curve_q)]
_k_cap   = _kj / 2
_q_cap   = _vf * _kj / 4

# ── Build Plotly traces ────────────────────────────────────────────────────────
traces = []

# Theoretical capacity curve
traces.append({
    "type": "scatter", "mode": "lines",
    "x": _curve_k, "y": _curve_q,
    "name": f"Greenshields capacity (vf={_vf:.0f} km/h, kj={_kj:.0f} veh/km)",
    "line": {"color": "#FF5722", "dash": "dash", "width": 2},
    "hoverinfo": "skip",
    "xaxis": "x", "yaxis": "y",
})
# Capacity point
traces.append({
    "type": "scatter", "mode": "markers+text",
    "x": [_k_cap], "y": [_q_cap],
    "text": [f"  Capacity<br>q={_q_cap:.0f} veh/h<br>k={_k_cap:.0f} veh/km"],
    "textposition": "top right",
    "marker": {"symbol": "star", "size": 14, "color": "#FF5722"},
    "name": "Capacity point",
    "hoverinfo": "text",
    "showlegend": False,
    "xaxis": "x", "yaxis": "y",
})

# Data points per experiment
for exp, pts in sorted(by_exp.items()):
    colour = EXP_COLOURS.get(exp, DEFAULT_C)
    xs, ys, texts = [], [], []
    for p in pts:
        if p["density"] is None or p["flow"] is None:
            continue
        xs.append(p["density"])
        ys.append(p["flow"])
        speed_str = f"{p['speed']:.1f} km/h" if p["speed"] else "–"
        delay_str = f"{p['delay']:.1f} s/km" if p["delay"] else "–"
        bus_str   = f"{p['avg_bus_tt']:.0f} s" if p["avg_bus_tt"] else "–"
        obj_str   = f"{p['objective']:.1f}" if p["objective"] else "–"
        texts.append(
            f"<b>{exp}</b> seed={p['seed']}<br>"
            f"Density: {p['density']:.2f} veh/km<br>"
            f"Flow: {p['flow']:.1f} veh/h<br>"
            f"Speed: {speed_str}<br>"
            f"Delay: {delay_str}<br>"
            f"Avg Bus TT: {bus_str}<br>"
            f"Pax/Delay-hr: {obj_str}"
        )
    if not xs:
        continue
    traces.append({
        "type": "scatter", "mode": "markers+text" if len(xs) == 1 else "markers",
        "x": xs, "y": ys, "text": [exp] * len(xs),
        "hovertext": texts, "hoverinfo": "text",
        "textposition": "top right",
        "name": exp,
        "marker": {"size": 14, "color": colour, "symbol": "circle",
                   "line": {"color": "white", "width": 1}},
        "xaxis": "x", "yaxis": "y",
    })

# ── Flow vs Speed (fundamental diagram, 2nd subplot) ──────────────────────────
traces2 = []
traces2.append({
    "type": "scatter", "mode": "lines",
    "x": _curve_v, "y": _curve_q,
    "name": "Greenshields (speed-flow)",
    "line": {"color": "#FF5722", "dash": "dash", "width": 2},
    "hoverinfo": "skip",
    "xaxis": "x2", "yaxis": "y2",
    "showlegend": False,
})
for exp, pts in sorted(by_exp.items()):
    colour = EXP_COLOURS.get(exp, DEFAULT_C)
    xs2, ys2, texts2 = [], [], []
    for p in pts:
        if p["speed"] is None or p["flow"] is None:
            continue
        xs2.append(p["speed"])
        ys2.append(p["flow"])
        texts2.append(f"<b>{exp}</b> seed={p['seed']}<br>Speed:{p['speed']:.1f} km/h  Flow:{p['flow']:.1f} veh/h")
    if not xs2:
        continue
    traces2.append({
        "type": "scatter", "mode": "markers",
        "x": xs2, "y": ys2,
        "hovertext": texts2, "hoverinfo": "text",
        "name": exp,
        "marker": {"size": 14, "color": colour, "symbol": "circle",
                   "line": {"color": "white", "width": 1}},
        "xaxis": "x2", "yaxis": "y2",
        "showlegend": False,
    })

# ── Total throughput bar chart (3rd panel) ────────────────────────────────────
traces3 = []
for exp, pts in sorted(by_exp.items()):
    colour = EXP_COLOURS.get(exp, DEFAULT_C)
    vals = [p["veh_km_h"] for p in pts if p["veh_km_h"] is not None]
    if not vals:
        continue
    avg_val = sum(vals) / len(vals)
    traces3.append({
        "type": "bar",
        "x": [exp], "y": [avg_val],
        "name": exp,
        "marker": {"color": colour},
        "hovertext": [f"{exp}: {avg_val:.1f} veh-km/h"],
        "hoverinfo": "text",
        "xaxis": "x3", "yaxis": "y3",
        "showlegend": False,
        "text": [f"{avg_val:.0f}"],
        "textposition": "outside",
    })

all_traces = traces + traces2 + traces3

layout = {
    "title": {"text": "Network Saturation Analysis (Macroscopic Fundamental Diagram)", "x": 0.5},
    "grid": {"rows": 1, "columns": 3, "pattern": "independent"},
    "xaxis":  {"title": "Density (veh/km)",  "domain": [0.00, 0.30]},
    "yaxis":  {"title": "Flow (veh/h)"},
    "xaxis2": {"title": "Speed (km/h)",       "domain": [0.37, 0.67]},
    "yaxis2": {"title": "Flow (veh/h)", "anchor": "x2"},
    "xaxis3": {"title": "Strategy",            "domain": [0.73, 1.00]},
    "yaxis3": {"title": "Total throughput (veh-km/h)", "anchor": "x3"},
    "height": 560,
    "hovermode": "closest",
    "legend": {"orientation": "h", "y": -0.18},
    "annotations": [
        {"text": "<b>Flow–Density MFD</b>", "x": 0.15, "y": 1.06, "xref": "paper", "yref": "paper",
         "showarrow": False, "font": {"size": 13}},
        {"text": "<b>Speed–Flow Diagram</b>", "x": 0.52, "y": 1.06, "xref": "paper", "yref": "paper",
         "showarrow": False, "font": {"size": 13}},
        {"text": "<b>Total Throughput</b>", "x": 0.865, "y": 1.06, "xref": "paper", "yref": "paper",
         "showarrow": False, "font": {"size": 13}},
    ],
}

fig_json = json.dumps({"data": all_traces, "layout": layout})

HTML = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<title>Saturation MFD</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
</head><body style="font-family:sans-serif;padding:16px">
<h2>Network Saturation / Macroscopic Fundamental Diagram</h2>
<p style="color:#555;max-width:900px">
  Each point is one simulation run. The dashed curve is the theoretical
  Greenshields capacity envelope. Points well below and to the left of the
  capacity point (★) are in <em>free-flow</em> — TSP is not pushing the network
  toward saturation. The <em>Total Throughput</em> bar shows total vehicle-km/h
  moved; a strategy that raises throughput while keeping density low is improving
  efficiency without creating congestion.
</p>
<div id="fig" style="width:100%;height:560px"></div>
<script>
Plotly.newPlot('fig', {fig_json}['data'], {fig_json}['layout'], {{responsive:true}});
</script>
</body></html>"""

with open(_out_html, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"[plot_saturation] written -> {_out_html}")
