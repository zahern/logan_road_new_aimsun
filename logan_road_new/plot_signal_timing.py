"""
Signal Timing Diagram v2 — multi-strategy, filterable by time.

Breakdown markers:
  GE  — Green Extension (harmony-ge-local / dctsp_ge)
  INS — Phase Insertion (harmony-ins-local / dctsp_ins)
  GR  — Natural Green (harmony-no-ge-local): bus arrived in green, no TSP action needed
  PR  — Prearm events (coord-prearm-*): fired / success / missed

Controls (in HTML):
  Strategy dropdown  — compare any run vs NO_TSP
  Time range filter  — zoom to a simulation window
  Marker checkboxes  — show/hide GE / INS / GR / PR / Arrivals / Replan / Phase labels

Usage:
    python plot_signal_timing.py [logs_dir] [out.html]
"""

import os, sys, csv, glob, json, math, re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_log_dir   = os.path.join(SCRIPT_DIR, "logs")
_out_html  = os.path.join(SCRIPT_DIR, "signal_timing_diagram.html")
if len(sys.argv) >= 2: _log_dir  = sys.argv[1]
if len(sys.argv) >= 3: _out_html = sys.argv[2]

# ── Load INTERSECTIONS_CONFIG ──────────────────────────────────────────────────
try:
    sys.path.insert(0, SCRIPT_DIR)
    from intersection_configs import INTERSECTIONS_CONFIG
except ImportError:
    print("[plot_signal_timing] cannot import INTERSECTIONS_CONFIG — aborting")
    sys.exit(1)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _f(v, d=0.0):
    try: return float(v)
    except: return d

def _latest(pattern):
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None

def _read_csv(path):
    if not path or not os.path.isfile(path): return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))

def _compute_cycle_offset(jct_id, cfg, all_rows):
    cycle_s  = _f(cfg.get("cycle_length", 110))
    bp_dur   = _f(cfg.get("BusPhaseDuration", 30))
    bus_ph_1 = int(cfg.get("BusPhase", 1))
    n_phases = max(len(cfg.get("SignalGroupIDList", [])), 1)
    non_dur  = (cycle_s - bp_dur) / max(n_phases - 1, 1)

    phase_starts = []
    pos = 0.0
    for ph in range(n_phases):
        phase_starts.append(pos)
        pos += bp_dur if ph == (bus_ph_1 - 1) % n_phases else non_dur

    candidates = sorted(
        [r for r in all_rows
         if int(_f(r.get("junction_id", 0))) == jct_id
         and r.get("signal_phase") and int(_f(r.get("signal_phase", 0))) > 0],
        key=lambda r: _f(r.get("sim_time_s", 0)),
    )
    if not candidates:
        return 0.0
    r0     = candidates[0]
    t_det  = _f(r0.get("sim_time_s", 0))
    sp     = int(_f(r0.get("signal_phase", 1)))
    ph_idx = (sp - 1) % n_phases
    return t_det - phase_starts[ph_idx]

def _build_marl_phase_bars(jct_id, cfg, ge_evts, ins_evts, t_start, t_end, t_cycle_0=0.0):
    """Return list of (t0, t1, phase_num_1indexed, bar_type)."""
    cycle_s  = _f(cfg.get("cycle_length", 110))
    bp_dur   = _f(cfg.get("BusPhaseDuration", 30))
    bus_ph_1 = int(cfg.get("BusPhase", 1))
    n_phases = max(len(cfg.get("SignalGroupIDList", [])), 1)
    non_dur  = (cycle_s - bp_dur) / max(n_phases - 1, 1)

    ge_q  = sorted([(t, d, sp, bp) for (jj, t, d, sp, bp) in ge_evts  if jj == jct_id])
    ins_q = sorted([(t, d, sp, bp) for (jj, t, d, sp, bp) in ins_evts if jj == jct_id])
    ge_i = ins_i = 0
    bars  = []

    if cycle_s > 0 and t_cycle_0 != 0.0:
        cursor = t_cycle_0 + cycle_s * math.floor((t_start - t_cycle_0) / cycle_s)
    else:
        cursor = t_start

    while cursor < t_end:
        for ph in range(n_phases):
            if cursor >= t_end: break
            is_bus = (ph == (bus_ph_1 - 1) % n_phases)
            pnum   = ph + 1
            if is_bus:
                end0 = cursor + bp_dur
                ext  = 0.0
                while ge_i < len(ge_q) and ge_q[ge_i][0] < end0 + ext:
                    if ge_q[ge_i][0] >= cursor: ext += ge_q[ge_i][1]
                    ge_i += 1
                bars.append((cursor, cursor + bp_dur, pnum, 'bus'))
                if ext > 0:
                    bars.append((cursor + bp_dur, cursor + bp_dur + ext, pnum, 'ge'))
                cursor += bp_dur + ext
            else:
                seg_s     = cursor
                phase_end = cursor + non_dur
                while ins_i < len(ins_q) and ins_q[ins_i][0] < phase_end:
                    t_ins, d_ins, _, bpv = ins_q[ins_i]
                    if t_ins >= seg_s:
                        if t_ins > seg_s:
                            bars.append((seg_s, t_ins, pnum, 'nonbus'))
                        bars.append((t_ins, t_ins + d_ins, bus_ph_1, 'ins'))
                        seg_s      = t_ins + d_ins
                        phase_end += d_ins
                    ins_i += 1
                if seg_s < phase_end:
                    bars.append((seg_s, phase_end, pnum, 'nonbus'))
                cursor = phase_end
        if n_phases == 1:
            clr_dur = max(0.0, cycle_s - bp_dur)
            if clr_dur > 0 and cursor < t_end:
                bars.append((cursor, cursor + clr_dur, 0, 'clearance'))
            cursor += clr_dur
    return bars

# ── Load all detection CSVs grouped by strategy name ──────────────────────────
def _load_strategies(log_dir):
    result, latest = {}, {}
    for path in glob.glob(os.path.join(log_dir, "detection_points_*.csv")):
        fname = os.path.basename(path)
        raw   = fname[len("detection_points_"):-len(".csv")]
        name  = re.sub(r'_\d{8}_\d{6}$', '', raw)
        mt    = os.path.getmtime(path)
        if name not in latest or mt > latest[name]:
            latest[name] = mt
            result[name] = _read_csv(path)
    return result

all_strategies = _load_strategies(_log_dir)
if not all_strategies:
    print("[plot_signal_timing] No detection_points_*.csv files found in", _log_dir)
    sys.exit(0)

notsp_label  = next((k for k in all_strategies if 'NO_TSP' in k), None)
strat_labels = sorted([k for k in all_strategies if k != notsp_label])
print(f"[plot_signal_timing] Strategies: NO_TSP={notsp_label}  others={strat_labels}")

# ── Full simulation time window ────────────────────────────────────────────────
_all_times = [_f(r.get("sim_time_s")) for rows in all_strategies.values()
              for r in rows if r.get("sim_time_s")]
t_show_end = max(_all_times) + 120.0 if _all_times else 4500.0

# ── Junction list and Y layout ─────────────────────────────────────────────────
jct_ids = sorted(INTERSECTIONS_CONFIG.keys())
ROW_H = 0.8
GAP   = 0.4
SLOT  = 3.0

def _y0(ji, row):
    return ji * SLOT + row * (ROW_H + GAP)

total_height = len(jct_ids) * SLOT + 0.5

# ── Cycle offset map ───────────────────────────────────────────────────────────
_all_rows_combined = [r for rows in all_strategies.values() for r in rows]
_cycle_offset_map  = {
    jct_id: _compute_cycle_offset(jct_id, cfg, _all_rows_combined)
    for jct_id, cfg in INTERSECTIONS_CONFIG.items()
}

# ── Extract events from detection rows ────────────────────────────────────────
def _extract_events(rows):
    """Return (ge, ins, gr, pr, arr) event lists."""
    ge, ins, gr, pr, arr = [], [], [], [], []
    for r in rows:
        tier = (r.get("tier") or "").strip().lower()
        jct  = int(_f(r.get("junction_id", 0)))
        t    = _f(r.get("sim_time_s", 0))
        sp   = int(_f(r.get("signal_phase", 0)))
        bp   = int(_f(r.get("bus_phase", 0)))
        note = r.get("prearm_note", "") or ""
        eta  = _f(r.get("prearm_eta_s", 0))
        stat = (r.get("prearm_status", "") or "").lower()

        if "harmony-ge" in tier or "dctsp_ge" in tier:
            dur = 0.0
            m = re.search(r'GE[\D_]*([\d.]+)', note)
            if m: dur = float(m.group(1))
            if dur == 0:
                for tok in note.split():
                    if tok.endswith("s") and tok[:-1].replace(".", "").isdigit():
                        dur = float(tok[:-1]); break
            ge.append((jct, t, dur, sp, bp))
        elif "harmony-ins" in tier or "dctsp_ins" in tier:
            dur = 20.0
            m = re.search(r'INS[\D]*([\d.]+)', note)
            if m: dur = float(m.group(1))
            ins.append((jct, t, dur, sp, bp))
        elif "harmony-no-ge" in tier:
            gr.append((jct, t, sp, bp, eta, note))
        elif "coord-prearm" in tier:
            pr.append((jct, t, sp, bp, stat, eta, note))
        elif tier == "ic-detect":
            arr.append((jct, t, sp, bp))
    return ge, ins, gr, pr, arr

# ── Build NO_TSP top-row shapes ───────────────────────────────────────────────
def _build_notsp_shapes():
    shapes = []
    for ji, jct_id in enumerate(jct_ids):
        cfg      = INTERSECTIONS_CONFIG.get(jct_id, {})
        cycle_s  = _f(cfg.get("cycle_length", 110))
        bp_dur   = _f(cfg.get("BusPhaseDuration", 30))
        bus_ph   = cfg.get("BusPhase", 1)
        n_phases = max(len(cfg.get("SignalGroupIDList", [])), 1)
        non_dur  = (cycle_s - bp_dur) / max(n_phases - 1, 1)
        y0n      = _y0(ji, 0)
        t0c      = _cycle_offset_map.get(jct_id, 0.0)
        t = (t0c + cycle_s * math.floor((0.0 - t0c) / cycle_s)) if cycle_s > 0 else 0.0
        while t < t_show_end:
            cursor = t
            for ph in range(n_phases):
                if cursor >= t + cycle_s: break
                if ph == (bus_ph - 1) % n_phases:
                    dur, col = bp_dur, "#81C784"
                else:
                    dur, col = non_dur, "#BBDEFB"
                shapes.append(dict(type="rect", xref="x", yref="y",
                    x0=cursor, x1=cursor + dur, y0=y0n, y1=y0n + ROW_H,
                    fillcolor=col, line=dict(width=0), layer="below"))
                cursor += dur
            if cursor < t + cycle_s:
                shapes.append(dict(type="rect", xref="x", yref="y",
                    x0=cursor, x1=t + cycle_s, y0=y0n, y1=y0n + ROW_H,
                    fillcolor="#CFD8DC", line=dict(width=0), layer="below"))
            t += cycle_s
    return shapes

notsp_shapes = _build_notsp_shapes()

# ── Build strategy bottom-row phase shapes ────────────────────────────────────
_BAR_COL = {"bus": "#4CAF50", "ge": "#FF9800", "nonbus": "#90CAF9",
            "ins": "#E53935", "clearance": "#CFD8DC"}
_BAR_BDR = {"bus": dict(width=0.3, color="#ccc"),  "ge":  dict(width=1, color="#E65100"),
            "nonbus": dict(width=0.3, color="#ccc"), "ins": dict(width=1, color="#B71C1C"),
            "clearance": dict(width=0)}
_BAR_OPA = {"bus": 1.0, "ge": 0.85, "nonbus": 1.0, "ins": 0.75, "clearance": 1.0}
_BAR_LYR = {"bus": "below", "ge": "above", "nonbus": "below", "ins": "above", "clearance": "below"}

def _build_strat_shapes(ge_events, ins_events):
    shapes = []
    for ji, jct_id in enumerate(jct_ids):
        cfg = INTERSECTIONS_CONFIG.get(jct_id, {})
        y0a = _y0(ji, 1)
        t0c = _cycle_offset_map.get(jct_id, 0.0)
        for (b_t0, b_t1, b_pnum, b_type) in _build_marl_phase_bars(
                jct_id, cfg, ge_events, ins_events, 0.0, t_show_end, t_cycle_0=t0c):
            shapes.append(dict(
                type="rect", xref="x", yref="y",
                x0=b_t0, x1=b_t1, y0=y0a, y1=y0a + ROW_H,
                fillcolor=_BAR_COL[b_type], line=_BAR_BDR[b_type],
                opacity=_BAR_OPA[b_type], layer=_BAR_LYR[b_type],
            ))
    return shapes

# ── Phase label text traces ────────────────────────────────────────────────────
def _build_notsp_label_trace():
    xs, ys, txts = [], [], []
    for ji, jct_id in enumerate(jct_ids):
        cfg      = INTERSECTIONS_CONFIG.get(jct_id, {})
        cycle_s  = _f(cfg.get("cycle_length", 110))
        bp_dur   = _f(cfg.get("BusPhaseDuration", 30))
        bus_ph   = cfg.get("BusPhase", 1)
        n_phases = max(len(cfg.get("SignalGroupIDList", [])), 1)
        non_dur  = (cycle_s - bp_dur) / max(n_phases - 1, 1)
        y0n      = _y0(ji, 0)
        t0c      = _cycle_offset_map.get(jct_id, 0.0)
        t = (t0c + cycle_s * math.floor((0.0 - t0c) / cycle_s)) if cycle_s > 0 else 0.0
        while t < t_show_end:
            cursor = t
            for ph in range(n_phases):
                if cursor >= t + cycle_s: break
                dur = bp_dur if ph == (bus_ph - 1) % n_phases else non_dur
                mid = cursor + dur / 2
                if 0.0 <= mid <= t_show_end:
                    xs.append(mid); ys.append(y0n + ROW_H / 2); txts.append(str(ph + 1))
                cursor += dur
            t += cycle_s
    return dict(type="scatter", mode="text", x=xs, y=ys, text=txts,
                textfont=dict(size=8, color="#1a5276"), hoverinfo="skip",
                showlegend=False, name="_notsp_ph_lbl", legendgroup="_ph_lbl")

def _build_strat_label_trace(ge_events, ins_events):
    xs, ys, txts = [], [], []
    for ji, jct_id in enumerate(jct_ids):
        cfg = INTERSECTIONS_CONFIG.get(jct_id, {})
        y0a = _y0(ji, 1)
        t0c = _cycle_offset_map.get(jct_id, 0.0)
        for (b_t0, b_t1, b_pnum, b_type) in _build_marl_phase_bars(
                jct_id, cfg, ge_events, ins_events, 0.0, t_show_end, t_cycle_0=t0c):
            if b_type != "clearance":
                xs.append((b_t0 + b_t1) / 2); ys.append(y0a + ROW_H / 2)
                txts.append(str(b_pnum))
    return dict(type="scatter", mode="text", x=xs, y=ys, text=txts,
                textfont=dict(size=8, color="#1b2631"), hoverinfo="skip",
                showlegend=False, name="_strat_ph_lbl", legendgroup="_ph_lbl")

# ── Build marker scatter traces ────────────────────────────────────────────────
def _arr_state(sp, bp):
    if sp > 0 and sp == bp: return "green"
    if sp > 0: return "red"
    return "unk"

def _build_marker_traces(ge_events, ins_events, gr_events, pr_events, arr_events,
                          row=1):
    """Build Plotly scatter traces for event markers on the given row (0=NO_TSP, 1=TSP)."""
    traces = []
    jct_set = set(jct_ids)

    # ── Bus arrivals, coloured by signal phase state ──────────────────────────
    for state, color, label in [
        ("green", "#2E7D32", "Arrival: green phase"),
        ("red",   "#C62828", "Arrival: red/non-bus"),
        ("unk",   "#757575", "Arrival: phase unknown"),
    ]:
        xs, ys, txts = [], [], []
        for (jj, t, sp, bp) in arr_events:
            if jj not in jct_set or _arr_state(sp, bp) != state: continue
            ji  = jct_ids.index(jj)
            yb  = _y0(ji, row)
            xs  += [t, t, None]
            ys  += [yb, yb + ROW_H, None]
            txts += [f"Arrival ({state}) t={t:.0f}s jct={jj} sp={sp} bp={bp}", "", ""]
        if xs:
            traces.append(dict(type="scatter", mode="lines",
                x=xs, y=ys, text=txts, hoverinfo="text",
                line=dict(color=color, width=1.5, dash="dot"),
                name=label, legendgroup=f"arr_{state}", showlegend=(row == 1)))

    if row == 0:   # NO_TSP row only needs arrival markers
        return traces

    # ── GE markers ────────────────────────────────────────────────────────────
    xs, ys, txts = [], [], []
    for (jj, t, dur, sp, bp) in ge_events:
        if jj not in jct_set: continue
        ji = jct_ids.index(jj)
        xs.append(t); ys.append(_y0(ji, 1) + ROW_H + 0.1)
        txts.append(f"GE +{dur:.0f}s @ t={t:.0f}s  jct={jj}  phase={sp}")
    if xs:
        traces.append(dict(type="scatter", mode="markers", x=xs, y=ys,
            hovertext=txts, hoverinfo="text",
            marker=dict(symbol="triangle-up", size=9, color="#FF9800",
                        line=dict(width=1, color="#E65100")),
            name="GE Green Extension", legendgroup="ge", showlegend=True))

    # ── INS markers ───────────────────────────────────────────────────────────
    xs, ys, txts = [], [], []
    for (jj, t, dur, sp, bp) in ins_events:
        if jj not in jct_set: continue
        ji = jct_ids.index(jj)
        xs.append(t); ys.append(_y0(ji, 1) + ROW_H + 0.1)
        txts.append(f"INS +{dur:.0f}s @ t={t:.0f}s  jct={jj}  inserted bp={bp}")
    if xs:
        traces.append(dict(type="scatter", mode="markers", x=xs, y=ys,
            hovertext=txts, hoverinfo="text",
            marker=dict(symbol="diamond", size=9, color="#E53935",
                        line=dict(width=1, color="#B71C1C")),
            name="INS Phase Insertion", legendgroup="ins", showlegend=True))

    # ── GR — natural green markers (bus arrived in green, no action needed) ───
    xs, ys, txts = [], [], []
    for (jj, t, sp, bp, eta, note) in gr_events:
        if jj not in jct_set: continue
        ji = jct_ids.index(jj)
        xs.append(t); ys.append(_y0(ji, 1) + ROW_H + 0.1)
        txts.append(f"GR natural green @ t={t:.0f}s  jct={jj}  +{eta:.1f}s rem in phase")
    if xs:
        traces.append(dict(type="scatter", mode="markers", x=xs, y=ys,
            hovertext=txts, hoverinfo="text",
            marker=dict(symbol="star", size=11, color="#00BFA5",
                        line=dict(width=1, color="#00897B")),
            name="GR Natural Green", legendgroup="gr", showlegend=True))

    # ── PR — prearm events by outcome ─────────────────────────────────────────
    for outcome, color, sym, label in [
        ("fired",   "#7B1FA2", "cross-open",       "PR Prearm fired"),
        ("success", "#388E3C", "triangle-up-open", "PR Prearm success"),
        ("missed",  "#D32F2F", "x-open",           "PR Prearm missed"),
    ]:
        xs, ys, txts = [], [], []
        for (jj, t, sp, bp, oc, eta, note) in pr_events:
            if oc != outcome or jj not in jct_set: continue
            ji = jct_ids.index(jj)
            xs.append(t); ys.append(_y0(ji, 1) + ROW_H * 1.9)
            eta_s = f"{eta:.1f}s" if eta else "?"
            txts.append(f"{label} @ t={t:.0f}s  jct={jj}  eta={eta_s}  {note}")
        if xs:
            traces.append(dict(type="scatter", mode="markers", x=xs, y=ys,
                hovertext=txts, hoverinfo="text",
                marker=dict(symbol=sym, size=9, color=color,
                            line=dict(width=1.5, color=color)),
                name=label, legendgroup=f"pr_{outcome}", showlegend=True))

    return traces

# ── Load wave events (periodic replan) for a strategy ─────────────────────────
def _load_wave_rows(strat_name):
    path = _latest(os.path.join(_log_dir, f"corridor_wave_events_{strat_name}_*.csv"))
    if not path:
        path = _latest(os.path.join(_log_dir, "corridor_wave_events_*.csv"))
    return _read_csv(path) if path else []

def _build_replan_trace(wave_rows):
    xs, ys, txts = [], [], []
    jct_set = set(jct_ids)
    for wr in wave_rows:
        evt = (wr.get("event") or "").strip().lower()
        if "periodic_replan" not in evt: continue
        tgt  = int(_f(wr.get("target_jct", wr.get("target_junction", 0))))
        t_ev = _f(wr.get("time_s", wr.get("sim_time_s", 0)))
        note = wr.get("note", "")
        m    = re.search(r'corr=([+-]?[\d.]+)', note)
        corr = float(m.group(1)) if m else 0.0
        if tgt not in jct_set: continue
        ji   = jct_ids.index(tgt)
        xs.append(t_ev); ys.append(_y0(ji, 1) + ROW_H / 2)
        txts.append(f"Forward OC {corr:+.1f}s @ t={t_ev:.0f}s  jct={tgt}")
    if not xs:
        return None
    return dict(type="scatter", mode="markers", x=xs, y=ys,
                hovertext=txts, hoverinfo="text",
                marker=dict(symbol="x", size=10, color="#7E57C2",
                            line=dict(width=2, color="#4527A0")),
                name="Periodic OC correction", legendgroup="replan", showlegend=True)

# ── Annotations and Y-tick labels ─────────────────────────────────────────────
ytick_vals = ([_y0(ji, 0) + ROW_H / 2 for ji in range(len(jct_ids))] +
              [_y0(ji, 1) + ROW_H / 2 for ji in range(len(jct_ids))])
ytick_text = ([f"INT{j} NO_TSP" for j in jct_ids] +
              [f"INT{j} TSP"    for j in jct_ids])

annotations = []
for ji, jct_id in enumerate(jct_ids):
    annotations.append(dict(
        x=-15, y=_y0(ji, 0) + ROW_H / 2, xref="x", yref="y",
        text=f"<b>{jct_id}</b><br><small>NO_TSP</small>",
        showarrow=False, xanchor="right", font=dict(size=9)))
    annotations.append(dict(
        x=-15, y=_y0(ji, 1) + ROW_H / 2, xref="x", yref="y",
        text=f"<b>{jct_id}</b><br><small>TSP</small>",
        showarrow=False, xanchor="right", font=dict(size=9)))

# ── Legend dummy traces (shapes can't appear in Plotly legend) ────────────────
legend_traces = [
    dict(type="scatter", mode="markers", x=[None], y=[None], showlegend=True,
         marker=dict(symbol="square", size=14, color="#81C784"),  name="Bus phase (NO_TSP)"),
    dict(type="scatter", mode="markers", x=[None], y=[None], showlegend=True,
         marker=dict(symbol="square", size=14, color="#BBDEFB"),  name="Non-bus (NO_TSP)"),
    dict(type="scatter", mode="markers", x=[None], y=[None], showlegend=True,
         marker=dict(symbol="square", size=14, color="#CFD8DC"),  name="All-red/clearance"),
    dict(type="scatter", mode="markers", x=[None], y=[None], showlegend=True,
         marker=dict(symbol="square", size=14, color="#4CAF50"),  name="Bus phase (TSP)"),
    dict(type="scatter", mode="markers", x=[None], y=[None], showlegend=True,
         marker=dict(symbol="square", size=14, color="#90CAF9"),  name="Non-bus (TSP)"),
    dict(type="scatter", mode="markers", x=[None], y=[None], showlegend=True,
         marker=dict(symbol="square", size=14, color="#FF9800"),  name="GE bar"),
    dict(type="scatter", mode="markers", x=[None], y=[None], showlegend=True,
         marker=dict(symbol="square", size=14, color="#E53935"),  name="INS bar"),
]

# ── Build NO_TSP base traces ───────────────────────────────────────────────────
notsp_rows = all_strategies.get(notsp_label, [])
_, _, _, _, notsp_arr = _extract_events(notsp_rows)
notsp_arr_traces  = _build_marker_traces([], [], [], [], notsp_arr, row=0)
notsp_lbl_trace   = _build_notsp_label_trace()
base_traces       = legend_traces + [notsp_lbl_trace] + notsp_arr_traces

# ── Build per-strategy data ────────────────────────────────────────────────────
strat_js_data = {}
for sname in strat_labels:
    rows = all_strategies.get(sname, [])
    ge, ins, gr, pr, arr = _extract_events(rows)
    shapes       = _build_strat_shapes(ge, ins)
    lbl_trace    = _build_strat_label_trace(ge, ins)
    mkt_traces   = _build_marker_traces(ge, ins, gr, pr, arr, row=1)
    wave_rows    = _load_wave_rows(sname)
    rp_trace     = _build_replan_trace(wave_rows)
    if rp_trace:
        mkt_traces.append(rp_trace)
    strat_js_data[sname] = {
        "shapes":      shapes,
        "labelTrace":  lbl_trace,
        "markerTraces": mkt_traces,
    }
    n_ge  = sum(1 for t in mkt_traces if t.get("legendgroup") == "ge")
    n_ins = sum(1 for t in mkt_traces if t.get("legendgroup") == "ins")
    n_gr  = sum(1 for t in mkt_traces if t.get("legendgroup") == "gr")
    n_pr  = sum(1 for t in mkt_traces if "pr_" in (t.get("legendgroup") or ""))
    print(f"  {sname}: {len(shapes)} shapes | GE={n_ge} INS={n_ins} GR={n_gr} PR={n_pr}")

# ── Base layout ───────────────────────────────────────────────────────────────
base_layout = {
    "title": {"text": "Signal Timing — select a strategy above", "x": 0.5},
    "xaxis": {
        "title": "Simulation time (s)",
        "range": [-30, t_show_end + 30],
        "tickmode": "linear", "dtick": 300,
    },
    "yaxis": {
        "tickvals": ytick_vals, "ticktext": ytick_text,
        "range": [-0.5, total_height],
        "tickfont": {"size": 9},
    },
    "annotations": annotations,
    "shapes": [],   # filled dynamically by JS
    "height": max(500, len(jct_ids) * 120 + 200),
    "hovermode": "closest",
    "legend": {"orientation": "h", "y": -0.12},
    "plot_bgcolor": "#F5F5F5",
    "margin": {"l": 130},
}

# ── Serialise everything to JSON ──────────────────────────────────────────────
notsp_shapes_json   = json.dumps(notsp_shapes,  default=str)
base_traces_json    = json.dumps(base_traces,   default=str)
strat_data_json     = json.dumps(strat_js_data, default=str)
base_layout_json    = json.dumps(base_layout,   default=str)
strat_labels_json   = json.dumps(strat_labels)
t_end_json          = json.dumps(round(t_show_end))
default_strat_json  = json.dumps(strat_labels[0] if strat_labels else "")

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<title>Signal Timing Diagram</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
body {{font-family:sans-serif;padding:12px 16px;background:#f5f5f5;margin:0}}
h2   {{margin:0 0 8px;font-size:16px;color:#1a237e}}
#controls {{
  background:white;border:1px solid #ddd;border-radius:6px;
  padding:8px 14px;margin-bottom:10px;
  display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:13px
}}
#controls label {{font-weight:600;color:#333;white-space:nowrap}}
#controls select,#controls input[type=number] {{
  font-size:13px;padding:3px 6px;border:1px solid #bbb;border-radius:4px
}}
#controls button {{
  padding:4px 12px;background:#2F5496;color:white;
  border:none;border-radius:4px;cursor:pointer;font-size:13px
}}
#controls button:hover {{background:#1a3c7a}}
.sep {{border-left:1px solid #ccc;align-self:stretch;margin:0 4px}}
.cbrow {{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.cbrow label {{font-weight:normal;cursor:pointer}}
#badge {{font-size:11px;background:#e8f0fe;border-radius:4px;padding:2px 8px;color:#174ea6;font-weight:600}}
#fig   {{background:white;border-radius:4px;border:1px solid #ddd}}
p.legend {{color:#555;font-size:11.5px;margin-top:6px;
           background:white;padding:8px 12px;border-radius:4px;border:1px solid #ddd}}
</style>
</head><body>
<h2>Signal Timing: NO_TSP (top) vs TSP strategy (bottom)</h2>

<div id="controls">
  <label>Strategy:</label>
  <select id="stratSel"></select>
  <span id="badge"></span>

  <div class="sep"></div>
  <label>Time (s):</label>
  <input type="number" id="tS" value="0"    step="100" style="width:72px">
  <span>–</span>
  <input type="number" id="tE" value="4500" step="100" style="width:72px">
  <button onclick="applyRange()">Zoom</button>
  <button onclick="resetRange()">Full</button>

  <div class="sep"></div>
  <label>Show:</label>
  <div class="cbrow">
    <label><input type="checkbox" id="cbGE"     checked onchange="redraw()"> <b style="color:#E65100">▲ GE</b> ext</label>
    <label><input type="checkbox" id="cbINS"    checked onchange="redraw()"> <b style="color:#B71C1C">◆ INS</b> ins</label>
    <label><input type="checkbox" id="cbGR"     checked onchange="redraw()"> <b style="color:#00897B">★ GR</b> nat.green</label>
    <label><input type="checkbox" id="cbPR"     checked onchange="redraw()"> <b style="color:#7B1FA2">+ PR</b> prearm</label>
    <label><input type="checkbox" id="cbArr"    checked onchange="redraw()"> Arrivals</label>
    <label><input type="checkbox" id="cbReplan" checked onchange="redraw()"> Replan</label>
    <label><input type="checkbox" id="cbLbl"    checked onchange="redraw()"> Phase#</label>
  </div>
</div>

<div id="fig"></div>

<p class="legend">
  <b>NO_TSP rows (top):</b>
  <span style="background:#81C784;padding:1px 6px;border-radius:2px">bus phase</span>
  <span style="background:#BBDEFB;padding:1px 6px;border-radius:2px">non-bus</span>
  <span style="background:#CFD8DC;padding:1px 6px;border-radius:2px">all-red</span>
  &nbsp;|&nbsp;
  <b>TSP rows (bottom):</b>
  <span style="background:#4CAF50;padding:1px 6px;border-radius:2px;color:white">bus phase</span>
  <span style="background:#FF9800;padding:1px 6px;border-radius:2px">GE bar</span>
  <span style="background:#E53935;padding:1px 6px;border-radius:2px;color:white">INS bar</span>
  &nbsp;|&nbsp;
  Markers above bars:
  <b style="color:#E65100">▲ GE</b> = green extension detected &nbsp;
  <b style="color:#B71C1C">◆ INS</b> = phase insertion &nbsp;
  <b style="color:#00BFA5">★ GR</b> = natural green (no TSP needed) &nbsp;
  <b style="color:#7B1FA2">+ PR fired</b> &nbsp;
  <b style="color:#388E3C">△ PR success</b> &nbsp;
  <b style="color:#D32F2F">× PR missed</b>
  &nbsp;|&nbsp;
  Dotted lines = bus arrivals (<span style="color:#2E7D32">green</span> = arrived in green phase,
  <span style="color:#C62828">red</span> = arrived in non-bus phase)
</p>

<script>
var notspShapes  = {notsp_shapes_json};
var baseTraces   = {base_traces_json};
var stratData    = {strat_data_json};
var baseLayout   = {base_layout_json};
var stratLabels  = {strat_labels_json};
var tShowEnd     = {t_end_json};
var defaultStrat = {default_strat_json};

// ── Populate dropdown ────────────────────────────────────────────────────────
var sel = document.getElementById('stratSel');
stratLabels.forEach(function(s) {{
  var o = document.createElement('option');
  o.value = s; o.text = s;
  if (s === defaultStrat) o.selected = true;
  sel.appendChild(o);
}});

// ── Filter helpers ───────────────────────────────────────────────────────────
function getFilter() {{
  return {{
    ge:     document.getElementById('cbGE').checked,
    ins:    document.getElementById('cbINS').checked,
    gr:     document.getElementById('cbGR').checked,
    pr:     document.getElementById('cbPR').checked,
    arr:    document.getElementById('cbArr').checked,
    replan: document.getElementById('cbReplan').checked,
    lbl:    document.getElementById('cbLbl').checked,
  }};
}}

var GROUP_FILTER = {{
  ge:          function(f){{ return f.ge; }},
  ins:         function(f){{ return f.ins; }},
  gr:          function(f){{ return f.gr; }},
  pr_fired:    function(f){{ return f.pr; }},
  pr_success:  function(f){{ return f.pr; }},
  pr_missed:   function(f){{ return f.pr; }},
  arr_green:   function(f){{ return f.arr; }},
  arr_red:     function(f){{ return f.arr; }},
  arr_unk:     function(f){{ return f.arr; }},
  replan:      function(f){{ return f.replan; }},
  _ph_lbl:     function(f){{ return f.lbl; }},
}};

function filterTraces(traces, flt) {{
  return traces.filter(function(t) {{
    var g = t.legendgroup || '';
    if (g in GROUP_FILTER) return GROUP_FILTER[g](flt);
    return true;   // legend dummy traces, unknown groups — always show
  }});
}}

// ── Main render ──────────────────────────────────────────────────────────────
function redraw() {{
  var sname  = document.getElementById('stratSel').value;
  var sd     = stratData[sname] || {{}};
  var flt    = getFilter();

  document.getElementById('badge').textContent = sname;

  // Build shapes: NO_TSP top rows (fixed) + strategy bottom rows
  var shapes = notspShapes.concat(sd.shapes || []);

  // Build layout
  var layout = JSON.parse(JSON.stringify(baseLayout));
  layout.shapes = shapes;
  layout.title.text = 'Signal Timing: NO_TSP vs ' + sname;

  // Apply current time range
  var t0 = parseFloat(document.getElementById('tS').value) || 0;
  var t1 = parseFloat(document.getElementById('tE').value) || tShowEnd;
  layout.xaxis.range = [t0 - 10, t1 + 10];

  // Build traces
  var traces = baseTraces.slice();           // legend dummies + NO_TSP arrivals + NO_TSP labels
  if (sd.labelTrace) traces.push(sd.labelTrace);
  if (sd.markerTraces) traces = traces.concat(sd.markerTraces);
  traces = filterTraces(traces, flt);

  Plotly.react('fig', traces, layout);
}}

function applyRange() {{ redraw(); }}

function resetRange() {{
  document.getElementById('tS').value = 0;
  document.getElementById('tE').value = tShowEnd;
  redraw();
}}

sel.addEventListener('change', redraw);

// ── Initial render ────────────────────────────────────────────────────────────
document.getElementById('tE').value = tShowEnd;
redraw();
</script>
</body></html>"""

with open(_out_html, "w", encoding="utf-8") as fh:
    fh.write(HTML)
print(f"[plot_signal_timing] written -> {_out_html}  ({len(strat_labels)} strategies)")
