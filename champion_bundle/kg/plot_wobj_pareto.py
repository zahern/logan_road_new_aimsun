"""
plot_wobj_pareto.py — Pareto-frontier plot for the Z1/Z2 weighted-objective sweep

Reads batch_results.csv (written by batch_runner.append_master_csv, which now
folds in the wobj_* fields collected by collect_run_metrics() section 7 from
each run's logs/weighted_objective_<experiment>_<timestamp>.csv trace) and
plots:

    x = total_weighted_delay        (Z1 — section/mode-weighted pax-second delay)
    y = offset_correction_magnitude (Z2 — |offset-correction error|, clipped)

one point per (WOBJ_ALPHA, WOBJ_BETA) run, with the non-dominated (Pareto)
points highlighted — the frontier of "can't reduce one without worsening the
other" trade-offs across the ALPHA/BETA weight sweep
(EXPERIMENTS WOBJ_SWEEP_* in batch_runner.py).

Usage:
    python plot_wobj_pareto.py
    python plot_wobj_pareto.py batch_results.csv wobj_pareto.html
"""

import os
import csv
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

_batch_csv = os.path.join(SCRIPT_DIR, 'batch_results.csv')
_out_html  = os.path.join(SCRIPT_DIR, 'wobj_pareto.html')

if len(sys.argv) >= 2:
    _batch_csv = sys.argv[1]
if len(sys.argv) >= 3:
    _out_html = sys.argv[2]


def _f(v, d=None):
    try:
        return float(v)
    except Exception:
        return d


def _load_runs(path):
    """Return rows that carry both Pareto-axis metrics, with alpha/beta/exp name."""
    runs = []
    if not os.path.isfile(path):
        return runs
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            z1 = _f(r.get('total_weighted_delay'))
            z2 = _f(r.get('offset_correction_magnitude'))
            if z1 is None or z2 is None:
                continue
            runs.append({
                'name':  (r.get('run_experiment') or '').strip(),
                'seed':  (r.get('run_seed') or '').strip(),
                'alpha': _f(r.get('wobj_alpha'), 0.0),
                'beta':  _f(r.get('wobj_beta'), 0.0),
                'objective': _f(r.get('wobj_objective_total'), 0.0),
                'z1': z1,
                'z2': z2,
            })
    return runs


def _pareto_frontier(runs):
    """Non-dominated points: lower Z1 AND lower Z2 is better (minimisation).

    A point is on the frontier if no other point is at-least-as-good on both
    axes and strictly better on at least one (i.e. nothing dominates it).
    """
    frontier = []
    for i, a in enumerate(runs):
        dominated = False
        for j, b in enumerate(runs):
            if i == j:
                continue
            if (b['z1'] <= a['z1'] and b['z2'] <= a['z2']
                    and (b['z1'] < a['z1'] or b['z2'] < a['z2'])):
                dominated = True
                break
        if not dominated:
            frontier.append(a)
    frontier.sort(key=lambda r: r['z1'])
    return frontier


def _build_html(runs, frontier):
    import json as _json

    frontier_keys = {(r['alpha'], r['beta'], r['z1'], r['z2']) for r in frontier}
    all_pts = [r for r in runs if (r['alpha'], r['beta'], r['z1'], r['z2']) not in frontier_keys]

    def _trace(points, name, colour, size, symbol):
        return {
            "x": [p['z1'] for p in points],
            "y": [p['z2'] for p in points],
            "text": [f"{p['name']} (alpha={p['alpha']:.1f}, beta={p['beta']:.1f}, "
                     f"obj={p['objective']:.1f}, seed={p['seed']})" for p in points],
            "mode": "markers",
            "type": "scatter",
            "name": name,
            "marker": {"color": colour, "size": size, "symbol": symbol,
                       "line": {"color": "#222", "width": 1}},
            "hovertemplate": "%{text}<br>Z1=%{x:.1f} pax·s<br>Z2=%{y:.2f} s<extra></extra>",
        }

    traces = [
        _trace(all_pts, "All sweep runs", "#90A4AE", 9, "circle"),
        _trace(frontier, "Pareto frontier", "#E53935", 13, "diamond"),
    ]
    if frontier:
        traces.append({
            "x": [p['z1'] for p in frontier],
            "y": [p['z2'] for p in frontier],
            "mode": "lines",
            "type": "scatter",
            "name": "Frontier (sorted by Z1)",
            "line": {"color": "#E53935", "width": 1, "dash": "dot"},
            "hoverinfo": "skip",
            "showlegend": False,
        })

    rows_html = "".join(
        f"<tr><td>{r['name']}</td><td>{r['alpha']:.1f}</td><td>{r['beta']:.1f}</td>"
        f"<td>{r['z1']:.1f}</td><td>{r['z2']:.2f}</td><td>{r['objective']:.1f}</td></tr>"
        for r in frontier
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Weighted-objective (Z1/Z2) Pareto frontier — ALPHA/BETA sweep</title>
  <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; color: #222; }}
    h1 {{ font-size: 20px; }}
    p.sub {{ color: #555; max-width: 900px; }}
    table {{ border-collapse: collapse; margin-top: 16px; }}
    th, td {{ border: 1px solid #ccc; padding: 6px 10px; font-size: 13px; text-align: right; }}
    th {{ background: #f5f5f5; }}
    td:first-child, th:first-child {{ text-align: left; }}
  </style>
</head>
<body>
  <h1>Weighted-objective (Z1/Z2) Pareto frontier</h1>
  <p class="sub">
    Each point is one WOBJ_SWEEP_* run (ALPHA/BETA combination from
    batch_runner.WOBJ_SWEEP_ALPHAS &times; WOBJ_SWEEP_BETAS).
    X = total_weighted_delay (Z1, section/mode-weighted passenger delay, pax&middot;s,
    lower is better). Y = offset_correction_magnitude (Z2, |offset-correction error|,
    clipped to DCTSP_OC_MAX_ADJ_S, seconds, lower is better).
    Highlighted points are <b>non-dominated</b> — no other run achieves both a
    lower Z1 and a lower Z2 — i.e. the Pareto frontier of the ALPHA/BETA trade-off.
  </p>
  <div id="pareto" style="width:900px;height:620px;"></div>
  <script>
    Plotly.newPlot('pareto', {_json.dumps(traces)}, {{
      xaxis: {{ title: 'total_weighted_delay  (Z1, pax·s)' }},
      yaxis: {{ title: 'offset_correction_magnitude  (Z2, s)' }},
      hovermode: 'closest',
      legend: {{ orientation: 'h', y: -0.18 }},
      margin: {{ t: 30 }},
    }});
  </script>
  <h2 style="font-size:16px;">Pareto-frontier runs (sorted by Z1)</h2>
  <table>
    <tr><th>experiment</th><th>alpha</th><th>beta</th><th>Z1 (pax&middot;s)</th>
        <th>Z2 (s)</th><th>objective</th></tr>
    {rows_html}
  </table>
</body>
</html>
"""


def main():
    runs = _load_runs(_batch_csv)
    if not runs:
        print(f"[plot_wobj_pareto] No rows with total_weighted_delay/"
              f"offset_correction_magnitude found in {_batch_csv}")
        print("  Run the WOBJ_SWEEP_* experiments first (set "
              "batch_runner.WOBJ_SWEEP_ENABLED = True), then re-run this script.")
        return
    frontier = _pareto_frontier(runs)
    html = _build_html(runs, frontier)
    with open(_out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"[plot_wobj_pareto] {len(runs)} runs, {len(frontier)} on the Pareto frontier")
    for r in frontier:
        print(f"    {r['name']:<28s} alpha={r['alpha']:.1f} beta={r['beta']:.1f} "
              f"Z1={r['z1']:.1f}  Z2={r['z2']:.2f}  obj={r['objective']:.1f}")
    print(f"[plot_wobj_pareto] Written: {_out_html}")


if __name__ == "__main__":
    main()
