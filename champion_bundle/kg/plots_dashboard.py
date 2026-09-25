"""
plots_dashboard.py
==================
Builds a self-contained HTML dashboard (plots_dashboard.html) that embeds:

  • Summary metrics bar-chart (passenger delay, bus delay, TSP detections, prearm success)
  • Per-experiment tabbed view with all existing PNG plots from logs/
    (detection map, OSM overlay, green-wave, space-time diagram)
  • A comparison table drawn from batch_results.csv

Run from the project root:
    python plots_dashboard.py

Or with a custom logs directory:
    python plots_dashboard.py --logs logs --batch batch_results.csv --out plots_dashboard.html
"""

import argparse
import base64
import glob
import os
import re
import sys
import csv

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
LOG_DIR     = os.path.join(SCRIPT_DIR, "logs")
BATCH_CSV   = os.path.join(SCRIPT_DIR, "batch_results.csv")
OUT_HTML    = os.path.join(SCRIPT_DIR, "plots_dashboard.html")

# Display order for experiments (others appended alphabetically after these)
EXP_ORDER = [
    "NORMAL",
    "HARMONY_COORD",
    "HARMONY_COORD_SHOCKWAVE",
    "HARMONY_COORD_ADAPTIVE",
    "HARMONY_INDEP",
    "REWARD_TSP_COORD",
    "REWARD_TSP_INDEP",
    "DYNAOPAC_COORD",
    "DYNAOPAC_INDEP",
    "DYNAOPAC_COORD_SHOCKWAVE",
]

# Colour palette per experiment
EXP_COLOURS = {
    "NORMAL":                    "#FF9800",
    "HARMONY_COORD":             "#2196F3",
    "HARMONY_COORD_SHOCKWAVE":   "#00BCD4",
    "HARMONY_COORD_ADAPTIVE":    "#3F51B5",
    "HARMONY_INDEP":             "#9C27B0",
    "REWARD_TSP_COORD":          "#4CAF50",
    "REWARD_TSP_INDEP":          "#8BC34A",
    "DYNAOPAC_COORD":            "#F44336",
    "DYNAOPAC_INDEP":            "#E91E63",
    "DYNAOPAC_COORD_SHOCKWAVE":  "#FF5722",
}
DEFAULT_COLOUR = "#9E9E9E"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64(path: str) -> str:
    """Return a base64-encoded data URI for the given image path."""
    if not path or not os.path.isfile(path):
        return ""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg",
            "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(ext, "image/png")
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"


def _find_latest(log_dir: str, pattern: str) -> str | None:
    """Return the most recently dated file matching a glob pattern."""
    matches = sorted(glob.glob(os.path.join(log_dir, pattern)))
    return matches[-1] if matches else None


def _exp_from_filename(name: str) -> str | None:
    """
    Extract experiment name from filenames like:
        detection_points_HARMONY_COORD_20260428_111508.png
        detection_points_HARMONY_COORD_20260428_111508_spacetime.png
    Returns the experiment name (e.g. 'HARMONY_COORD') or None.
    """
    m = re.match(r"detection_points_(.+)_\d{8}_\d{6}(?:_\w+)?\.png$", name)
    return m.group(1) if m else None


def _gather_plots(log_dir: str) -> dict:
    """
    Collect all PNG plots in log_dir, grouped by experiment name.
    Returns {exp_name: {kind: path}} where kind is one of:
        'map', 'osm', 'green_wave', 'spacetime'
    Only the most recent file is kept per (exp, kind) pair.
    """
    result: dict = {}
    for png in sorted(glob.glob(os.path.join(log_dir, "detection_points_*.png"))):
        base = os.path.basename(png)
        exp = _exp_from_filename(base)
        if exp is None:
            continue
        if "_spacetime" in base:
            kind = "spacetime"
        elif "_green_wave" in base:
            kind = "green_wave"
        elif "_osm" in base:
            kind = "osm"
        else:
            kind = "map"
        result.setdefault(exp, {})[kind] = png   # overwritten by later (newer) files
    return result


def _load_batch(batch_csv: str) -> list[dict]:
    """Load batch_results.csv; return list of row dicts."""
    if not os.path.isfile(batch_csv):
        return []
    rows = []
    with open(batch_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def _safe_float(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=0):
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Summary comparison chart (inline SVG bar chart using JavaScript + Canvas)
# ---------------------------------------------------------------------------

def _build_metrics_js(batch_rows: list[dict], ordered_exps: list[str]) -> str:
    """Build JavaScript data arrays for the metrics bar charts."""
    row_by_exp = {}
    for r in batch_rows:
        exp = r.get("run_experiment", "")
        if exp and exp not in row_by_exp:
            row_by_exp[exp] = r

    labels, colours = [], []
    total_delay, bus_delay, prearm_fired, prearm_success, detections = [], [], [], [], []
    natural_green = []

    for exp in ordered_exps:
        if exp not in row_by_exp:
            continue
        r = row_by_exp[exp]
        labels.append(exp)
        colours.append(EXP_COLOURS.get(exp, DEFAULT_COLOUR))
        total_delay.append(_safe_float(r.get("stats_TotalPassDelay_hrs"), 0))
        bus_delay.append(_safe_float(r.get("stats_SimBusDelay_pax_s"), 0) / 3600.0)
        prearm_fired.append(_safe_int(r.get("stats_Prearm_Fired")))
        prearm_success.append(_safe_int(r.get("stats_Prearm_Success")))
        detections.append(_safe_int(r.get("stats_TSP_Detections")))
        natural_green.append(_safe_int(r.get("stats_TSP_NaturalGreen")))

    return f"""
const LABELS      = {labels!r};
const COLOURS     = {colours!r};
const TOTAL_DELAY = {total_delay!r};
const BUS_DELAY   = {bus_delay!r};
const PREARM_FIRED    = {prearm_fired!r};
const PREARM_SUCCESS  = {prearm_success!r};
const DETECTIONS  = {detections!r};
const NAT_GREEN   = {natural_green!r};
"""


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def _img_tag(path: str, alt: str, style: str = "") -> str:
    uri = _b64(path)
    if not uri:
        return f'<p class="no-data">Plot not found: {os.path.basename(path or "?")}</p>'
    return f'<img src="{uri}" alt="{alt}" style="max-width:100%;height:auto;{style}">'


def build_html(log_dir: str, batch_csv: str) -> str:
    plots     = _gather_plots(log_dir)
    batch     = _load_batch(batch_csv)

    # Determine display order
    all_exps  = list(plots.keys())
    ordered   = [e for e in EXP_ORDER if e in all_exps]
    ordered  += sorted(e for e in all_exps if e not in ordered)

    metrics_js = _build_metrics_js(batch, ordered)

    # Build per-experiment batch metrics table rows
    row_by_exp = {}
    for r in batch:
        exp = r.get("run_experiment", "")
        if exp and exp not in row_by_exp:
            row_by_exp[exp] = r

    def _td(val, fmt=None, na="—"):
        if val is None or val == "":
            return f"<td>{na}</td>"
        if fmt:
            try:
                return f"<td>{fmt % float(val)}</td>"
            except (TypeError, ValueError):
                return f"<td>{na}</td>"
        return f"<td>{val}</td>"

    table_rows_html = ""
    for exp in ordered:
        r = row_by_exp.get(exp, {})
        col = EXP_COLOURS.get(exp, DEFAULT_COLOUR)
        table_rows_html += f"""
        <tr>
          <td><span class="exp-dot" style="background:{col}"></span>{exp}</td>
          {_td(r.get('stats_TotalPassDelay_hrs'),   '%.1f')}
          {_td(r.get('stats_MainPassDelay_hrs'),    '%.1f')}
          {_td(r.get('stats_SidePassDelay_hrs'),    '%.1f')}
          {_td(r.get('stats_SimBusDelay_pax_s'),    '%.0f')}
          {_td(r.get('stats_TSP_Detections'),       '%.0f')}
          {_td(r.get('stats_TSP_NaturalGreen'),     '%.0f')}
          {_td(r.get('stats_Prearm_Fired'),         '%.0f')}
          {_td(r.get('stats_Prearm_Success'),       '%.0f')}
          {_td(r.get('run_elapsed_s'),              '%.0f')}
        </tr>"""

    # Build experiment tab buttons
    tab_btns = ""
    tab_panels = ""
    for i, exp in enumerate(ordered):
        active_cls = "active" if i == 0 else ""
        col = EXP_COLOURS.get(exp, DEFAULT_COLOUR)
        tab_btns += f'<button class="tab-btn {active_cls}" onclick="showExp(\'{exp}\')" id="btn-{exp}" style="border-bottom-color:{col}">{exp}</button>\n'

        kinds = plots.get(exp, {})
        imgs_html = ""
        plot_defs = [
            ("map",        "Detection Map"),
            ("osm",        "OSM Overlay"),
            ("green_wave", "Green Wave"),
            ("spacetime",  "Space-Time Diagram"),
        ]
        for kind, label in plot_defs:
            p = kinds.get(kind)
            imgs_html += f"""
            <div class="plot-card">
              <h3 class="plot-title">{label}</h3>
              {_img_tag(p, f'{exp} — {label}')}
            </div>"""

        # Per-exp metrics mini-table
        r = row_by_exp.get(exp, {})
        def _kv(k, v, unit=""):
            return f'<div class="kv"><span class="kk">{k}</span><span class="kv-val">{v}{unit}</span></div>'

        def _fv(key, fmt="%.1f", unit=""):
            raw = r.get(key)
            if raw is None or raw == "":
                return "—"
            try:
                return fmt % float(raw) + unit
            except (TypeError, ValueError):
                return "—"

        mini = f"""
        <div class="mini-metrics">
          {_kv("Total pass. delay", _fv("stats_TotalPassDelay_hrs"), " hrs")}
          {_kv("Main-st delay",     _fv("stats_MainPassDelay_hrs"),  " hrs")}
          {_kv("Bus delay",         _fv("stats_SimBusDelay_pax_s", "%.0f"), " pax·s")}
          {_kv("TSP detections",    _fv("stats_TSP_Detections",     "%.0f"))}
          {_kv("Natural greens",    _fv("stats_TSP_NaturalGreen",   "%.0f"))}
          {_kv("Prearm fired",      _fv("stats_Prearm_Fired",       "%.0f"))}
          {_kv("Prearm success",    _fv("stats_Prearm_Success",     "%.0f"))}
          {_kv("Elapsed",           _fv("run_elapsed_s", "%.0f"),   " s")}
        </div>"""

        disp = "block" if i == 0 else "none"
        tab_panels += f"""
        <div class="tab-panel" id="panel-{exp}" style="display:{disp}">
          <h2 style="color:{col}">{exp}</h2>
          {mini}
          <div class="plot-grid">
            {imgs_html}
          </div>
        </div>"""

    # ── Final HTML ─────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Logan Road TSP — Plots Dashboard</title>
<style>
  :root {{
    --bg:      #0d0d1e;
    --bg2:     #13132b;
    --card:    #1a1a3a;
    --border:  #2a2a55;
    --text:    #cccce8;
    --muted:   #8888aa;
    --accent:  #29b6f6;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', sans-serif; font-size: 14px; }}
  h1   {{ font-size: 1.5rem; color: var(--accent); padding: 18px 24px 8px; }}
  h2   {{ font-size: 1.15rem; margin-bottom: 12px; }}
  h3.plot-title {{ font-size: 0.9rem; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .subtitle {{ color: var(--muted); font-size: 0.85rem; padding: 0 24px 16px; }}

  /* ── Navigation ─────────────────────────────── */
  .nav {{ display: flex; background: var(--bg2); border-bottom: 1px solid var(--border);
          overflow-x: auto; padding: 0 24px; gap: 2px; }}
  .nav a {{ color: var(--muted); text-decoration: none; padding: 10px 16px;
             border-bottom: 2px solid transparent; font-size: 0.85rem; white-space: nowrap; }}
  .nav a:hover, .nav a.active {{ color: var(--accent); border-bottom-color: var(--accent); }}

  /* ── Sections ───────────────────────────────── */
  .section {{ padding: 20px 24px; display: none; }}
  .section.active {{ display: block; }}

  /* ── Summary charts ─────────────────────────── */
  .chart-wrap {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px;
                 padding: 16px; margin-bottom: 18px; overflow-x: auto; }}
  canvas {{ display: block; max-width: 100%; }}

  /* ── Comparison table ───────────────────────── */
  .tbl-wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; }}
  th {{ background: var(--bg2); color: var(--muted); padding: 8px 10px; text-align: right;
        border: 1px solid var(--border); white-space: nowrap; }}
  th:first-child {{ text-align: left; }}
  td {{ padding: 7px 10px; text-align: right; border: 1px solid var(--border); color: var(--text); }}
  td:first-child {{ text-align: left; white-space: nowrap; }}
  tr:nth-child(even) td {{ background: var(--bg2); }}
  .exp-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%;
              margin-right: 6px; vertical-align: middle; }}

  /* ── Experiment tabs ────────────────────────── */
  .tab-bar {{ display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 16px; }}
  .tab-btn {{ background: var(--card); border: 1px solid var(--border);
               border-bottom: 3px solid transparent; color: var(--muted);
               padding: 6px 14px; border-radius: 4px 4px 0 0; cursor: pointer;
               font-size: 0.8rem; transition: color 0.15s; }}
  .tab-btn:hover {{ color: var(--text); }}
  .tab-btn.active {{ color: #fff; background: var(--bg2); }}

  /* ── Mini metrics ───────────────────────────── */
  .mini-metrics {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }}
  .kv {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px;
          padding: 8px 14px; display: flex; flex-direction: column; min-width: 130px; }}
  .kk  {{ font-size: 0.72rem; color: var(--muted); text-transform: uppercase;
           letter-spacing: 0.04em; margin-bottom: 2px; }}
  .kv-val {{ font-size: 1.1rem; color: var(--text); font-weight: 600; }}

  /* ── Plot grid ──────────────────────────────── */
  .plot-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(460px, 1fr));
                gap: 18px; }}
  .plot-card {{ background: var(--card); border: 1px solid var(--border);
                border-radius: 8px; padding: 14px; }}
  .no-data {{ color: var(--muted); font-style: italic; padding: 20px; text-align: center; }}
</style>
</head>
<body>
<h1>Logan Road TSP — Plots Dashboard</h1>
<p class="subtitle">Generated from <code>batch_results.csv</code> and detection plots in <code>logs/</code></p>

<!-- Navigation -->
<nav class="nav">
  <a href="#" class="active" onclick="showSection('summary', this)">Summary &amp; Metrics</a>
  <a href="#" onclick="showSection('experiments', this)">Per-Experiment Plots</a>
</nav>

<!-- ══════════════════ SUMMARY SECTION ══════════════════ -->
<div class="section active" id="section-summary">
  <h2 style="color:var(--accent);margin-bottom:16px">Summary Metrics</h2>

  <div class="chart-wrap">
    <h3 class="plot-title">Total Passenger Delay (hrs)</h3>
    <canvas id="chart-delay" height="220"></canvas>
  </div>

  <div class="chart-wrap">
    <h3 class="plot-title">Bus Passenger Delay (pax·hrs)</h3>
    <canvas id="chart-bus-delay" height="220"></canvas>
  </div>

  <div class="chart-wrap">
    <h3 class="plot-title">TSP Detections vs Natural Greens</h3>
    <canvas id="chart-detections" height="220"></canvas>
  </div>

  <div class="chart-wrap">
    <h3 class="plot-title">Corridor Coordinator: Pre-arms Fired vs Success</h3>
    <canvas id="chart-prearm" height="220"></canvas>
  </div>

  <h2 style="color:var(--accent);margin:24px 0 12px">Comparison Table</h2>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Experiment</th>
          <th>Total Delay (hrs)</th>
          <th>Main-st (hrs)</th>
          <th>Side-st (hrs)</th>
          <th>Bus Delay (pax·s)</th>
          <th>TSP Detections</th>
          <th>Natural Greens</th>
          <th>Prearm Fired</th>
          <th>Prearm Success</th>
          <th>Elapsed (s)</th>
        </tr>
      </thead>
      <tbody>
        {table_rows_html}
      </tbody>
    </table>
  </div>
</div>

<!-- ══════════════════ EXPERIMENTS SECTION ══════════════════ -->
<div class="section" id="section-experiments">
  <div class="tab-bar">
    {tab_btns}
  </div>
  {tab_panels}
</div>

<!-- ══════════════════ JavaScript ══════════════════ -->
<script>
// ── Navigation ──────────────────────────────────────────
function showSection(id, el) {{
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav a').forEach(a => a.classList.remove('active'));
  document.getElementById('section-' + id).classList.add('active');
  if (el) el.classList.add('active');
  return false;
}}

// ── Experiment tabs ──────────────────────────────────────
function showExp(exp) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const panel = document.getElementById('panel-' + exp);
  if (panel) panel.style.display = 'block';
  const btn = document.getElementById('btn-' + exp);
  if (btn) btn.classList.add('active');
}}

// ── Chart data ───────────────────────────────────────────
{metrics_js}

// ── Minimal canvas bar-chart renderer ────────────────────
function drawBarChart(canvasId, values, labels, colours, yLabel) {{
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.parentElement.clientWidth || 900;
  const H = parseInt(canvas.getAttribute('height')) || 240;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width  = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const PAD_L = 70, PAD_R = 20, PAD_T = 20, PAD_B = 60;
  const cw = W - PAD_L - PAD_R;
  const ch = H - PAD_T - PAD_B;
  const n = values.length;
  if (!n) return;

  const maxVal = Math.max(...values, 1e-9);
  const barW = Math.max(4, cw / n * 0.65);
  const gap  = cw / n;

  // Background
  ctx.fillStyle = '#1a1a3a';
  ctx.fillRect(0, 0, W, H);

  // Grid lines
  ctx.strokeStyle = '#2a2a55';
  ctx.lineWidth = 0.8;
  const nGrid = 5;
  for (let i = 0; i <= nGrid; i++) {{
    const y = PAD_T + ch - (ch * i / nGrid);
    ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(PAD_L + cw, y); ctx.stroke();
    ctx.fillStyle = '#8888aa';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText((maxVal * i / nGrid).toFixed(maxVal < 10 ? 2 : 0), PAD_L - 6, y + 4);
  }}

  // Bars
  for (let i = 0; i < n; i++) {{
    const x = PAD_L + gap * i + (gap - barW) / 2;
    const bh = ch * (values[i] / maxVal);
    const y  = PAD_T + ch - bh;
    ctx.fillStyle = colours[i] || '#888';
    ctx.fillRect(x, y, barW, bh);

    // Value label on bar
    if (values[i] > 0) {{
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(values[i].toFixed(values[i] < 10 ? 2 : 0), x + barW / 2, Math.max(y - 4, PAD_T + 12));
    }}

    // X-axis label (angled)
    ctx.save();
    ctx.translate(x + barW / 2, PAD_T + ch + 8);
    ctx.rotate(-Math.PI / 5);
    ctx.fillStyle = '#cccce8';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(labels[i], 0, 0);
    ctx.restore();
  }}

  // Y-axis label
  ctx.save();
  ctx.translate(16, PAD_T + ch / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = '#8888aa';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(yLabel, 0, 0);
  ctx.restore();
}}

function drawGroupedBarChart(canvasId, vals1, vals2, labels, col1, col2, yLabel, legend1, legend2) {{
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.parentElement.clientWidth || 900;
  const H = parseInt(canvas.getAttribute('height')) || 240;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width  = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const PAD_L = 70, PAD_R = 120, PAD_T = 20, PAD_B = 60;
  const cw = W - PAD_L - PAD_R;
  const ch = H - PAD_T - PAD_B;
  const n = labels.length;
  if (!n) return;

  const allVals = [...vals1, ...vals2];
  const maxVal  = Math.max(...allVals, 1e-9);
  const groupW  = cw / n;
  const barW    = groupW * 0.38;

  ctx.fillStyle = '#1a1a3a';
  ctx.fillRect(0, 0, W, H);

  ctx.strokeStyle = '#2a2a55';
  ctx.lineWidth = 0.8;
  const nGrid = 5;
  for (let i = 0; i <= nGrid; i++) {{
    const y = PAD_T + ch - ch * i / nGrid;
    ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(PAD_L + cw, y); ctx.stroke();
    ctx.fillStyle = '#8888aa';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText((maxVal * i / nGrid).toFixed(0), PAD_L - 6, y + 4);
  }}

  for (let i = 0; i < n; i++) {{
    const gx = PAD_L + groupW * i + groupW * 0.07;

    // Bar 1
    const bh1 = ch * (vals1[i] / maxVal);
    ctx.fillStyle = col1;
    ctx.fillRect(gx, PAD_T + ch - bh1, barW, bh1);

    // Bar 2
    const bh2 = ch * (vals2[i] / maxVal);
    ctx.fillStyle = col2;
    ctx.fillRect(gx + barW + 2, PAD_T + ch - bh2, barW, bh2);

    // X label
    ctx.save();
    ctx.translate(gx + barW, PAD_T + ch + 8);
    ctx.rotate(-Math.PI / 5);
    ctx.fillStyle = '#cccce8';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(labels[i], 0, 0);
    ctx.restore();
  }}

  // Legend
  const lx = W - PAD_R + 10;
  [[col1, legend1], [col2, legend2]].forEach(([c, lbl], li) => {{
    const ly = PAD_T + 20 + li * 20;
    ctx.fillStyle = c;
    ctx.fillRect(lx, ly, 12, 12);
    ctx.fillStyle = '#cccce8';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(lbl, lx + 16, ly + 10);
  }});

  ctx.save();
  ctx.translate(16, PAD_T + ch / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = '#8888aa';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(yLabel, 0, 0);
  ctx.restore();
}}

// ── Draw all charts on load ──────────────────────────────
window.addEventListener('load', function() {{
  drawBarChart('chart-delay',     TOTAL_DELAY, LABELS, COLOURS, 'Delay (hrs)');
  drawBarChart('chart-bus-delay', BUS_DELAY,   LABELS, COLOURS, 'Bus Delay (pax·hrs)');
  drawGroupedBarChart(
    'chart-detections',
    DETECTIONS, NAT_GREEN,
    LABELS,
    '#29b6f6', '#00e676',
    'Count',
    'TSP Detections', 'Natural Greens'
  );
  drawGroupedBarChart(
    'chart-prearm',
    PREARM_FIRED, PREARM_SUCCESS,
    LABELS,
    '#ffb300', '#00e676',
    'Count',
    'Prearm Fired', 'Prearm Success'
  );
}});
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Build plots HTML dashboard")
    ap.add_argument("--logs",  default=LOG_DIR,   help="logs directory")
    ap.add_argument("--batch", default=BATCH_CSV,  help="batch_results.csv path")
    ap.add_argument("--out",   default=OUT_HTML,   help="output HTML path")
    args = ap.parse_args()

    print(f"[plots_dashboard] Gathering plots from: {args.logs}")
    print(f"[plots_dashboard] Reading metrics from: {args.batch}")

    html = build_html(args.logs, args.batch)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[plots_dashboard] Dashboard written to: {args.out}")


if __name__ == "__main__":
    main()
