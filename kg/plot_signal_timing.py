"""
Signal Timing Diagram: Original configured phase plan vs TSP-adjusted timings.

Two panels per intersection:
  Top row  — Original signal plan (repeating configured cycle, no TSP)
  Bottom row — Actual run: same nominal cycle but with GE/INS events overlaid
               and periodic_replan forward-OC corrections shown.

Data sources
------------
  INTERSECTIONS_CONFIG   — nominal phase durations and cycle length
  detection_points_*.csv — harmony-ge-local / harmony-ins-local tier events
  corridor_wave_events_*.csv — periodic_replan events

Usage:
    python plot_signal_timing.py [logs_dir] [out.html]
"""

import os, sys, csv, glob, json, math

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

# ── helpers ────────────────────────────────────────────────────────────────────
def _f(v, d=0.0):
    try: return float(v)
    except Exception: return d

def _latest(pattern):
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None

def _read_csv(path):
    if not path or not os.path.isfile(path): return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _compute_cycle_offset(jct_id, cfg, all_rows):
    """Return t_cycle_0: the time when the junction's cycle was at position 0.

    Uses the earliest detection row at jct_id that has a valid signal_phase
    (Aimsun 1-indexed stage number).  Assumes the detection occurs at the START
    of that stage.  If no usable row is found, returns 0.0 (cycle starts at
    phase 1 at t=0, the previous default behaviour).
    """
    cycle_s  = _f(cfg.get("cycle_length", 110))
    bp_dur   = _f(cfg.get("BusPhaseDuration", 30))
    bus_ph_1 = int(cfg.get("BusPhase", 1))
    n_phases = max(len(cfg.get("SignalGroupIDList", [])), 1)
    non_dur  = (cycle_s - bp_dur) / max(n_phases - 1, 1)

    # Cumulative start position for each 0-indexed phase
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

    r0    = candidates[0]
    t_det = _f(r0.get("sim_time_s", 0))
    sp    = int(_f(r0.get("signal_phase", 1)))   # 1-indexed Aimsun stage
    ph_idx = (sp - 1) % n_phases                  # 0-indexed phase
    # Assume the detection falls at the very start of that phase
    t_cycle_0 = t_det - phase_starts[ph_idx]
    return t_cycle_0

# ── Load CSVs — explicitly pick DCTSP_MARL and NO_TSP for comparison ───────────
_marl_det_path  = _latest(os.path.join(_log_dir, "detection_points_DCTSP_MARL_*.csv"))
_notsp_det_path = _latest(os.path.join(_log_dir, "detection_points_NO_TSP_*.csv"))
_wave_path      = _latest(os.path.join(_log_dir, "corridor_wave_events_DCTSP_MARL_*.csv"))
if not _wave_path:
    _wave_path  = _latest(os.path.join(_log_dir, "corridor_wave_events_*.csv"))
# Fall back to latest CSV if specific experiments not found
if not _marl_det_path:
    _marl_det_path = _latest(os.path.join(_log_dir, "detection_points_*.csv"))

det_rows   = _read_csv(_marl_det_path)    # DCTSP_MARL — GE/INS events + bus arrivals
notsp_rows = _read_csv(_notsp_det_path)   # NO_TSP     — bus arrivals only
wave_rows  = _read_csv(_wave_path)

print(f"[plot_signal_timing] DCTSP_MARL detections: {len(det_rows)} rows  ({_marl_det_path})")
print(f"[plot_signal_timing] NO_TSP detections:     {len(notsp_rows)} rows  ({_notsp_det_path})")
print(f"[plot_signal_timing] wave events:           {len(wave_rows)} rows ({_wave_path})")

# ── Per-junction cycle offsets from first detection signal_phase ──────────────
# Combined pool: use whichever run provides the earliest signal_phase reading.
_all_det_rows_combined = det_rows + notsp_rows
_cycle_offset_map = {}   # {jct_id: t_cycle_0}
for _jct_key, _jcfg in INTERSECTIONS_CONFIG.items():
    _cycle_offset_map[_jct_key] = _compute_cycle_offset(
        _jct_key, _jcfg, _all_det_rows_combined
    )

# ── Extract GE / INS events from detection CSV ────────────────────────────────
ge_events  = []   # (jct_id, sim_time, ge_s, signal_phase, bus_phase)
ins_events = []   # (jct_id, sim_time, ins_s, signal_phase, bus_phase)
for r in det_rows:
    tier = r.get("tier", "").strip().lower()
    jct  = int(_f(r.get("junction_id", 0)))
    t    = _f(r.get("sim_time_s", 0))
    note = r.get("prearm_note", "")
    sp   = int(_f(r.get("signal_phase", 0)))
    bpv  = int(_f(r.get("bus_phase", 0)))
    if "harmony-ge" in tier or "dctsp_ge" in tier:
        # parse duration from prearm_note: "GE 10.0s R=..." or "DCTSP GE_10s ..."
        dur = 0.0
        for tok in note.replace("GE_", "GE ").split():
            if tok.startswith("GE") or (dur == 0 and tok[:-1].replace(".","").isdigit()):
                pass
            try:
                if tok.endswith("s") and tok[:-1].replace(".","").isdigit():
                    dur = float(tok[:-1])
                    break
            except Exception:
                pass
        if dur == 0:
            import re
            m = re.search(r'GE\D*([\d.]+)', note)
            if m: dur = float(m.group(1))
        ge_events.append((jct, t, dur, sp, bpv))
    elif "harmony-ins" in tier or "dctsp_ins" in tier:
        dur = 20.0
        import re
        m = re.search(r'INS\D*([\d.]+)', note)
        if m: dur = float(m.group(1))
        ins_events.append((jct, t, dur, sp, bpv))

# ── Extract periodic_replan events from wave CSV ──────────────────────────────
replan_events = []  # (tgt_jct, sim_time, correction_s)
for r in wave_rows:
    evt = r.get("event", "").strip().lower()
    if "periodic_replan" not in evt:
        continue
    tgt = int(_f(r.get("target_jct", r.get("target_junction", 0))))
    t   = _f(r.get("time_s", r.get("sim_time_s", 0)))
    note = r.get("note", "")
    import re
    m = re.search(r'corr=([+-]?[\d.]+)', note)
    corr = float(m.group(1)) if m else 0.0
    replan_events.append((tgt, t, corr))

# ── Bus arrival markers — IC-detect events from both experiments ─────────────────
def _bus_arrivals(rows):
    """Return sorted list of (jct_id, sim_time_s) for IC-detect bus entries."""
    out = []
    for r in rows:
        tier = (r.get("tier") or "").strip().lower()
        if tier == "ic-detect":
            jct = int(_f(r.get("junction_id", 0)))
            t   = _f(r.get("sim_time_s", 0))
            if jct > 0 and t > 0:
                out.append((jct, t))
    return sorted(out, key=lambda x: x[1])

marl_arrivals  = _bus_arrivals(det_rows)
notsp_arrivals = _bus_arrivals(notsp_rows)

# ── Full simulation time window ─────────────────────────────────────────────────
# Use complete sim duration rather than just the window around TSP events so
# the user can see the entire signal plan for both experiments.
_all_det_times = ([_f(r.get("sim_time_s")) for r in det_rows + notsp_rows
                   if r.get("sim_time_s")])
t_show_start = 0.0
t_show_end   = max(_all_det_times) + 120.0 if _all_det_times else 4500.0

# ── Build Plotly shapes + traces ───────────────────────────────────────────────
PHASE_COLOURS = {
    "bus":      "#4CAF50",   # green  — bus phase
    "other":    "#90CAF9",   # light blue — non-bus phases
    "ge_ext":   "#FF9800",   # orange — GE extension
    "ins":      "#E53935",   # red    — phase insertion
    "replan":   "#7E57C2",   # purple — periodic OC correction
    "nominal":  "#E0E0E0",   # light grey — nominal cycle (top row)
    "other_nom":"#BBDEFB",   # pale blue — non-bus nominal
}

# ── Reconstruct actual DCTSP_MARL phase sequence ─────────────────────────────
def _build_marl_phase_bars(jct_id, cfg, ge_evts, ins_evts, t_start, t_end,
                            t_cycle_0=0.0):
    """Walk the signal plan phase-by-phase, extending bus phases for GE events
    and inserting extra bus phases for INS events so that subsequent bars shift
    in time relative to the NO_TSP nominal row.
    Returns list of (t0, t1, phase_num_1indexed, bar_type)
    where bar_type in {'bus', 'ge', 'nonbus', 'ins', 'clearance'}.

    t_cycle_0: time at which the junction's signal cycle was at position 0.
    The cursor starts at the beginning of the cycle that contains t_start so
    the diagram reflects the correct initial phase offset.
    """
    cycle_s  = _f(cfg.get("cycle_length", 110))
    bp_dur   = _f(cfg.get("BusPhaseDuration", 30))
    bus_ph_1 = int(cfg.get("BusPhase", 1))
    n_phases = max(len(cfg.get("SignalGroupIDList", [])), 1)
    non_dur  = (cycle_s - bp_dur) / max(n_phases - 1, 1)

    ge_q  = sorted([(t, d, sp, bp) for (jj, t, d, sp, bp) in ge_evts  if jj == jct_id])
    ins_q = sorted([(t, d, sp, bp) for (jj, t, d, sp, bp) in ins_evts if jj == jct_id])
    ge_i = ins_i = 0
    bars   = []

    # Start at the beginning of the cycle that contains t_start so the initial
    # phase matches the actual Aimsun signal state at t_start.
    if cycle_s > 0 and t_cycle_0 != 0.0:
        cycles_before = math.floor((t_start - t_cycle_0) / cycle_s)
        cursor = t_cycle_0 + cycles_before * cycle_s
    else:
        cursor = t_start

    while cursor < t_end:
        for ph in range(n_phases):
            if cursor >= t_end:
                break
            is_bus = (ph == (bus_ph_1 - 1) % n_phases)
            pnum   = ph + 1
            if is_bus:
                end0 = cursor + bp_dur
                ext  = 0.0
                while ge_i < len(ge_q) and ge_q[ge_i][0] < end0 + ext:
                    if ge_q[ge_i][0] >= cursor:
                        ext += ge_q[ge_i][1]
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
        # n_phases==1: the for loop only draws the bus phase (bp_dur seconds).
        # Add the remaining clearance (all-red inter-green) so cycles advance
        # at the correct rate and GE events fall into the right bus phase window.
        if n_phases == 1:
            clr_dur = max(0.0, cycle_s - bp_dur)
            if clr_dur > 0 and cursor < t_end:
                bars.append((cursor, cursor + clr_dur, 0, 'clearance'))
            cursor += clr_dur
    return bars

jct_ids = sorted(set(e[0] for e in ge_events + ins_events + replan_events)
                 | set(INTERSECTIONS_CONFIG.keys()))

shapes  = []
annotations = []
traces_plotly = []

# Phase number label accumulators — scatter text traces, readable on zoom-in
_ph_xs_notsp, _ph_ys_notsp, _ph_txt_notsp = [], [], []
_ph_xs_marl,  _ph_ys_marl,  _ph_txt_marl  = [], [], []

# Y layout: each intersection gets a 2-row slot (nominal on top, actual below)
# row_y: jct_index × 3 + 0 = nominal, × 3 + 1 = actual
ROW_H = 0.8   # bar height
GAP   = 0.4   # gap between rows
SLOT  = 3.0   # total slot height per intersection

def _y0(jct_idx, row):
    """row=0 nominal, row=1 actual"""
    base = jct_idx * SLOT
    return base + row * (ROW_H + GAP)

total_height = len(jct_ids) * SLOT + 0.5

for ji, jct_id in enumerate(jct_ids):
    cfg      = INTERSECTIONS_CONFIG.get(jct_id, {})
    cycle_s  = _f(cfg.get("cycle_length", 110))
    bp_dur   = _f(cfg.get("BusPhaseDuration", 30))
    bus_ph   = cfg.get("BusPhase", 1)
    phases   = cfg.get("SignalGroupIDList", [])
    n_phases = max(len(phases), 1)
    non_bus_dur = (cycle_s - bp_dur) / max(n_phases - 1, 1)

    # ── NOMINAL cycle (top row) ────────────────────────────────────────────
    y0n = _y0(ji, 0)
    # Use the per-junction cycle offset so the nominal plan starts at the
    # correct initial phase (not always phase 1 at t=0).
    _t_cycle_0 = _cycle_offset_map.get(jct_id, 0.0)
    # First cycle boundary at or before t_show_start
    _t_nom_first = (_t_cycle_0 + cycle_s * math.floor((t_show_start - _t_cycle_0) / cycle_s)
                    if cycle_s > 0 else t_show_start)
    t = _t_nom_first
    while t < t_show_end:
        bp_start = t
        cursor = bp_start
        for ph in range(n_phases):
            if cursor >= min(t_show_end, bp_start + cycle_s):
                break
            if ph == (bus_ph - 1) % n_phases:
                dur = bp_dur
                col = "#81C784"  # lighter green for nominal bus phase
            else:
                dur = non_bus_dur
                col = "#BBDEFB"
            # Only draw the visible portion of this bar
            seg_x0 = max(cursor, t_show_start)
            seg_x1 = min(cursor + dur, t_show_end)
            if seg_x0 < seg_x1:
                shapes.append(dict(
                    type="rect", xref="x", yref="y",
                    x0=seg_x0, x1=seg_x1,
                    y0=y0n, y1=y0n + ROW_H,
                    fillcolor=col, line=dict(width=0),
                    layer="below",
                ))
            _ph_xs_notsp.append(cursor + dur / 2)
            _ph_ys_notsp.append(y0n + ROW_H / 2)
            _ph_txt_notsp.append(str(ph + 1))
            cursor += dur
        # Draw clearance if cycle time remains (covers n_phases==1 intersections)
        if cursor < bp_start + cycle_s and cursor < t_show_end:
            shapes.append(dict(
                type="rect", xref="x", yref="y",
                x0=max(cursor, t_show_start), x1=min(bp_start + cycle_s, t_show_end),
                y0=y0n, y1=y0n + ROW_H,
                fillcolor="#CFD8DC", line=dict(width=0),
                layer="below",
            ))
        t += cycle_s

    annotations.append(dict(
        x=t_show_start - 5, y=y0n + ROW_H / 2,
        xref="x", yref="y",
        text=f"<b>INT{jct_id}</b><br><i>NO_TSP</i>",
        showarrow=False, xanchor="right", font=dict(size=9),
    ))

    # ── ACTUAL cycle (bottom row) — GE/INS-adjusted phase reconstruction ──────
    y0a = _y0(ji, 1)
    _BAR_COL = {"bus": "#4CAF50",               "ge": PHASE_COLOURS["ge_ext"],
                "nonbus": "#90CAF9",             "ins": PHASE_COLOURS["ins"],
                "clearance": "#CFD8DC"}
    _BAR_BDR = {"bus": dict(width=0.3, color="#ccc"), "ge":  dict(width=1, color="#E65100"),
                "nonbus": dict(width=0.3, color="#ccc"), "ins": dict(width=1, color="#B71C1C"),
                "clearance": dict(width=0)}
    _BAR_OPA = {"bus": 1.0, "ge": 0.85, "nonbus": 1.0, "ins": 0.75, "clearance": 1.0}
    _BAR_LYR = {"bus": "below", "ge": "above", "nonbus": "below", "ins": "above", "clearance": "below"}
    for (b_t0, b_t1, b_pnum, b_type) in _build_marl_phase_bars(
            jct_id, cfg, ge_events, ins_events, t_show_start, t_show_end,
            t_cycle_0=_t_cycle_0):
        shapes.append(dict(
            type="rect", xref="x", yref="y",
            x0=b_t0, x1=b_t1,
            y0=y0a, y1=y0a + ROW_H,
            fillcolor=_BAR_COL[b_type], line=_BAR_BDR[b_type],
            opacity=_BAR_OPA[b_type], layer=_BAR_LYR[b_type],
        ))
        if b_type != 'clearance':   # don't label all-red gaps
            _ph_xs_marl.append((b_t0 + b_t1) / 2)
            _ph_ys_marl.append(y0a + ROW_H / 2)
            _ph_txt_marl.append(str(b_pnum))

    annotations.append(dict(
        x=t_show_start - 5, y=y0a + ROW_H / 2,
        xref="x", yref="y",
        text=f"<b>INT{jct_id}</b><br><i>DCTSP_MARL</i>",
        showarrow=False, xanchor="right", font=dict(size=9),
    ))

    # ── Bus arrival markers (dotted vertical lines) ────────────────────────────
    # NO_TSP arrivals on the NO_TSP row, DCTSP_MARL arrivals on the DCTSP row.
    for (jj, t_arr) in notsp_arrivals:
        if jj == jct_id and t_show_start <= t_arr <= t_show_end:
            shapes.append(dict(
                type="line", xref="x", yref="y",
                x0=t_arr, x1=t_arr,
                y0=y0n, y1=y0n + ROW_H,
                line=dict(color="#1B5E20", width=1.5, dash="dot"),
                layer="above",
            ))
    for (jj, t_arr) in marl_arrivals:
        if jj == jct_id and t_show_start <= t_arr <= t_show_end:
            shapes.append(dict(
                type="line", xref="x", yref="y",
                x0=t_arr, x1=t_arr,
                y0=y0a, y1=y0a + ROW_H,
                line=dict(color="#1B5E20", width=1.5, dash="dot"),
                layer="above",
            ))

    # ── GE detection markers (bars already drawn in _build_marl_phase_bars) ────
    ge_xs, ge_ys, ge_texts = [], [], []
    for (jj, t_ev, dur, _ge_sp, _ge_bp) in ge_events:
        if jj != jct_id or not (t_show_start <= t_ev <= t_show_end):
            continue
        _lbl = str(_ge_sp) if _ge_sp > 0 else str(bus_ph)
        ge_xs.append(t_ev)
        ge_ys.append(y0a + ROW_H)
        ge_texts.append(f"GE detected t={t_ev:.0f}s +{dur:.0f}s  jct={jct_id}  phase={_lbl}")

    if ge_xs:
        traces_plotly.append(dict(
            type="scatter", mode="markers",
            x=ge_xs, y=ge_ys,
            hovertext=ge_texts, hoverinfo="text",
            marker=dict(symbol="triangle-up", size=8,
                        color=PHASE_COLOURS["ge_ext"]),
            name="GE extension" if ji == 0 else None,
            showlegend=(ji == 0),
        ))

    # ── INS detection markers (bars already drawn in _build_marl_phase_bars) ───
    ins_xs, ins_ys, ins_texts = [], [], []
    for (jj, t_ev, dur, _ins_sp, _ins_bp) in ins_events:
        if jj != jct_id or not (t_show_start <= t_ev <= t_show_end):
            continue
        _ins_lbl = str(_ins_bp) if _ins_bp > 0 else str(bus_ph)
        ins_xs.append(t_ev)
        ins_ys.append(y0a + ROW_H)
        ins_texts.append(f"INS detected t={t_ev:.0f}s +{dur:.0f}s  jct={jct_id}  phase={_ins_lbl}")

    if ins_xs:
        traces_plotly.append(dict(
            type="scatter", mode="markers",
            x=ins_xs, y=ins_ys,
            hovertext=ins_texts, hoverinfo="text",
            marker=dict(symbol="diamond", size=8, color=PHASE_COLOURS["ins"]),
            name="Phase insertion" if ji == 0 else None,
            showlegend=(ji == 0),
        ))

    # ── Periodic replan corrections ────────────────────────────────────────
    rp_xs, rp_ys, rp_texts = [], [], []
    for (jj, t_ev, corr) in replan_events:
        if jj != jct_id or not (t_show_start <= t_ev <= t_show_end):
            continue
        rp_xs.append(t_ev)
        rp_ys.append(y0a + ROW_H / 2)
        rp_texts.append(f"Forward OC {corr:+.1f}s @ t={t_ev:.0f}s  jct={jct_id}")

    if rp_xs:
        traces_plotly.append(dict(
            type="scatter", mode="markers",
            x=rp_xs, y=rp_ys,
            hovertext=rp_texts, hoverinfo="text",
            marker=dict(symbol="x", size=10, color=PHASE_COLOURS["replan"],
                        line=dict(width=2)),
            name="Periodic OC correction" if ji == 0 else None,
            showlegend=(ji == 0),
        ))

# ── Phase number labels (scatter text — zoom in to read) ─────────────────────
traces_plotly.append(dict(
    type="scatter", mode="text",
    x=_ph_xs_notsp, y=_ph_ys_notsp,
    text=_ph_txt_notsp,
    textfont=dict(size=8, color="#1a5276"),
    hoverinfo="skip",
    showlegend=False,
    name="_phase_labels_notsp",
))
traces_plotly.append(dict(
    type="scatter", mode="text",
    x=_ph_xs_marl, y=_ph_ys_marl,
    text=_ph_txt_marl,
    textfont=dict(size=8, color="#1b2631"),
    hoverinfo="skip",
    showlegend=False,
    name="_phase_labels_marl",
))

# ── Legend dummy traces ────────────────────────────────────────────────────────
for label, colour, symbol in [
    ("Bus phase (NO_TSP)",      "#81C784",              "square"),
    ("All-red / clearance",     "#CFD8DC",              "square"),
    ("Bus phase (DCTSP_MARL)",  PHASE_COLOURS["bus"],   "square"),
    ("Non-bus (DCTSP_MARL)",    PHASE_COLOURS["other"], "square"),
    ("GE extension (DCTSP)",    PHASE_COLOURS["ge_ext"],"square"),
    ("Phase insertion (DCTSP)", PHASE_COLOURS["ins"],   "square"),
    ("Bus arrival (IC-detect)", "#1B5E20",              "line-ew-open"),
]:
    traces_plotly.insert(0, dict(
            type="scatter", mode="markers",
            x=[None], y=[None],
            marker=dict(symbol=symbol, size=12, color=colour),
            name=label, showlegend=True,
        ))

ytick_vals  = [_y0(ji, 0) + ROW_H/2 for ji in range(len(jct_ids))]
ytick_vals += [_y0(ji, 1) + ROW_H/2 for ji in range(len(jct_ids))]
ytick_text  = [f"INT{j} NO_TSP"     for j in jct_ids] + [f"INT{j} DCTSP_MARL" for j in jct_ids]

layout = {
    "title": {"text": "Signal Timing: NO_TSP (fixed plan) vs DCTSP_MARL — Full Simulation", "x": 0.5},
    "xaxis": {"title": "Simulation time (s)", "range": [t_show_start - 30, t_show_end + 30],
              "tickmode": "linear", "dtick": 300},  # major tick every 5 min
    "yaxis": {
        "tickvals": ytick_vals, "ticktext": ytick_text,
        "range": [-0.5, total_height],
        "tickfont": {"size": 9},
    },
    "shapes": shapes,
    "annotations": annotations,
    "height": max(400, len(jct_ids) * 120 + 120),
    "hovermode": "closest",
    "legend": {"orientation": "h", "y": -0.12},
    "plot_bgcolor": "#F5F5F5",
}

fig_json = json.dumps({"data": traces_plotly, "layout": layout}, default=str)

HTML = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<title>Signal Timing Diagram</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
</head><body style="font-family:sans-serif;padding:16px">
<h2>Signal Timing: NO_TSP vs DCTSP_MARL — Full Simulation</h2>
<p style="color:#555;max-width:960px">
  Each intersection has two rows: <b>NO_TSP</b> (top) shows the fixed-time
  signal plan with the correct bus phase (green), non-bus phases (blue) and
  all-red clearance (light grey) repeating throughout the simulation.
  <b>DCTSP_MARL</b> (bottom) shows the same base plan but with TSP
  modifications applied in real time — <b style="color:#FF9800">orange GE
  bars</b> appear immediately after the bus phase when it was held green longer
  (the detection triangle marks when the bus was spotted), and
  <b style="color:#E53935">red INS bars</b> appear where an extra bus-phase
  was inserted mid-cycle. Every GE/INS event shifts ALL subsequent phase bars
  right relative to the NO_TSP row — zoom into any intersection to see the
  accumulated offset clearly.
  <b style="color:#1B5E20">Dotted green lines</b> mark bus arrivals
  (IC-detect). Phase numbers are labelled in each bar — zoom in to read them.
  Note: offset-correction (&times;) markers require a
  <code>corridor_wave_events_*.csv</code> log file; none was found for this run.
</p>
<div id="fig"></div>
<script>
var fig = {fig_json};
Plotly.newPlot('fig', fig['data'], fig['layout'], {{responsive:true}});
</script>
</body></html>"""

with open(_out_html, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"[plot_signal_timing] written -> {_out_html}")
