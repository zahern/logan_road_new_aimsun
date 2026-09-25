"""
generate_bus_tracking_dashboard.py
===================================
Standalone dashboard for bus position tracking across experiments.
Reads bus_positions_*.csv from logs/ and generates an interactive HTML.

Usage:
    python generate_bus_tracking_dashboard.py
    python generate_bus_tracking_dashboard.py --logs logs --out bus_tracking_dashboard.html
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
OUT_HTML = os.path.join(SCRIPT_DIR, "bus_tracking_dashboard.html")

_HEAVY_JSON_DIR = os.path.join(SCRIPT_DIR, "dashboard_data")

COLORS = [
    "#00e676", "#29b6f6", "#ffb300", "#ff5252", "#ab47bc",
    "#26c6da", "#ff6d00", "#76ff03", "#448aff", "#e91e63",
    "#69f0ae", "#b388ff", "#ffd740", "#40c4ff", "#ff8a80",
    "#a7ffeb", "#ea80fc", "#ffe57f", "#84ffff", "#ff80ab",
]


def _read_bus_tracking_json(path: str) -> list:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_html(all_experiments: dict) -> str:
    """all_experiments: {exp_name: [rows]}"""

    exp_list = sorted(all_experiments.keys())
    all_exp_json = json.dumps(all_experiments, separators=(",", ":"))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bus Tracking Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg: #0d0d1e; --bg2: #13132b; --bg3: #1a1a35;
  --border: #2a2a50; --text: #cccce8; --muted: #7070a0;
  --green: #00e676; --orange: #ffb300; --red: #ff5252;
  --blue: #29b6f6; --purple: #ab47bc;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text);
       font-family: 'Segoe UI', sans-serif; font-size: 14px; padding: 16px; }}
h1 {{ font-size: 1.5rem; color: #e8e8ff; margin-bottom: 4px; }}
.subtitle {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 20px; }}
.card {{ background: var(--bg2); border: 1px solid var(--border);
        border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
.card h2 {{ font-size: 1.05rem; color: #b0b0e0; margin-bottom: 12px;
           border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
.tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }}
.tab {{ padding: 5px 14px; border-radius: 20px; border: 1px solid var(--border);
       cursor: pointer; font-size: 13px; background: var(--bg3);
       color: var(--muted); transition: all 0.15s; }}
.tab.active {{ background: #1a2a40; color: var(--blue); border-color: var(--blue); }}
.controls {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; font-size: 12px; color: var(--muted); }}
select {{ background: var(--bg3); color: var(--text); border: 1px solid var(--border);
         padding: 3px 8px; font-size: 12px; border-radius: 4px; }}
.grid {{ display: grid; gap: 16px; }}
.grid-2 {{ grid-template-columns: 1fr 1fr; }}
canvas {{ max-width: 100%; }}
.kpi-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }}
.kpi {{ flex: 1 1 140px; background: var(--bg3); border: 1px solid var(--border);
       border-radius: 8px; padding: 10px 14px; }}
.kpi .label {{ font-size: 0.7rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
.kpi .val {{ font-size: 1.35rem; font-weight: 700; color: #e8e8ff; margin-top: 2px; }}
.kpi .unit {{ font-size: 0.7rem; color: var(--muted); }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th {{ background: #0a0a22; color: #9090cc; padding: 6px 10px; text-align: left; border-bottom: 2px solid var(--border); white-space: nowrap; }}
td {{ padding: 5px 10px; border-bottom: 1px solid #1e1e38; white-space: nowrap; }}
tr:hover td {{ background: #1a1a30; }}
</style>
</head>
<body>
<h1>Bus Position Tracking Dashboard</h1>
<p class="subtitle" id="gen-time"></p>

<div class="card">
  <div class="controls">
    <label>Experiment:
      <select id="exp-sel"></select>
    </label>
    <label>Bus:
      <select id="bus-sel"><option value="">All buses</option></select>
    </label>
    <label>View:
      <select id="view-sel">
        <option value="timepos">Time-Position (corridor)</option>
        <option value="speed">Speed Profile</option>
        <option value="dist">Distance to Junction</option>
        <option value="events">Detection Zone Events</option>
      </select>
    </label>
  </div>
  <div id="kpi-row" class="kpi-row"></div>
  <canvas id="main-canvas" height="400"></canvas>
</div>

<div class="card">
  <h2>Per-Bus Summary Table</h2>
  <div class="controls">
    <label>Experiment:
      <select id="tbl-exp-sel"></select>
    </label>
    <label>Sort by:
      <select id="tbl-sort-sel">
        <option value="zones">Zone Entries</option>
        <option value="jcts">Junctions Visited</option>
        <option value="duration">Duration (s)</option>
        <option value="speed">Avg Speed</option>
      </select>
    </label>
  </div>
  <div style="overflow-x:auto">
    <table id="summary-table"><thead></thead><tbody></tbody></table>
  </div>
</div>

<script>
const ALL_DATA = {all_exp_json};
const COLORS = {json.dumps(COLORS)};
const EXP_NAMES = {json.dumps(exp_list)};

document.getElementById('gen-time').textContent =
  'Generated ' + new Date().toISOString().slice(0, 16).replace('T',' ') +
  '  |  ' + EXP_NAMES.length + ' experiment(s)';

let currentExp = EXP_NAMES[0] || '';
let currentBus = '';
let currentView = 'timepos';
let mainChart = null;

const expSel = document.getElementById('exp-sel');
const busSel = document.getElementById('bus-sel');
const viewSel = document.getElementById('view-sel');
const tblExpSel = document.getElementById('tbl-exp-sel');
const tblSortSel = document.getElementById('tbl-sort-sel');

EXP_NAMES.forEach(function(name) {{
  var o = document.createElement('option');
  o.value = name; o.textContent = name;
  expSel.appendChild(o.cloneNode(true));
  tblExpSel.appendChild(o);
}});
expSel.addEventListener('change', onExpChange);
busSel.addEventListener('change', onBusChange);
viewSel.addEventListener('change', onViewChange);
tblExpSel.addEventListener('change', renderSummaryTable);
tblSortSel.addEventListener('change', renderSummaryTable);

function onExpChange() {{
  currentExp = expSel.value;
  populateBusSelect();
  renderKPIs();
  renderChart();
  renderSummaryTable();
}}

function onBusChange() {{
  currentBus = busSel.value;
  renderKPIs();
  renderChart();
}}

function onViewChange() {{
  currentView = viewSel.value;
  renderChart();
}}

function getCurrentData() {{
  return ALL_DATA[currentExp] || [];
}}

function populateBusSelect() {{
  var data = getCurrentData();
  var busIds = [];
  var seen = {{}};
  data.forEach(function(p) {{
    if (!seen[p.vid]) {{ seen[p.vid] = true; busIds.push(p.vid); }}
  }});
  busIds.sort(function(a,b) {{ return a - b; }});
  busSel.innerHTML = '<option value="">All buses</option>';
  busIds.forEach(function(vid) {{
    var o = document.createElement('option');
    o.value = vid; o.textContent = 'Bus ' + vid;
    busSel.appendChild(o);
  }});
}}

function filterData(data) {{
  if (!currentBus) return data;
  var vid = parseInt(currentBus);
  return data.filter(function(p) {{ return p.vid === vid; }});
}}

// ── KPI row ────────────────────────────────────────────────────────
function renderKPIs() {{
  var data = filterData(getCurrentData());
  var all = getCurrentData();
  var busIds = new Set(); var jctIds = new Set();
  var zoneEnters = 0, zoneExits = 0, nInZone = 0;
  var minT = Infinity, maxT = -Infinity;
  var minDist = Infinity, maxDist = -Infinity;
  data.forEach(function(p) {{
    busIds.add(p.vid); jctIds.add(p.jct);
    if (p.event === 'zone_enter') zoneEnters++;
    if (p.event === 'zone_exit') zoneExits++;
    if (p.in_zone) nInZone++;
    if (p.t < minT) minT = p.t;
    if (p.t > maxT) maxT = p.t;
    if (p.dist < minDist) minDist = p.dist;
    if (p.dist > maxDist) maxDist = p.dist;
  }});
  var duration = data.length ? (maxT - minT) : 0;
  var inZonePct = all.length ? (100 * nInZone / all.length).toFixed(1) : 0;

  document.getElementById('kpi-row').innerHTML =
    '<div class="kpi"><div class="label">Buses</div><div class="val">' + busIds.size + '</div></div>' +
    '<div class="kpi"><div class="label">Track Points</div><div class="val">' + data.length.toLocaleString() + '</div></div>' +
    '<div class="kpi"><div class="label">Zone Entries</div><div class="val">' + zoneEnters + '</div></div>' +
    '<div class="kpi"><div class="label">Zone Exits</div><div class="val">' + zoneExits + '</div></div>' +
    '<div class="kpi"><div class="label">In-Zone %</div><div class="val">' + inZonePct + '<span class="unit">%</span></div></div>' +
    '<div class="kpi"><div class="label">Junctions</div><div class="val">' + jctIds.size + '</div></div>' +
    '<div class="kpi"><div class="label">Duration</div><div class="val">' + duration.toFixed(0) + '<span class="unit">s</span></div></div>';
}}

// ── Main chart ──────────────────────────────────────────────────────
function renderChart() {{
  var data = filterData(getCurrentData());
  if (mainChart) {{ mainChart.destroy(); mainChart = null; }}
  var ctx = document.getElementById('main-canvas').getContext('2d');

  if (currentView === 'timepos') renderTimePos(ctx, data);
  else if (currentView === 'speed') renderSpeed(ctx, data);
  else if (currentView === 'dist') renderDist(ctx, data);
  else if (currentView === 'events') renderEvents(ctx, data);
}}

function renderTimePos(ctx, data) {{
  var jcts = [];
  var seen = {{}};
  data.forEach(function(p) {{
    var jctStr = String(p.jct);
    if (!seen[jctStr]) {{ seen[jctStr] = true; jcts.push(jctStr); }}
  }});
  jcts.sort(function(a,b) {{ var na = parseInt(a), nb = parseInt(b); return na - nb; }});
  var jctIndex = {{}};
  jcts.forEach(function(j, i) {{ jctIndex[String(j)] = i; }});

  var busGroups = {{}};
  data.forEach(function(p) {{
    if (!busGroups[p.vid]) busGroups[p.vid] = [];
    busGroups[p.vid].push(p);
  }});

  var datasets = [];
  var ci = 0;
  Object.keys(busGroups).forEach(function(vid) {{
    var pts = busGroups[vid].sort(function(a,b) {{ return a.t - b.t; }});
    datasets.push({{
      label: 'Bus ' + vid,
      data: pts.map(function(p) {{ return {{x: p.t, y: jctIndex[String(p.jct)]}}; }}),
      borderColor: COLORS[ci % COLORS.length],
      backgroundColor: 'transparent',
      borderWidth: currentBus ? 2 : 1,
      pointRadius: 0, pointHitRadius: 5,
      showLine: true, tension: 0.1,
    }});
    ci++;
  }});

  mainChart = new Chart(ctx, {{
    type: 'scatter',
    data: {{ datasets: datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: datasets.length < 30, position: 'right', labels: {{color:'#9090cc',font:{{size:10}}}} }} }},
      scales: {{
        x: {{ type: 'linear', title: {{ display: true, text: 'Time (s)', color: '#9090cc' }},
              ticks: {{ color: '#7070a0' }}, grid: {{ color: '#1e1e38' }} }},
        y: {{ title: {{ display: true, text: 'Junction', color: '#9090cc' }},
              min: -0.5, max: jcts.length - 0.5,
              ticks: {{ color: '#7070a0', stepSize: 1,
                        callback: function(v) {{ var j = Math.round(v); return j >= 0 && j < jcts.length ? jcts[j] : ''; }} }},
              grid: {{ color: '#1e1e38' }} }}
      }}
    }}
  }});
}}

function renderSpeed(ctx, data) {{
  var busGroups = {{}};
  data.forEach(function(p) {{
    if (!busGroups[p.vid]) busGroups[p.vid] = [];
    busGroups[p.vid].push({{t: p.t, x: p.x, y: p.y}});
  }});

  var datasets = [];
  var ci = 0;
  Object.keys(busGroups).forEach(function(vid) {{
    var pts = busGroups[vid].sort(function(a,b) {{ return a.t - b.t; }});
    var speeds = [];
    for (var i = 1; i < pts.length; i++) {{
      var dt = pts[i].t - pts[i-1].t;
      if (dt <= 0) continue;
      var dx = pts[i].x - pts[i-1].x;
      var dy = pts[i].y - pts[i-1].y;
      var dist = Math.sqrt(dx*dx + dy*dy);
      var speed = dist / dt * 3.6; // km/h
      speeds.push({{x: pts[i].t, y: speed}});
    }}
    if (speeds.length > 0) {{
      datasets.push({{
        label: 'Bus ' + vid,
        data: speeds,
        borderColor: COLORS[ci % COLORS.length],
        backgroundColor: 'transparent',
        borderWidth: currentBus ? 2 : 0.8,
        pointRadius: 0, showLine: true, tension: 0.3,
      }});
    }}
    ci++;
  }});

  mainChart = new Chart(ctx, {{
    type: 'scatter',
    data: {{ datasets: datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: datasets.length < 30, position: 'right', labels: {{color:'#9090cc',font:{{size:10}}}} }} }},
      scales: {{
        x: {{ type: 'linear', title: {{ display: true, text: 'Time (s)', color: '#9090cc' }},
              ticks: {{ color: '#7070a0' }}, grid: {{ color: '#1e1e38' }} }},
        y: {{ title: {{ display: true, text: 'Speed (km/h)', color: '#9090cc' }},
              ticks: {{ color: '#7070a0' }}, grid: {{ color: '#1e1e38' }}, min: 0 }}
      }}
    }}
  }});
}}

function renderDist(ctx, data) {{
  var busGroups = {{}};
  data.forEach(function(p) {{
    if (!busGroups[p.vid]) busGroups[p.vid] = [];
    busGroups[p.vid].push(p);
  }});

  var datasets = [];
  var ci = 0;
  Object.keys(busGroups).forEach(function(vid) {{
    var pts = busGroups[vid].sort(function(a,b) {{ return a.t - b.t; }});
    datasets.push({{
      label: 'Bus ' + vid,
      data: pts.map(function(p) {{ return {{x: p.t, y: p.dist}}; }}),
      borderColor: COLORS[ci % COLORS.length],
      backgroundColor: 'transparent',
      borderWidth: currentBus ? 2 : 0.8,
      pointRadius: 0, showLine: true, tension: 0.3,
    }});
    ci++;
  }});

  mainChart = new Chart(ctx, {{
    type: 'scatter',
    data: {{ datasets: datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: datasets.length < 30, position: 'right', labels: {{color:'#9090cc',font:{{size:10}}}} }} }},
      scales: {{
        x: {{ type: 'linear', title: {{ display: true, text: 'Time (s)', color: '#9090cc' }},
              ticks: {{ color: '#7070a0' }}, grid: {{ color: '#1e1e38' }} }},
        y: {{ title: {{ display: true, text: 'Distance to Junction (m)', color: '#9090cc' }},
              ticks: {{ color: '#7070a0' }}, grid: {{ color: '#1e1e38' }} }}
      }}
    }}
  }});
}}

function renderEvents(ctx, data) {{
  var jcts = [];
  var seen = {{}};
  data.forEach(function(p) {{
    var jctStr = String(p.jct);
    if (!seen[jctStr]) {{ seen[jctStr] = true; jcts.push(jctStr); }}
  }});
  jcts.sort(function(a,b) {{ var na = parseInt(a), nb = parseInt(b); return na - nb; }});
  var jctIndex = {{}};
  jcts.forEach(function(j, i) {{ jctIndex[String(j)] = i; }});

  var busGroups = {{}};
  data.forEach(function(p) {{
    if (!busGroups[p.vid]) busGroups[p.vid] = [];
    busGroups[p.vid].push(p);
  }});

  var datasets = [];
  var ci = 0;
  Object.keys(busGroups).forEach(function(vid) {{
    var pts = busGroups[vid].filter(function(p) {{
      return p.event !== 'track' && p.event !== '';
    }});
    if (pts.length === 0) return;
    datasets.push({{
      label: 'Bus ' + vid,
      data: pts.map(function(p) {{ return {{x: p.t, y: jctIndex[String(p.jct)]}}; }}),
      borderColor: COLORS[ci % COLORS.length],
      backgroundColor: COLORS[ci % COLORS.length],
      borderWidth: 1, pointRadius: 4, showLine: false,
    }});
    ci++;
  }});

  mainChart = new Chart(ctx, {{
    type: 'scatter',
    data: {{ datasets: datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ display: datasets.length < 30, position: 'right', labels: {{color:'#9090cc',font:{{size:10}}}} }} }},
      scales: {{
        x: {{ type: 'linear', title: {{ display: true, text: 'Time (s)', color: '#9090cc' }},
              ticks: {{ color: '#7070a0' }}, grid: {{ color: '#1e1e38' }} }},
        y: {{ title: {{ display: true, text: 'Junction', color: '#9090cc' }},
              min: -0.5, max: jcts.length - 0.5,
              ticks: {{ color: '#7070a0', stepSize: 1,
                        callback: function(v) {{ var j = Math.round(v); return j >= 0 && j < jcts.length ? jcts[j] : ''; }} }},
              grid: {{ color: '#1e1e38' }} }}
      }}
    }}
  }});
}}

// ── Summary table ───────────────────────────────────────────────────
function renderSummaryTable() {{
  var expName = tblExpSel.value;
  var data = ALL_DATA[expName] || [];
  var sortBy = tblSortSel.value;

  var busSummaries = {{}};
  data.forEach(function(p) {{
    if (!busSummaries[p.vid]) {{
      busSummaries[p.vid] = {{
        vid: p.vid, minT: Infinity, maxT: -Infinity,
        jcts: new Set(), zones: 0, points: 0, sumDist: 0, sumT: 0, firstPT: null, lastPT: null
      }};
    }}
    var s = busSummaries[p.vid];
    if (p.t < s.minT) {{ s.minT = p.t; s.firstPT = p; }}
    if (p.t > s.maxT) {{ s.maxT = p.t; s.lastPT = p; }}
    s.jcts.add(p.jct);
    if (p.event === 'zone_enter') s.zones++;
    s.points++;
  }});

  var rows = [];
  Object.keys(busSummaries).forEach(function(vid) {{
    var s = busSummaries[vid];
    var dur = s.maxT - s.minT;
    var dx = (s.lastPT && s.firstPT) ? s.lastPT.x - s.firstPT.x : 0;
    var dy = (s.lastPT && s.firstPT) ? s.lastPT.y - s.firstPT.y : 0;
    var dist = Math.sqrt(dx*dx + dy*dy);
    var speed = dur > 0 ? (dist / dur * 3.6).toFixed(1) : '-';
    rows.push({{
      vid: s.vid, jcts: s.jcts.size, zones: s.zones,
      duration: dur.toFixed(1), points: s.points, speed: speed
    }});
  }});

  if (sortBy === 'zones') rows.sort(function(a,b) {{ return b.zones - a.zones; }});
  else if (sortBy === 'jcts') rows.sort(function(a,b) {{ return b.jcts - a.jcts; }});
  else if (sortBy === 'duration') rows.sort(function(a,b) {{ return parseFloat(b.duration) - parseFloat(a.duration); }});
  else if (sortBy === 'speed') rows.sort(function(a,b) {{ return parseFloat(b.speed) - parseFloat(a.speed); }});

  var thead = '<tr><th>Bus ID</th><th>Junctions</th><th>Zone Entries</th><th>Duration (s)</th><th>Track Points</th><th>Avg Speed (km/h)</th></tr>';
  var tbody = rows.map(function(r) {{
    return '<tr><td>' + r.vid + '</td><td>' + r.jcts + '</td><td>' + r.zones +
           '</td><td>' + r.duration + '</td><td>' + r.points + '</td><td>' + r.speed + '</td></tr>';
  }}).join('');

  document.querySelector('#summary-table thead').innerHTML = thead;
  document.querySelector('#summary-table tbody').innerHTML = tbody;
}}

// ── Init ────────────────────────────────────────────────────────────
if (EXP_NAMES.length > 0) {{
  currentExp = EXP_NAMES[0];
  expSel.value = currentExp;
  tblExpSel.value = currentExp;
  populateBusSelect();
  renderKPIs();
  renderChart();
  renderSummaryTable();
}}
</script>
</body>
</html>"""


def generate(log_dir: str = None, out_html: str = None) -> str:
    if log_dir is None:
        log_dir = LOG_DIR
    if out_html is None:
        out_html = OUT_HTML

    # Try external JSON files first (from dashboard_data/), fall back to CSVs
    all_experiments = {}
    json_dir = os.path.join(os.path.dirname(out_html), "dashboard_data")

    if os.path.isdir(json_dir):
        for fname in sorted(glob.glob(os.path.join(json_dir, "run_*_bus_tracking.json"))):
            m = re.match(r".*run_(\d+)_bus_tracking\.json$", fname)
            idx = m.group(1)
            rows = _read_bus_tracking_json(fname)
            if rows:
                all_experiments[f"Experiment {idx}"] = rows

    # Fallback: read CSVs from logs/
    if not all_experiments:
        csv_paths = sorted(
            glob.glob(os.path.join(log_dir, "bus_positions_*.csv")),
            key=lambda x: os.path.getmtime(x),
        )
        for path in csv_paths:
            stem = os.path.basename(path)
            exp_name = stem[len("bus_positions_"):]
            exp_name = re.sub(r"_\d{8}_\d{6}\.csv$", "", exp_name)
            exp_name = re.sub(r"_\d{8}T\d{6}\.csv$", "", exp_name)
            exp_name = re.sub(r"\.csv$", "", exp_name)
            rows = []
            try:
                with open(path, newline="", encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        try:
                            rows.append({
                                "t": float(r.get("sim_time_s", 0)), "vid": int(float(r.get("veh_id", 0) or 0)),
                                "x": float(r.get("x", 0)), "y": float(r.get("y", 0)),
                                "jct": int(float(r.get("nearest_jct", 0) or 0)),
                                "dist": float(r.get("dist_m", 0)),
                                "in_zone": int(float(r.get("in_zone", 0) or 0)),
                                "zone_r": float(r.get("zone_radius_m", 0)),
                                "event": r.get("event", "track"),
                            })
                        except Exception:
                            pass
            except Exception:
                pass
            if rows:
                all_experiments[exp_name] = rows

    if not all_experiments:
        print("[bus_tracking_dashboard] No bus tracking data found.")
        return None

    html = _build_html(all_experiments)

    out_dir = os.path.dirname(out_html)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)

    total = sum(len(v) for v in all_experiments.values())
    print(f"[bus_tracking_dashboard] {len(all_experiments)} experiments, "
          f"{total:,} track points -> {out_html}")
    return out_html


def main():
    ap = argparse.ArgumentParser(description="Bus tracking dashboard generator")
    ap.add_argument("--logs", default=LOG_DIR, help="logs directory")
    ap.add_argument("--out", default=OUT_HTML, help="output HTML path")
    args = ap.parse_args()
    generate(args.logs, args.out)


if __name__ == "__main__":
    main()
