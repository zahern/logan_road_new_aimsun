"""
plot_phase_timing.py
--------------------
Generates phase_timing_dashboard.html — an interactive Gantt-style chart
showing the phase sequence of each signalised intersection over the entire
simulation, comparing the NO_TSP baseline against a TSP run (DCTSP_MARL or
DCTSP_BUS_PRIORITY).

Phase sequences are reconstructed from:
  • Nominal phase plans extracted from the Aimsun TSP log PATCH lines
  • GE (green extension) and INS (phase insertion) events from detection_points CSVs

Usage:
  python plot_phase_timing.py                  # auto-discovers latest log files
  python plot_phase_timing.py --tsp_log <path> # explicit TSP log
  python plot_phase_timing.py --out <html>     # custom output path
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Phase-plan extraction
# ---------------------------------------------------------------------------
PATCH_RE = re.compile(
    r"PATCH.*?inter=(\d+).*?NumberOfPhases\s*\S+\s*(\d+)\s*\|.*?GreenPhaseDuration\s*\S+\s*\[([^\]]+)\]"
)
BUS_PHASE_MAP = {
    39606: 2, 39590: 2, 36393: 2, 36385: 1, 39593: 1,
    39587: 1, 39576: 1, 39578: 2, 1043762: 2, 39569: 4, 39572: 2, 38339: 2,
}


def load_phase_plans(tsp_log_path: str) -> dict:
    """Return {jct_id: {'n_phases': int, 'durations': [float, ...], 'bus_phase': int}}."""
    plans = {}
    try:
        with open(tsp_log_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        for m in PATCH_RE.finditer(content):
            jct = int(m.group(1))
            n = int(m.group(2))
            durs = [float(x.strip()) for x in m.group(3).split(",")]
            bus_ph = BUS_PHASE_MAP.get(jct, 1)
            plans[jct] = {"n_phases": n, "durations": durs, "bus_phase": bus_ph}
    except Exception as e:
        print(f"[phase_timing] Warning: could not parse phase plans from {tsp_log_path}: {e}")
    return plans


# ---------------------------------------------------------------------------
# TSP event extraction from detection_points CSV
# ---------------------------------------------------------------------------
_DUR_RE = re.compile(r"(GE|INS)_(\d+)s")


def load_tsp_events(dp_csv: str) -> list:
    """Return list of GE/INS action events sorted by time."""
    events = []
    if not dp_csv or not os.path.isfile(dp_csv):
        return events
    try:
        with open(dp_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tier = row.get("tier", "")
                status = row.get("prearm_status", "")
                if status != "action":
                    continue
                if tier not in ("harmony-ge-local", "harmony-ins-local"):
                    continue
                note = row.get("prearm_note", "")
                m = _DUR_RE.search(note)
                if not m:
                    continue
                act_type = m.group(1)      # "GE" or "INS"
                act_dur = float(m.group(2))
                events.append({
                    "t": float(row.get("sim_time_s", 0) or 0),
                    "jct": int(float(row.get("junction_id", -1) or -1)),
                    "type": act_type,
                    "dur": act_dur,
                    "signal_phase": int(float(row.get("signal_phase", 1) or 1)),
                    "phase_start_t": float(row.get("phase_start_t", 0) or 0),
                })
    except Exception as e:
        print(f"[phase_timing] Warning: could not read {dp_csv}: {e}")
    events.sort(key=lambda x: x["t"])
    return events


# ---------------------------------------------------------------------------
# Phase sequence reconstruction
# ---------------------------------------------------------------------------
def reconstruct_phases(plans: dict, events_by_jct: dict, t_start: float, t_end: float) -> dict:
    """
    For each junction, build a list of phase segments:
      [(phase_number, t_start, t_end, intervention_type_or_None), ...]

    intervention_type: None = nominal, 'GE' = extended, 'INS' = inserted
    """
    result = {}
    for jct, plan in plans.items():
        durs = plan["durations"]
        n_ph = len(durs)
        bus_ph = plan["bus_phase"]  # 1-indexed
        evs = sorted(events_by_jct.get(jct, []), key=lambda x: x["t"])

        segments = []
        t = t_start
        # Start at phase index 0 (phase 1)
        ph_idx = 0  # 0-indexed; phase number = ph_idx + 1

        ev_idx = 0  # pointer into events list

        while t < t_end:
            ph_num = ph_idx + 1           # 1-indexed phase number
            nominal_dur = durs[ph_idx]
            seg_end = t + nominal_dur
            intervention = None

            # Check for a TSP event during this phase
            while ev_idx < len(evs) and evs[ev_idx]["t"] < seg_end:
                ev = evs[ev_idx]
                ev_t = ev["t"]

                if ev["type"] == "GE" and ph_num == bus_ph:
                    # Extend the current bus phase by GE duration
                    seg_end += ev["dur"]
                    intervention = "GE"
                    ev_idx += 1

                elif ev["type"] == "INS" and ph_num != bus_ph:
                    # Split: finish current phase up to ev_t, then insert bus phase
                    if ev_t > t + 0.5:
                        segments.append((ph_num, t, ev_t, None))
                    # Inserted bus phase
                    ins_end = min(ev_t + ev["dur"], t_end)
                    segments.append((bus_ph, ev_t, ins_end, "INS"))
                    t = ins_end
                    ev_idx += 1
                    # Continue with the SAME nominal phase after insertion
                    remaining = seg_end - ev_t - ev["dur"]
                    if remaining > 0.5:
                        seg_end = t + remaining
                        intervention = None
                        continue
                    else:
                        # Move to next phase
                        ph_idx = (ph_idx + 1) % n_ph
                        ph_num = ph_idx + 1
                        nominal_dur = durs[ph_idx]
                        seg_end = t + nominal_dur
                        intervention = None
                    break
                else:
                    ev_idx += 1

            seg_end = min(seg_end, t_end)
            if seg_end > t + 0.01:
                segments.append((ph_num, t, seg_end, intervention))
            t = seg_end
            ph_idx = (ph_idx + 1) % n_ph

        result[jct] = segments
    return result


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------
# Assign a consistent colour to each phase number (up to 15 phases)
PHASE_COLOURS = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#16a085", "#c0392b", "#2980b9",
    "#8e44ad", "#27ae60", "#d35400", "#2c3e50", "#7f8c8d",
]
GE_STRIPE = "rgba(255,255,255,0.35)"
INS_STRIPE = "rgba(0,0,0,0.30)"


def _phase_col(ph: int) -> str:
    return PHASE_COLOURS[(ph - 1) % len(PHASE_COLOURS)]


def build_html(
    plans: dict,
    notsp_segments: dict,
    tsp_segments: dict,
    tsp_label: str,
    tsp_events: list,
    t_start: float,
    t_end: float,
    out_path: str,
):
    # Prepare JS data
    jct_ids = sorted(plans.keys())
    jct_labels = {j: str(j) for j in jct_ids}

    rows_data = []
    for jct in jct_ids:
        no_segs = notsp_segments.get(jct, [])
        tsp_segs = tsp_segments.get(jct, [])
        rows_data.append({
            "jct": jct,
            "label": jct_labels[jct],
            "bus_phase": plans[jct]["bus_phase"],
            "n_phases": plans[jct]["n_phases"],
            "notsp": [(ph, t0, t1, iv) for ph, t0, t1, iv in no_segs],
            "tsp": [(ph, t0, t1, iv) for ph, t0, t1, iv in tsp_segs],
        })

    events_data = [{"t": e["t"], "jct": e["jct"], "type": e["type"], "dur": e["dur"]} for e in tsp_events]

    rows_js = json.dumps(rows_data, separators=(",", ":"))
    events_js = json.dumps(events_data, separators=(",", ":"))
    phase_cols_js = json.dumps(PHASE_COLOURS)

    all_n_phases = max((plans[j]["n_phases"] for j in jct_ids), default=5)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Phase Signal Timing Dashboard</title>
<style>
  :root {{
    --bg: #0a0a18; --card: #10102a; --border: #2a2a50;
    --text: #ccccee; --muted: #7070a0; --accent: #29b6f6;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; font-size: 13px; padding: 16px; }}
  h1 {{ font-size: 18px; margin-bottom: 4px; color: var(--accent); }}
  p.sub {{ color: var(--muted); margin-bottom: 14px; font-size: 11px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 14px; margin-bottom: 14px; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--muted); }}
  .legend-swatch {{ width: 14px; height: 14px; border-radius: 2px; flex-shrink: 0; }}
  canvas {{ display: block; width: 100%; }}
  .jct-block {{ margin-bottom: 20px; }}
  .jct-title {{ font-size: 12px; font-weight: bold; color: var(--accent); margin-bottom: 4px; }}
  .row-label {{ font-size: 10px; color: var(--muted); text-align: right; padding-right: 6px; display: inline-block; width: 90px; }}
  .canvas-row {{ display: block; }}
  .row-wrap {{ display: flex; align-items: center; margin-bottom: 3px; }}
  #filter-bar {{ margin-bottom: 14px; }}
  #filter-bar label {{ color: var(--muted); font-size: 11px; margin-right: 6px; }}
  #jct-filter {{ background: #16163a; border: 1px solid var(--border); color: var(--text); border-radius: 4px; padding: 2px 6px; font-size: 11px; }}
</style>
</head>
<body>
<h1>Phase Signal Timing Comparison</h1>
<p class="sub">Entire simulation — each row shows the phase sequence for one intersection. Top row = NO TSP (nominal plan). Bottom row = {tsp_label} (with GE / INS applied). Warm-up excluded. Time range: {t_start:.0f}s – {t_end:.0f}s.</p>

<div id="filter-bar">
  <label for="jct-filter">Junction:</label>
  <select id="jct-filter">
    <option value="">All</option>
  </select>
</div>

<div id="legend-wrap" class="card">
  <div class="legend" id="phase-legend"></div>
  <div class="legend" style="margin-top:4px">
    <span class="legend-item"><span class="legend-swatch" style="background:rgba(255,255,100,0.6)"></span>GE extended</span>
    <span class="legend-item"><span class="legend-swatch" style="background:rgba(0,0,0,0.5);border:1px solid #00bcd4"></span>INS inserted</span>
  </div>
</div>

<div id="chart-host"></div>

<script>
const ROWS = {rows_js};
const EVENTS = {events_js};
const PHASE_COLS = {phase_cols_js};
const T_START = {t_start};
const T_END = {t_end};
const TSP_LABEL = {json.dumps(tsp_label)};
const N_MAX_PHASES = {all_n_phases};

// Build legend
const legendEl = document.getElementById('phase-legend');
for (let ph = 1; ph <= N_MAX_PHASES; ph++) {{
  const col = PHASE_COLS[(ph - 1) % PHASE_COLS.length];
  legendEl.innerHTML += `<span class="legend-item"><span class="legend-swatch" style="background:${{col}}"></span>Ph ${{ph}}</span>`;
}}

// Populate junction filter
const jctSel = document.getElementById('jct-filter');
ROWS.forEach(r => {{
  const o = document.createElement('option');
  o.value = String(r.jct);
  o.textContent = `Jct ${{r.jct}} (bus ph ${{r.bus_phase}})`;
  jctSel.appendChild(o);
}});

const host = document.getElementById('chart-host');

function drawRow(canvas, segments, busPhase, W, H) {{
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);
  const tRange = T_END - T_START;

  for (const [ph, t0, t1, iv] of segments) {{
    if (t1 <= T_START || t0 >= T_END) continue;
    const x0 = Math.max(0, (t0 - T_START) / tRange * W);
    const x1 = Math.min(W, (t1 - T_START) / tRange * W);
    const col = PHASE_COLS[(ph - 1) % PHASE_COLS.length];
    ctx.fillStyle = col;
    ctx.fillRect(x0, 0, x1 - x0, H);
    // Overlay stripe for intervention
    if (iv === 'GE') {{
      ctx.fillStyle = 'rgba(255,255,100,0.45)';
      ctx.fillRect(x0, 0, x1 - x0, H);
      ctx.strokeStyle = 'rgba(255,255,0,0.9)'; ctx.lineWidth = 1.5;
      ctx.strokeRect(x0, 0.5, x1 - x0, H - 1);
    }} else if (iv === 'INS') {{
      ctx.fillStyle = 'rgba(0,0,0,0.45)';
      ctx.fillRect(x0, 0, x1 - x0, H);
      ctx.strokeStyle = '#00bcd4'; ctx.lineWidth = 1.5;
      ctx.strokeRect(x0, 0.5, x1 - x0, H - 1);
    }}
    // Phase number label if wide enough
    const wPx = x1 - x0;
    if (wPx > 14) {{
      ctx.fillStyle = 'rgba(0,0,0,0.75)';
      ctx.font = 'bold ' + Math.min(10, wPx * 0.6) + 'px system-ui';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(ph), (x0 + x1) / 2, H / 2);
    }}
  }}
  // Border
  ctx.strokeStyle = '#2a2a50'; ctx.lineWidth = 1;
  ctx.strokeRect(0.5, 0.5, W - 1, H - 1);
}}

function drawTimeTicks(canvas, W) {{
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr;
  canvas.height = 18 * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = '18px';
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, 18);
  const tRange = T_END - T_START;
  const step = tRange > 3000 ? 600 : tRange > 1500 ? 300 : 120;
  ctx.fillStyle = '#7070a0'; ctx.font = '9px system-ui'; ctx.textAlign = 'center';
  for (let t = Math.ceil(T_START / step) * step; t <= T_END; t += step) {{
    const x = (t - T_START) / tRange * W;
    ctx.fillText(t + 's', x, 12);
    ctx.fillStyle = '#2a2a50';
    ctx.fillRect(x - 0.5, 0, 1, 6);
    ctx.fillStyle = '#7070a0';
  }}
}}

function renderAll() {{
  host.innerHTML = '';
  const selJ = jctSel.value ? Number(jctSel.value) : null;
  const visRows = selJ ? ROWS.filter(r => r.jct === selJ) : ROWS;

  const W = host.clientWidth - 100 || 900;
  const TICK_H = 18;
  const ROW_H = 22;

  // Tick axis
  const tickWrap = document.createElement('div');
  tickWrap.className = 'row-wrap';
  tickWrap.innerHTML = '<span class="row-label"></span>';
  const tickCanvas = document.createElement('canvas');
  tickCanvas.className = 'canvas-row';
  drawTimeTicks(tickCanvas, W);
  tickWrap.appendChild(tickCanvas);
  host.appendChild(tickWrap);

  for (const r of visRows) {{
    const block = document.createElement('div');
    block.className = 'jct-block card';

    const title = document.createElement('div');
    title.className = 'jct-title';
    title.textContent = `Junction ${{r.jct}}  |  ${{r.n_phases}} phases  |  bus phase = ${{r.bus_phase}}`;
    block.appendChild(title);

    // NO TSP row
    const noTspWrap = document.createElement('div'); noTspWrap.className = 'row-wrap';
    noTspWrap.innerHTML = '<span class="row-label">NO TSP</span>';
    const noTspCanvas = document.createElement('canvas'); noTspCanvas.className = 'canvas-row';
    drawRow(noTspCanvas, r.notsp, r.bus_phase, W, ROW_H);
    noTspWrap.appendChild(noTspCanvas); block.appendChild(noTspWrap);

    // TSP row
    const tspWrap = document.createElement('div'); tspWrap.className = 'row-wrap';
    tspWrap.innerHTML = `<span class="row-label">${{TSP_LABEL}}</span>`;
    const tspCanvas = document.createElement('canvas'); tspCanvas.className = 'canvas-row';
    drawRow(tspCanvas, r.tsp, r.bus_phase, W, ROW_H);
    tspWrap.appendChild(tspCanvas); block.appendChild(tspWrap);

    // Event markers row (GE/INS callouts)
    const jctEvs = EVENTS.filter(e => e.jct === r.jct);
    if (jctEvs.length) {{
      const evCanvas = document.createElement('canvas');
      const evCtx = evCanvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      evCanvas.width = W * dpr; evCanvas.height = 16 * dpr;
      evCanvas.style.width = W + 'px'; evCanvas.style.height = '16px';
      evCtx.scale(dpr, dpr);
      evCtx.clearRect(0, 0, W, 16);
      const tRange = T_END - T_START;
      for (const ev of jctEvs) {{
        const x = (ev.t - T_START) / tRange * W;
        const col = ev.type === 'GE' ? '#2ecc71' : '#00bcd4';
        evCtx.fillStyle = col;
        evCtx.fillRect(x - 0.75, 0, 1.5, 16);
        evCtx.font = '8px system-ui'; evCtx.fillStyle = col;
        evCtx.textAlign = x > W * 0.9 ? 'right' : 'left';
        evCtx.textBaseline = 'top';
        evCtx.fillText(`${{ev.type}}${{ev.dur}}s`, x + (x > W * 0.9 ? -2 : 2), 1);
      }}
      const evWrap = document.createElement('div'); evWrap.className = 'row-wrap';
      evWrap.innerHTML = '<span class="row-label" style="font-size:9px;color:#9090cc">TSP events</span>';
      evWrap.appendChild(evCanvas); block.appendChild(evWrap);
    }}

    host.appendChild(block);
  }}
}}

jctSel.addEventListener('change', renderAll);
window.addEventListener('resize', () => setTimeout(renderAll, 100));
renderAll();
</script>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[phase_timing] Written: {out_path}")


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------
def _find_latest(pattern: str, log_dir: str):
    import glob
    matches = sorted(glob.glob(os.path.join(log_dir, pattern)), key=os.path.getmtime, reverse=True)
    return matches[0] if matches else None


def main():
    parser = argparse.ArgumentParser(description="Generate phase signal timing comparison dashboard")
    parser.add_argument("--log_dir", default=os.path.join(os.path.dirname(__file__), "logs"))
    parser.add_argument("--tsp_log", default=None, help="Path to Aimsun TSP log (DCTSP_MARL run)")
    parser.add_argument("--dp_tsp", default=None, help="detection_points CSV for TSP run")
    parser.add_argument("--dp_notsp", default=None, help="detection_points CSV for NO_TSP run")
    parser.add_argument("--tsp_label", default=None, help="Label for TSP run (default: auto)")
    parser.add_argument("--t_start", type=float, default=0.0, help="Simulation start time (s)")
    parser.add_argument("--t_end", type=float, default=3600.0, help="Simulation end time (s)")
    parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "phase_timing_dashboard.html"))
    args = parser.parse_args()

    log_dir = args.log_dir

    # Auto-discover files — prefer MARL/BUS_PRIORITY TSP log (has PATCH lines)
    tsp_log = args.tsp_log
    if not tsp_log:
        import glob
        candidates = sorted(glob.glob(os.path.join(log_dir, "Aimsun_TSP_Log_*.txt")), key=os.path.getmtime, reverse=True)
        # Prefer logs that contain PATCH/GreenPhaseDuration data
        for c in candidates:
            try:
                with open(c, "r", encoding="utf-8", errors="replace") as _f:
                    _snippet = _f.read(50000)
                if "GreenPhaseDuration" in _snippet:
                    tsp_log = c
                    break
            except Exception:
                continue
        if not tsp_log and candidates:
            tsp_log = candidates[0]
    if not tsp_log:
        print("[phase_timing] ERROR: no TSP log found. Pass --tsp_log.")
        sys.exit(1)

    dp_tsp = args.dp_tsp or _find_latest("detection_points_DCTSP_MARL_*.csv", log_dir)
    if not dp_tsp:
        dp_tsp = _find_latest("detection_points_DCTSP_BUS_PRIORITY_*.csv", log_dir)
    if not dp_tsp:
        print("[phase_timing] ERROR: no DCTSP detection_points CSV found. Pass --dp_tsp.")
        sys.exit(1)

    dp_notsp = args.dp_notsp or _find_latest("detection_points_NO_TSP_*.csv", log_dir)

    # Auto-detect TSP label from filename
    tsp_label = args.tsp_label
    if not tsp_label:
        base = os.path.basename(dp_tsp)
        m = re.match(r"detection_points_(.+?)_\d{8}", base)
        tsp_label = m.group(1) if m else "TSP"

    print(f"[phase_timing] TSP log:     {tsp_log}")
    print(f"[phase_timing] TSP detects: {dp_tsp}  ({tsp_label})")
    print(f"[phase_timing] NO_TSP det:  {dp_notsp or '(none — nominal only)'}")

    plans = load_phase_plans(tsp_log)
    if not plans:
        print("[phase_timing] ERROR: could not extract phase plans from log.")
        sys.exit(1)
    print(f"[phase_timing] Loaded phase plans for {len(plans)} intersections.")

    tsp_events = load_tsp_events(dp_tsp)
    print(f"[phase_timing] TSP events: {len(tsp_events)} (GE/INS actions)")

    # Group events by junction
    tsp_ev_by_jct: dict = {}
    for ev in tsp_events:
        tsp_ev_by_jct.setdefault(ev["jct"], []).append(ev)

    t_start = args.t_start
    t_end = args.t_end

    notsp_segments = reconstruct_phases(plans, {}, t_start, t_end)
    tsp_segments = reconstruct_phases(plans, tsp_ev_by_jct, t_start, t_end)

    build_html(plans, notsp_segments, tsp_segments, tsp_label, tsp_events, t_start, t_end, args.out)


if __name__ == "__main__":
    main()
