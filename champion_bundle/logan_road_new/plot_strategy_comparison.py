"""
plot_strategy_comparison.py — DCTSP reward decomposition dashboard

Reads reward_cycle_*.csv from logs/ and shows for each strategy:
  - Action frequency and average reward when chosen
  - Component breakdown: bus_saved vs other_inc vs total cost
  - NO_ACTION baseline comparison (delta per action)
  - Temporal reward scatter
  - Summary table

NOTE on reward semantics: The NO_ACTION reward represents doing nothing
and waiting for the natural green. Total cost includes BOTH bus delay AND
other-vehicle (car/truck) delay at the intersection, weighted by occupancy.
Reward = bus_saved × BusOcc − BETA × other_inc × car_occ − GAMMA × side_inc × car_occ.


and the quantitative difference across strategies.

Usage:
    python plot_strategy_comparison.py
    python plot_strategy_comparison.py batch_results.csv logs/ out.html
"""

import os
import csv
import glob
import sys
import json
import math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── resolve paths ──────────────────────────────────────────────────────────────
_batch_csv = os.path.join(SCRIPT_DIR, 'batch_results.csv')
_log_dir   = os.path.join(SCRIPT_DIR, 'logs')
_out_html  = os.path.join(SCRIPT_DIR, 'strategy_comparison.html')

if len(sys.argv) >= 2:
    _batch_csv = sys.argv[1]
if len(sys.argv) >= 3:
    _log_dir = sys.argv[2]
if len(sys.argv) >= 4:
    _out_html = sys.argv[3]

# ── helpers ────────────────────────────────────────────────────────────────────
def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def _i(v, d=0):
    try:
        return int(float(v))
    except Exception:
        return d


EXP_COLOURS = {
    'NO_TSP':         '#9E9E9E',
    'HARMONY_INDEP':  '#2196F3',
    'HARMONY_COORD':  '#4CAF50',
    'URTSP':          '#FF9800',
    'REWARD_TSP':     '#9C27B0',
}
DEFAULT_COLOUR = '#607D8B'

EXP_ORDER = ['NO_TSP', 'HARMONY_INDEP', 'HARMONY_COORD', 'URTSP', 'REWARD_TSP']

# ── load batch results ─────────────────────────────────────────────────────────
def _load_batch(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _agg_by_experiment(rows):
    """Group batch rows by run_experiment and compute mean over seeds."""
    groups = {}
    for r in rows:
        exp = r.get('run_experiment', r.get('run_strategy', 'UNKNOWN')).strip()
        if exp not in groups:
            groups[exp] = []
        groups[exp].append(r)
    result = {}
    for exp, grp in groups.items():
        n = len(grp)
        agg = {'experiment': exp, 'n_seeds': n}
        # Average numeric columns
        all_keys = set()
        for g in grp:
            all_keys.update(g.keys())
        for k in all_keys:
            if k.startswith('run_') or k == 'stats_ExperimentID':
                agg[k] = grp[0].get(k, '')
                continue
            vals = [_f(g.get(k, ''), None) for g in grp]
            vals = [v for v in vals if v is not None]
            if vals:
                agg[k] = sum(vals) / len(vals)
        result[exp] = agg
    return result


# ── load objective trace CSVs ──────────────────────────────────────────────────
def _load_obj_traces(log_dir):
    """Return dict: {experiment_name: [rows...]} from objective_trace_*.csv."""
    out = {}
    for path in glob.glob(os.path.join(log_dir, 'objective_trace_*.csv')):
        base = os.path.basename(path)
        # Extract experiment name from filename: objective_trace_<EXP>_<ts>.csv
        stem = base[len('objective_trace_'):-len('.csv')]
        # Timestamp is the last part (yyyymmdd_hhmmss)
        parts = stem.rsplit('_', 2)
        if len(parts) >= 3:
            exp_name = '_'.join(parts[:-2])
        else:
            exp_name = stem
        rows = []
        with open(path, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                rows.append({
                    't':           _f(r.get('sim_time_s', 0)),
                    'jct':         _i(r.get('junction_id', -1)),
                    'mode':        (r.get('mode') or '').strip(),
                    'decision':    (r.get('decision') or '').strip(),
                    'reason':      (r.get('reason') or '').strip(),
                    'bus_eta_s':   _f(r.get('bus_eta_s', '')),
                    'bus_benefit': _f(r.get('delay_base_pax_s', '')),    # bus benefit pax-s
                    'side_cost':   _f(r.get('delay_with_strategy_pax_s', '')),  # side cost pax-s
                    'net_saved':   _f(r.get('delay_saved_pax_s', '')),
                    'opt_ge_s':    _f(r.get('opt_ge_s', '')),
                    'opt_bp_s':    _f(r.get('opt_bp_s', '')),
                    'note':        (r.get('note') or '').strip(),
                })
        out[exp_name] = rows
    return out


def _summarise_trace(rows):
    """Return summary dict from objective trace rows."""
    s = {
        'ge_action': 0, 'ge_skip': 0,
        'ins_action': 0, 'ins_skip': 0,
        'reasons': {},
        'benefit_action': [], 'cost_action': [],
        'benefit_skip':   [], 'cost_skip':   [],
    }
    for r in rows:
        mode = r['mode']
        dec  = r['decision']
        reason = r['reason'] or 'unknown'
        if mode == 'GE' and dec == 'ACTION':
            s['ge_action'] += 1
            s['benefit_action'].append(r['bus_benefit'])
            s['cost_action'].append(r['side_cost'])
        elif mode == 'GE':
            s['ge_skip'] += 1
            s['benefit_skip'].append(r['bus_benefit'])
            s['cost_skip'].append(r['side_cost'])
        elif mode == 'INS' and dec == 'ACTION':
            s['ins_action'] += 1
            s['benefit_action'].append(r['bus_benefit'])
            s['cost_action'].append(r['side_cost'])
        elif mode == 'INS':
            s['ins_skip'] += 1
            s['benefit_skip'].append(r['bus_benefit'])
            s['cost_skip'].append(r['side_cost'])
        s['reasons'][reason] = s['reasons'].get(reason, 0) + 1
    return s


def _p95(vals):
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return 0.0
    idx = int(round(0.95 * (len(vals) - 1)))
    return float(vals[max(0, min(idx, len(vals) - 1))])


def _load_offset_logs(log_dir):
    """Return dict: {experiment_name: [rows...]} from green_offsets_*.csv."""
    out = {}
    for path in glob.glob(os.path.join(log_dir, 'green_offsets_*.csv')):
        base = os.path.basename(path)
        stem = base[len('green_offsets_'):-len('.csv')]
        parts = stem.rsplit('_', 2)
        if len(parts) >= 3:
            exp_name = '_'.join(parts[:-2])
        else:
            exp_name = stem

        rows = []
        with open(path, newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                rows.append({
                    't': _f(r.get('sim_time_s', '')),
                    'offset_s': _f(r.get('offset_s', '')),
                    'quality': (r.get('quality') or 'unknown').strip(),
                    'veh_id': _i(r.get('veh_id', '')),
                    'from_jct': _i(r.get('from_jct', '')),
                    'to_jct': _i(r.get('to_jct', '')),
                    'dist_m': _f(r.get('dist_m', '')),
                    'speed_est_ms': _f(r.get('speed_est_ms', '')),
                })
        out[exp_name] = rows
    return out


def _summarise_offsets(offset_logs, experiments):
  out = {}
  _corr_quality = {'aligned', 'misaligned'}
  for exp in experiments:
    rows = offset_logs.get(exp, [])
    if not rows:
      out[exp] = {
        'count': 0,
        'corr_count': 0,
        'mean_abs_offset_s': 0.0,
        'p95_abs_offset_s': 0.0,
        'quality_counts': {},
      }
      continue
    corr_rows = [
      r for r in rows
      if (r.get('quality') or '').strip() in _corr_quality
    ]
    abs_vals = [abs(_f(r.get('offset_s', 0.0))) for r in corr_rows]
    q = {}
    for r in rows:
      k = (r.get('quality') or 'unknown').strip() or 'unknown'
      q[k] = q.get(k, 0) + 1
    out[exp] = {
      'count': len(rows),
      'corr_count': len(corr_rows),
      'mean_abs_offset_s': (sum(abs_vals) / len(abs_vals)) if abs_vals else 0.0,
      'p95_abs_offset_s': _p95(abs_vals),
      'quality_counts': q,
    }
  return out


# ── main ───────────────────────────────────────────────────────────────────────
batch_rows = _load_batch(_batch_csv)
batch_agg  = _agg_by_experiment(batch_rows)
obj_traces = _load_obj_traces(_log_dir)
offset_logs = _load_offset_logs(_log_dir)

# Order experiments
all_exps = [e for e in EXP_ORDER if e in batch_agg or e in obj_traces]
all_exps += sorted(set(list(batch_agg.keys()) + list(obj_traces.keys())) - set(all_exps))

# Build trace summaries
trace_summaries = {exp: _summarise_trace(obj_traces.get(exp, []))
                   for exp in all_exps}
offset_summaries = _summarise_offsets(offset_logs, all_exps)

# ── build JSON data blocks for JavaScript ─────────────────────────────────────
def _bv(exp, col):
    """Get numeric metric for an experiment."""
    row = batch_agg.get(exp, {})
    return _f(row.get(col, ''), 0.0)


# Panel 1: key performance metrics
def _bar_series(metric_col, label, experiments):
    vals   = [_bv(e, metric_col) for e in experiments]
    colors = [EXP_COLOURS.get(e, DEFAULT_COLOUR) for e in experiments]
    return {
        'type': 'bar',
        'name': label,
        'x': experiments,
        'y': vals,
        'marker': {'color': colors},
        'text': [f'{v:.2f}' if abs(v) >= 0.01 else '0' for v in vals],
        'textposition': 'outside',
    }


def _metric_panels(experiments):
    metrics = [
        ('stats_AvgBusTT_s',        'Avg Bus Travel Time (s/trip)',  'Bus Performance'),
        ('stats_AvgBusPassDelay_s',  'Avg Bus Pax Delay (s/pax)',     'Bus Performance'),
        ('stats_AvgPassDelay_s',     'Avg All-Mode Pax Delay (s/pax)','Network Impact'),
        ('stats_AvgCarPassDelay_s',  'Avg Car Pax Delay (s/pax)',     'Network Impact'),
        ('stats_Net_AvgSpeed_kmh',   'Network Avg Speed (km/h)',      'Network Impact'),
        ('stats_TotalPassDelay_hrs', 'Total Pax Delay (hrs)',         'Totals'),
        ('stats_BusTotalTT_hrs',     'Bus Total TT (hrs)',            'Totals'),
        ('stats_Objective_PaxPerDelayHr', 'Objective (pax/delay-hr)', 'Objective'),
    ]
    panels = []
    for col, lbl, group in metrics:
        vals   = [_bv(e, col) for e in experiments]
        colors = [EXP_COLOURS.get(e, DEFAULT_COLOUR) for e in experiments]
        panels.append({
            'label': lbl,
            'group': group,
            'experiments': experiments,
            'vals': vals,
            'colors': colors,
        })
    return panels


metric_panels = _metric_panels(all_exps)

# Panel 2: TSP action breakdown per experiment
def _tsp_panels(experiments, summaries, batch_agg):
    panels = []
    for exp in experiments:
        sm = summaries.get(exp, {})
        b  = batch_agg.get(exp, {})
        natural  = _f(b.get('stats_TSP_NaturalGreen', 0))
        over_max = sm.get('reasons', {}).get('over_max_extension', 0)
        eta_hor  = sm.get('reasons', {}).get('eta_horizon', 0)
        headroom = sm.get('reasons', {}).get('insufficient_cycle_headroom', 0)
        no_saving= sm.get('reasons', {}).get('no_delay_saving', 0)
        nat_fut  = sm.get('reasons', {}).get('natural_green_future_bus_phase', 0)
        nat_cur  = sm.get('reasons', {}).get('natural_green_current_phase', 0)
        ge_act   = sm.get('ge_action', 0)
        ins_act  = sm.get('ins_action', 0)
        trivial  = sm.get('reasons', {}).get('not_optimal', 0) + sm.get('reasons', {}).get('not_optimal_too_short', 0)
        imp_ub   = sm.get('reasons', {}).get('impractical_upper_bound', 0)
        panels.append({
            'exp': exp,
            'natural_cur': nat_cur + natural,
            'natural_fut': nat_fut,
            'ge_action': ge_act,
            'ins_action': ins_act,
            'over_max': over_max,
            'eta_horizon': eta_hor,
            'insufficient_headroom': headroom,
            'no_delay_saving': no_saving,
            'trivial': trivial + imp_ub,
        })
    return panels


tsp_panels = _tsp_panels(all_exps, trace_summaries, batch_agg)

# Panel 3: benefit vs cost scatter (GE evaluations)
def _benefit_cost_scatter(experiments, obj_traces):
    series = []
    for exp in experiments:
        rows = obj_traces.get(exp, [])
        ge_rows = [r for r in rows if r['mode'] == 'GE' and r['bus_benefit'] > 0]
        if not ge_rows:
            continue
        for dec, symbol, opacity in [('ACTION', 'circle', 0.85), ('SKIP', 'x', 0.45)]:
            pts = [r for r in ge_rows if r['decision'] == dec]
            if not pts:
                continue
            series.append({
                'type': 'scatter',
                'mode': 'markers',
                'name': f'{exp} {dec}',
                'x': [r['bus_benefit'] for r in pts],
                'y': [r['side_cost'] for r in pts],
                'marker': {
                    'color': EXP_COLOURS.get(exp, DEFAULT_COLOUR),
                    'symbol': symbol,
                    'size': 7,
                    'opacity': opacity,
                    'line': {'width': 0.5, 'color': 'white'},
                },
                'text': [f"t={r['t']:.0f}s jct={r['jct']} reason={r['reason']}"
                         for r in pts],
                'hovertemplate': (
                    '<b>%{fullData.name}</b><br>'
                    'Bus benefit: %{x:.0f} pax-s<br>'
                    'Side cost: %{y:.0f} pax-s<br>'
                    '%{text}<extra></extra>'
                ),
            })
    return series


scatter_series = _benefit_cost_scatter(all_exps, obj_traces)

# ── compute percentage improvements vs NO_TSP ─────────────────────────────────
def _pct_change(new, base, lower_is_better=True):
    if abs(base) < 1e-9:
        return 0.0
    delta = (new - base) / abs(base) * 100.0
    return -delta if lower_is_better else delta


no_tsp = batch_agg.get('NO_TSP', {})
improvements = {}
for exp in all_exps:
    if exp == 'NO_TSP':
        improvements[exp] = {}
        continue
    row = batch_agg.get(exp, {})
    improvements[exp] = {
        'bus_delay':   _pct_change(_f(row.get('stats_AvgBusPassDelay_s', 0)),
                                   _f(no_tsp.get('stats_AvgBusPassDelay_s', 0)),
                                   lower_is_better=True),
        'all_delay':   _pct_change(_f(row.get('stats_AvgPassDelay_s', 0)),
                                   _f(no_tsp.get('stats_AvgPassDelay_s', 0)),
                                   lower_is_better=True),
        'bus_tt':      _pct_change(_f(row.get('stats_AvgBusTT_s', 0)),
                                   _f(no_tsp.get('stats_AvgBusTT_s', 0)),
                                   lower_is_better=True),
        'speed':       _pct_change(_f(row.get('stats_Net_AvgSpeed_kmh', 0)),
                                   _f(no_tsp.get('stats_Net_AvgSpeed_kmh', 0)),
                                   lower_is_better=False),
        'total_delay': _pct_change(_f(row.get('stats_TotalPassDelay_hrs', 0)),
                                   _f(no_tsp.get('stats_TotalPassDelay_hrs', 0)),
                                   lower_is_better=True),
    }

# ── skip reason analysis ───────────────────────────────────────────────────────
def _reason_bars(experiments, summaries):
    """Stacked bar for GE skip reasons per experiment."""
    reason_order = [
        ('natural_green_current_phase', 'Natural green (bus phase)', '#4CAF50'),
        ('natural_green_future_bus_phase', 'Natural green (future)', '#8BC34A'),
        ('no_delay_saving',             'Side cost > bus benefit',  '#F44336'),
        ('over_max_extension',          'Over max GE cap',          '#FF9800'),
        ('eta_horizon',                 'ETA too far (horizon)',     '#9C27B0'),
        ('insufficient_cycle_headroom', 'Insufficient headroom',    '#FF5722'),
        ('impractical_upper_bound',     'Impractical bound',        '#795548'),
        ('not_optimal',                 'Not optimal (trivial)',     '#9E9E9E'),
        ('ge_action_granted',           'GE GRANTED ✓',             '#1565C0'),
        ('ins_action_granted',          'INS GRANTED ✓',            '#0288D1'),
    ]
    traces = []
    for key, label, color in reason_order:
        vals = []
        for exp in experiments:
            sm = summaries.get(exp, {})
            if key == 'ge_action_granted':
                vals.append(sm.get('ge_action', 0))
            elif key == 'ins_action_granted':
                vals.append(sm.get('ins_action', 0))
            else:
                vals.append(sm.get('reasons', {}).get(key, 0))
        if any(v > 0 for v in vals):
            traces.append({
                'type': 'bar',
                'name': label,
                'x': experiments,
                'y': vals,
                'marker': {'color': color},
                'hovertemplate': f'<b>{label}</b><br>Count: %{{y}}<extra></extra>',
            })
    return traces


reason_bars = _reason_bars(all_exps, trace_summaries)

# ── build JSON for JS ──────────────────────────────────────────────────────────
_js_data = json.dumps({
    'experiments':    all_exps,
    'exp_colours':    {e: EXP_COLOURS.get(e, DEFAULT_COLOUR) for e in all_exps},
    'metrics':        metric_panels,
    'tsp_breakdown':  tsp_panels,
    'improvements':   improvements,
    'scatter_series': scatter_series,
    'reason_bars':    reason_bars,
    'offset_logs':    offset_logs,
    'offset_summary': offset_summaries,
    'batch_agg':      {e: {k: v for k, v in d.items() if not k.startswith('run_')}
                       for e, d in batch_agg.items()},
}, indent=2)

# ── HTML template ──────────────────────────────────────────────────────────────
html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Strategy Comparison — NO_TSP vs GE vs INS</title>
  <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
  <style>
    :root {
      --bg:     #f0f4f8;
      --panel:  #ffffff;
      --ink:    #102236;
      --muted:  #5b6b7d;
      --line:   #d8e1ea;
      --accent: #1f6feb;
      --ok:     #1b8f3e;
      --warn:   #d97706;
      --bad:    #c0392b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: "Segoe UI", Tahoma, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    .wrap { max-width: 1400px; margin: 0 auto; padding: 18px; }
    h1 { font-size: 1.4rem; font-weight: 700; margin-bottom: 6px; }
    .subtitle { color: var(--muted); font-size: 0.875rem; margin-bottom: 18px; }
    .section-title {
      font-size: 1rem; font-weight: 600; margin: 22px 0 10px;
      padding-bottom: 4px; border-bottom: 2px solid var(--line);
      color: var(--accent);
    }
    .card {
      background: var(--panel);
      border-radius: 10px;
      box-shadow: 0 2px 8px rgba(0,0,0,.07);
      padding: 16px;
      margin-bottom: 18px;
    }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }
    @media (max-width: 900px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px,1fr)); gap: 12px; }
    .kpi-card {
      background: var(--bg);
      border-radius: 8px;
      padding: 12px 16px;
      border-left: 4px solid var(--accent);
    }
    .kpi-card.better { border-left-color: var(--ok); }
    .kpi-card.worse  { border-left-color: var(--bad); }
    .kpi-label { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; }
    .kpi-val   { font-size: 1.6rem; font-weight: 700; margin: 2px 0; }
    .kpi-pct   { font-size: 0.85rem; font-weight: 600; }
    .kpi-pct.better { color: var(--ok); }
    .kpi-pct.worse  { color: var(--bad); }
    .note-box {
      background: #fffbe6;
      border: 1px solid #ffe58f;
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 16px;
      font-size: 0.875rem;
      line-height: 1.5;
    }
    .note-box strong { color: #7c5c00; }
    .exp-selector {
      display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px;
    }
    .exp-btn {
      padding: 5px 14px; border-radius: 20px; border: 2px solid #ccc;
      cursor: pointer; font-size: 0.8rem; font-weight: 600;
      background: #fff; transition: all .15s;
    }
    .exp-btn.active { color: #fff; border-color: transparent; }
    #plotDiv1, #plotDiv2, #plotDiv3, #plotDiv4, #plotDiv5, #plotDiv6, #plotDiv7 {
      width: 100%; min-height: 380px;
    }
  </style>
</head>
<body>
<div class="wrap">
  <h1>Strategy Comparison: NO_TSP vs HARMONY (GE &amp; Phase Insertion)</h1>
  <div class="subtitle">
    Comparing simulation outcomes and TSP decision analysis across scenarios.
    Bus benefit = passenger-delay avoided by catching the green.
    Side cost = incremental delay imposed on other traffic by extending green.
  </div>

  <div id="diagNote" class="note-box">
    <strong>Diagnostic:</strong> Loading data...
  </div>

  <!-- Experiment selector -->
  <div class="exp-selector" id="expSelector"></div>

  <!-- KPI comparison cards -->
  <div class="section-title">Key Performance Metrics vs NO_TSP</div>
  <div id="kpiCards" class="kpi-grid"></div>

  <!-- Panel 1: Bar charts for each metric -->
  <div class="section-title">Performance Metric Bar Charts</div>
  <div class="card"><div id="plotDiv1"></div></div>

  <!-- Panel 2: TSP action breakdown -->
  <div class="section-title">TSP Decision Breakdown (GE &amp; Phase Insertion)</div>
  <div class="note-box" id="tspNote" style="display:none"></div>
  <div class="card"><div id="plotDiv2"></div></div>

  <!-- Panel 3: Benefit vs Cost scatter -->
  <div class="section-title">GE Evaluation: Bus Benefit vs Side-Street Cost</div>
  <div class="card" style="font-size:0.85rem;color:var(--muted);padding-bottom:8px;">
    Each point is one GE evaluation. <em>Above the diagonal</em> = GE saves more than it costs →
    action should fire. <em>Below</em> = cost exceeds benefit → action correctly skipped.
    Points should ideally cluster above-diagonal for HARMONY strategies.
  </div>
  <div class="card"><div id="plotDiv3"></div></div>

  <!-- Panel 4: Skip reasons by experiment -->
  <div class="section-title">Why GE / INS Were Skipped</div>
  <div class="card"><div id="plotDiv4"></div></div>

  <!-- Panel 5: Time-series pax delay delta (if queue snapshot available) -->
  <div class="section-title">Bus Delay Timeline (per Intersection)</div>
  <div class="card"><div id="plotDiv5"></div></div>

  <!-- Panel 6: Offset correction activity -->
  <div class="section-title">Offset Correction Activity (sim time vs offset)</div>
  <div class="card" style="font-size:0.85rem;color:var(--muted);padding-bottom:8px;">
    Positive offset means the downstream green starts before bus arrival.
    Negative offset means the bus arrives before green. Values near zero indicate better alignment.
  </div>
  <div class="card"><div id="plotDiv6"></div></div>

  <!-- Panel 7: Offset alignment quality -->
  <div class="section-title">Offset Alignment Quality and Magnitude</div>
  <div class="card"><div id="plotDiv7"></div></div>

</div>

<script>
const DATA = """ + _js_data + """;

// ── helpers ────────────────────────────────────────────────────────────────────
const fmt1 = v => (v == null || isNaN(v)) ? '—' : v.toFixed(1);
const fmt2 = v => (v == null || isNaN(v)) ? '—' : v.toFixed(2);
const fmtPct = v => (v == null || isNaN(v)) ? '' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
const colours = DATA.exp_colours;
const exps = DATA.experiments;

// ── diagnostic note ────────────────────────────────────────────────────────────
(function buildDiag() {
  const noTsp = DATA.batch_agg['NO_TSP'] || {};
  const lines = [];
  exps.forEach(e => {
    if (e === 'NO_TSP') return;
    const sm = DATA.tsp_breakdown.find(t => t.exp === e) || {};
    const geAct = sm.ge_action || 0;
    const insAct = sm.ins_action || 0;
    const noSave = sm.no_delay_saving || 0;
    const natural = (sm.natural_cur || 0) + (sm.natural_fut || 0);
    lines.push(`<strong>${e}</strong>: ${geAct} GE actions, ${insAct} INS actions, ` +
      `${natural.toLocaleString()} natural-green passes, ${noSave.toLocaleString()} side-cost exceeded bus benefit`);
  });
  const note = document.getElementById('diagNote');
  if (lines.length === 0) {
    note.innerHTML = '<strong>Note:</strong> Only one experiment loaded — no comparison possible. Run multiple strategies (NO_TSP, HARMONY_INDEP, HARMONY_COORD) to see side-by-side differences.';
  } else {
    const offsetBits = [];
    exps.forEach(e => {
      const os = DATA.offset_summary?.[e] || null;
      if (!os || !(+os.count > 0)) return;
      offsetBits.push(`<strong>${e}</strong> offset logs=${(+os.count).toLocaleString()} (corr=${(+os.corr_count || 0).toLocaleString()}) | corr mean|offset|=${(+os.mean_abs_offset_s).toFixed(2)}s | corr p95|offset|=${(+os.p95_abs_offset_s).toFixed(2)}s`);
    });
    const offsetTxt = offsetBits.length ? ('<br><br><strong>Offset Summary:</strong><br>' + offsetBits.join('<br>')) : '';
    note.innerHTML = '<strong>TSP Actions Summary:</strong><br>' + lines.join('<br>') + offsetTxt;
  }
  // TSP note
  const tspNote = document.getElementById('tspNote');
  const hasActions = exps.some(e => {
    const sm = DATA.tsp_breakdown.find(t => t.exp === e) || {};
    return (sm.ge_action || 0) + (sm.ins_action || 0) > 0;
  });
  if (!hasActions) {
    tspNote.style.display = '';
    tspNote.innerHTML = `<strong>⚠ Zero GE/INS actions in all experiments.</strong> ` +
      `This is caused by the objective function not encoding the bus benefit (avoided red-cycle wait). ` +
      `The fix in intersection_controller.py (split-accounting: bus_benefit = RedDuration × BusOcc; ` +
      `side_cost = ΔObjective) corrects this so GE and INS will fire appropriately in the next simulation run.`;
  }
})();

// ── experiment selector ────────────────────────────────────────────────────────
const sel = document.getElementById('expSelector');
exps.forEach(e => {
  const btn = document.createElement('button');
  btn.className = 'exp-btn active';
  btn.textContent = e;
  btn.style.borderColor = colours[e] || '#9E9E9E';
  btn.style.background  = colours[e] || '#9E9E9E';
  btn.style.color = '#fff';
  btn.onclick = () => {
    btn.classList.toggle('active');
    if (!btn.classList.contains('active')) {
      btn.style.background = '#fff';
      btn.style.color = colours[e] || '#9E9E9E';
    } else {
      btn.style.background = colours[e] || '#9E9E9E';
      btn.style.color = '#fff';
    }
  };
  sel.appendChild(btn);
});

// ── KPI Cards ─────────────────────────────────────────────────────────────────
const kpiDiv = document.getElementById('kpiCards');
const kpiFields = [
  { key: 'bus_delay',   label: 'Bus Pax Delay',   unit: '%',  lower_better: true },
  { key: 'all_delay',   label: 'All-Mode Delay',  unit: '%',  lower_better: true },
  { key: 'bus_tt',      label: 'Bus Travel Time', unit: '%',  lower_better: true },
  { key: 'speed',       label: 'Network Speed',   unit: '%',  lower_better: false },
  { key: 'total_delay', label: 'Total Delay',     unit: '%',  lower_better: true },
];
exps.filter(e => e !== 'NO_TSP').forEach(exp => {
  const impr = DATA.improvements[exp] || {};
  kpiFields.forEach(kf => {
    const pct = impr[kf.key] || 0;
    const better = kf.lower_better ? pct >= 0 : pct >= 0;
    const card = document.createElement('div');
    card.className = 'kpi-card ' + (better ? 'better' : 'worse');
    const bat = DATA.batch_agg[exp] || {};
    let absVal = 0;
    if (kf.key === 'bus_delay')   absVal = +(bat.stats_AvgBusPassDelay_s || 0);
    if (kf.key === 'all_delay')   absVal = +(bat.stats_AvgPassDelay_s || 0);
    if (kf.key === 'bus_tt')      absVal = +(bat.stats_AvgBusTT_s || 0);
    if (kf.key === 'speed')       absVal = +(bat.stats_Net_AvgSpeed_kmh || 0);
    if (kf.key === 'total_delay') absVal = +(bat.stats_TotalPassDelay_hrs || 0);
    card.innerHTML = `
      <div class="kpi-label">${exp} — ${kf.label}</div>
      <div class="kpi-val">${fmt1(absVal)}</div>
      <div class="kpi-pct ${better ? 'better' : 'worse'}">${fmtPct(pct)} vs NO_TSP</div>
    `;
    kpiDiv.appendChild(card);
  });
});

// ── Plot 1: Metric bar charts ──────────────────────────────────────────────────
(function buildMetricPlot() {
  const metrics = DATA.metrics;
  const n = metrics.length;
  const cols = Math.min(n, 4);
  const rows = Math.ceil(n / cols);
  const traces = [];
  const layout = {
    grid: { rows, columns: cols, pattern: 'independent' },
    showlegend: false,
    margin: { t: 60, b: 40, l: 50, r: 20 },
    height: rows * 220,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Segoe UI, Tahoma, sans-serif', size: 11, color: '#102236' },
  };
  metrics.forEach((m, idx) => {
    const axId = idx === 0 ? '' : (idx + 1).toString();
    layout[`xaxis${axId}`] = { title: '', tickfont: { size: 9 } };
    layout[`yaxis${axId}`] = { title: m.label.split('(')[1] ? '(' + m.label.split('(')[1] : '' };
    traces.push({
      type: 'bar',
      x: m.experiments,
      y: m.vals,
      marker: { color: m.colors, opacity: 0.85 },
      text: m.vals.map(v => fmt2(v)),
      textposition: 'outside',
      cliponaxis: false,
      name: m.label,
      xaxis: `x${axId}`,
      yaxis: `y${axId}`,
      hovertemplate: `<b>${m.label}</b><br>%{x}: %{y:.3g}<extra></extra>`,
    });
    layout[`annotations`] = layout.annotations || [];
    // subplots don't support easy title per panel — use annotations
    layout.annotations.push({
      text: `<b>${m.label}</b>`,
      font: { size: 10 },
      showarrow: false,
      x: 0.5,
      y: 1.02,
      xref: `x${axId} domain`,
      yref: `y${axId} domain`,
    });
  });
  Plotly.newPlot('plotDiv1', traces, layout, { responsive: true, displayModeBar: false });
})();

// ── Plot 2: TSP action stacked bar ─────────────────────────────────────────────
(function buildTspPlot() {
  const bkd = DATA.tsp_breakdown;
  const expLabels = bkd.map(b => b.exp);
  const cats = [
    { key: 'ge_action',              label: 'GE Granted ✓',            color: '#1565C0' },
    { key: 'ins_action',             label: 'INS Granted ✓',           color: '#0288D1' },
    { key: 'natural_cur',            label: 'Natural green (cur. phase)',color: '#43A047' },
    { key: 'natural_fut',            label: 'Natural green (future)',   color: '#81C784' },
    { key: 'no_delay_saving',        label: 'Side cost > bus benefit',  color: '#E53935' },
    { key: 'over_max',               label: 'Over max GE cap',          color: '#FB8C00' },
    { key: 'eta_horizon',            label: 'ETA horizon',              color: '#8E24AA' },
    { key: 'insufficient_headroom',  label: 'Insufficient headroom',    color: '#F4511E' },
    { key: 'trivial',                label: 'Trivial / impractical',    color: '#9E9E9E' },
  ];
  const traces = cats.map(c => ({
    type: 'bar',
    name: c.label,
    x: expLabels,
    y: bkd.map(b => b[c.key] || 0),
    marker: { color: c.color, opacity: 0.88 },
    hovertemplate: `<b>${c.label}</b><br>%{x}: %{y:,}<extra></extra>`,
  }));
  const layout = {
    barmode: 'stack',
    height: 380,
    margin: { t: 20, b: 60, l: 60, r: 20 },
    legend: { orientation: 'h', y: -0.25, font: { size: 10 } },
    yaxis: { title: 'Number of evaluations' },
    xaxis: { title: '' },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
  };
  Plotly.newPlot('plotDiv2', traces, layout, { responsive: true, displayModeBar: false });
})();

// ── Plot 3: Benefit vs Cost scatter ───────────────────────────────────────────
(function buildScatter() {
  const traces = DATA.scatter_series;
  // Add diagonal line (y=x) for reference
  if (traces.length > 0) {
    const allX = traces.flatMap(t => t.x).filter(Number.isFinite);
    const maxV = Math.max(...allX, 100);
    traces.unshift({
      type: 'scatter',
      mode: 'lines',
      name: 'Break-even (benefit = cost)',
      x: [0, maxV],
      y: [0, maxV],
      line: { color: '#FF5722', dash: 'dash', width: 1.5 },
      hoverinfo: 'skip',
    });
  }
  const noData = traces.filter(t => t.type === 'scatter' && t.mode === 'markers').length === 0;
  const layout = {
    height: 420,
    margin: { t: 30, b: 70, l: 70, r: 20 },
    xaxis: { title: 'Bus Benefit (pax-s avoided) → higher = more bus passengers saved' },
    yaxis: { title: 'Side Cost (pax-s imposed) → higher = more other traffic delayed' },
    legend: { font: { size: 10 } },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: '#fafbfc',
    annotations: noData ? [{
      text: 'No GE evaluations found in objective trace CSVs.<br>' +
            'Re-run simulation with HARMONY strategy to populate this chart.',
      showarrow: false, x: 0.5, y: 0.5, xref: 'paper', yref: 'paper',
      font: { size: 13, color: '#888' },
    }] : [],
  };
  Plotly.newPlot('plotDiv3', noData ? [] : traces, layout, { responsive: true, displayModeBar: false });
})();

// ── Plot 4: Skip reason bars ───────────────────────────────────────────────────
(function buildReasonBars() {
  const traces = DATA.reason_bars;
  const noData = traces.length === 0;
  const layout = {
    barmode: 'stack',
    height: 360,
    margin: { t: 20, b: 90, l: 70, r: 20 },
    legend: { orientation: 'h', y: -0.38, font: { size: 10 } },
    yaxis: { title: 'Count' },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    annotations: noData ? [{
      text: 'No GE/INS evaluations found in objective trace CSVs.',
      showarrow: false, x: 0.5, y: 0.5, xref: 'paper', yref: 'paper',
      font: { size: 13, color: '#888' },
    }] : [],
  };
  Plotly.newPlot('plotDiv4', noData ? [] : traces, layout, { responsive: true, displayModeBar: false });
})();

// ── Plot 5: Per-intersection bus delay ─────────────────────────────────────────
(function buildInterPlot() {
  const agg = DATA.batch_agg;
  // Per-intersection bus delay if available in agg
  // We show avg bus travel time per experiment as a simple comparison
  const traces = [];
  const metricKey = 'stats_AvgBusTT_s';
  const base = +(agg['NO_TSP'] || {})[metricKey] || 0;
  exps.forEach(exp => {
    const row = agg[exp] || {};
    const val = +(row[metricKey] || 0);
    const delta = val - base;
    traces.push({
      type: 'bar',
      name: exp,
      x: [exp],
      y: [val],
      marker: { color: colours[exp] || DEFAULT_COLOUR, opacity: 0.85 },
      text: [`${fmt1(val)}s (Δ${delta >= 0 ? '+' : ''}${fmt1(delta)})`],
      textposition: 'outside',
      hovertemplate: `<b>${exp}</b><br>Avg Bus TT: %{y:.1f}s<extra></extra>`,
    });
  });
  const layout = {
    height: 280,
    margin: { t: 30, b: 50, l: 70, r: 20 },
    showlegend: false,
    yaxis: { title: 'Avg Bus Travel Time (s/trip)', rangemode: 'tozero' },
    xaxis: { title: '' },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    shapes: base > 0 ? [{
      type: 'line', x0: -0.5, x1: exps.length - 0.5,
      y0: base, y1: base,
      line: { color: '#9E9E9E', dash: 'dot', width: 1.5 },
    }] : [],
    annotations: base > 0 ? [{
      x: exps.length - 0.5, y: base, xanchor: 'right',
      text: 'NO_TSP baseline', showarrow: false,
      font: { size: 10, color: '#9E9E9E' },
    }] : [],
  };
  Plotly.newPlot('plotDiv5', traces, layout, { responsive: true, displayModeBar: false });
})();

// ── Plot 6: Offset activity (sim time vs offset) ─────────────────────────────
(function buildOffsetActivity() {
  const corrQuality = new Set(['aligned', 'misaligned']);
  const traces = [];
  exps.forEach(exp => {
    const rows = (DATA.offset_logs && DATA.offset_logs[exp]) ? DATA.offset_logs[exp] : [];
    const corrRows = rows.filter(r => corrQuality.has((r.quality || '').trim()));
    if (!corrRows.length) return;
    traces.push({
      type: 'scatter',
      mode: 'markers',
      name: exp,
      x: corrRows.map(r => +r.t || 0),
      y: corrRows.map(r => +r.offset_s || 0),
      marker: {
        color: colours[exp] || '#607D8B',
        size: 7,
        opacity: 0.7,
      },
      text: corrRows.map(r => `veh=${r.veh_id} ${r.from_jct}->${r.to_jct} q=${r.quality}`),
      hovertemplate: '<b>%{fullData.name}</b><br>t=%{x:.1f}s<br>offset=%{y:.2f}s<br>%{text}<extra></extra>',
    });
  });

  const noData = traces.length === 0;
  const layout = {
    height: 380,
    margin: { t: 30, b: 60, l: 70, r: 20 },
    xaxis: { title: 'Simulation time (s)' },
    yaxis: { title: 'Offset (s)' },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    shapes: [{
      type: 'line', x0: 0, x1: 1, xref: 'paper', y0: 0, y1: 0,
      line: { color: '#9E9E9E', dash: 'dot', width: 1.2 },
    }],
    annotations: noData ? [{
      text: 'No aligned/misaligned offset-correction rows found. Run coordinated strategy to populate offset diagnostics.',
      showarrow: false, x: 0.5, y: 0.5, xref: 'paper', yref: 'paper',
      font: { size: 13, color: '#888' },
    }] : [],
  };
  Plotly.newPlot('plotDiv6', noData ? [] : traces, layout, { responsive: true, displayModeBar: false });
})();

// ── Plot 7: Offset quality + correction |offset| magnitude ──────────────────
(function buildOffsetQuality() {
  const qualityKeys = ['aligned', 'misaligned', 'wave/pre-arm', 'observed', 'unknown'];
  const stacked = [];

  qualityKeys.forEach(qk => {
    const ys = exps.map(exp => {
      const os = DATA.offset_summary?.[exp] || {};
      const qc = os.quality_counts || {};
      return +(qc[qk] || 0);
    });
    if (ys.some(v => v > 0)) {
      stacked.push({
        type: 'bar',
        name: qk,
        x: exps,
        y: ys,
      });
    }
  });

  const meanAbs = {
    type: 'scatter',
    mode: 'lines+markers',
    name: 'mean |offset| (s)',
    x: exps,
    y: exps.map(exp => +(DATA.offset_summary?.[exp]?.mean_abs_offset_s || 0)),
    yaxis: 'y2',
    line: { color: '#1f6feb', width: 2 },
    marker: { size: 6 },
  };

  const p95Abs = {
    type: 'scatter',
    mode: 'lines+markers',
    name: 'p95 |offset| (s)',
    x: exps,
    y: exps.map(exp => +(DATA.offset_summary?.[exp]?.p95_abs_offset_s || 0)),
    yaxis: 'y2',
    line: { color: '#e65100', width: 2, dash: 'dash' },
    marker: { size: 6 },
  };

  const noData = !stacked.length && !exps.some(exp => +(DATA.offset_summary?.[exp]?.count || 0) > 0);
  const traces = noData ? [] : [...stacked, meanAbs, p95Abs];
  const layout = {
    barmode: 'stack',
    height: 400,
    margin: { t: 30, b: 70, l: 60, r: 70 },
    xaxis: { title: '' },
    yaxis: { title: 'Offset event count' },
    yaxis2: {
      title: '|Offset| seconds',
      overlaying: 'y',
      side: 'right',
      rangemode: 'tozero',
    },
    legend: { orientation: 'h', y: -0.25, font: { size: 10 } },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    annotations: noData ? [{
      text: 'No offset-correction records available.',
      showarrow: false, x: 0.5, y: 0.5, xref: 'paper', yref: 'paper',
      font: { size: 13, color: '#888' },
    }] : [],
  };
  Plotly.newPlot('plotDiv7', traces, layout, { responsive: true, displayModeBar: false });
})();
</script>
</body>
</html>
"""

with open(_out_html, 'w', encoding='utf-8') as f:
    f.write(html)

print(f"[plot_strategy_comparison] Written: {_out_html}")
