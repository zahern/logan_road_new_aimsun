"""
Bargaining-game TSP dashboard.

Reads the latest reward_cycle_DCTSP_BARGAIN_SPM_*.csv and produces an
interactive HTML dashboard visualising:
  1. Action distribution heatmap per junction
  2. Bargaining utility decomposition (bus benefit vs car cost vs fairness)
  3. Detection-to-action scatter (bus ETA vs no-action delay, coloured by action)
  4. Per-junction reward timeline
  5. Cooperative fairness radar

Usage:  python plot_bargain_dashboard.py [--csv path/to/reward_cycle.csv]
Output: bargain_game_dashboard.html
"""
import argparse, csv, glob, json, os, statistics, collections, math

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main(csv_path=None):
    """Generate bargain_game_dashboard.html from the latest (or supplied) reward_cycle CSV.

    Parameters
    ----------
    csv_path : str, optional
        Explicit path to a reward_cycle CSV.  When None the latest
        reward_cycle_DCTSP_BARGAIN_SPM_*.csv in logs/ is used.
    """
    # ── locate latest reward_cycle -----------------------------------------------
    if csv_path:
        fn = csv_path
    else:
        logs_dir = os.path.join(SCRIPT_DIR, "logs")
        files = sorted(
            glob.glob(os.path.join(logs_dir, "reward_cycle_DCTSP_BARGAIN_SPM_*.csv")),
            key=os.path.getmtime,
        )
        if not files:
            print("[bargain_dashboard] No reward_cycle_DCTSP_BARGAIN_SPM_*.csv found in logs/ — skipping")
            return None
        fn = files[-1]

    print(f"[bargain_dashboard] reading {fn}")
    raw = list(csv.DictReader(open(fn, newline="", encoding="utf-8")))

# ── helpers -------------------------------------------------------------------
    def fv(r, k, default=0.0):
        v = r.get(k, "")
        try:
            return float(v) if v not in ("", None) else default
        except ValueError:
            return default

    def ens_delay(r):
        """Return ensemble_delay_s if present in the CSV (new runs), else fall
        back to no_act_delay_s (old CSVs that predate BG_MB_WEIGHT)."""
        ed = fv(r, "ensemble_delay_s", -1.0)
        return ed if ed >= 0.0 else fv(r, "no_act_delay_s")

    # action display ordering
    ACTION_ORDER = ["GE_5", "GE_10", "GE_15", "GR_5", "GR_10", "GR_15",
                    "INS_10", "INS_15", "INS_20", "INS_PRETERM_10", "INS_PRETERM_15",
                    "INS_PRETERM_20",
                    "ER_10", "ER_20", "ER_30",
                    "ER_BP_10", "ER_BP_20", "ER_BP_30",
                    "NO_ACTION"]
    ACTION_COLORS = {
        "GE_5":           "#22c55e",  # green-500
        "GE_10":          "#16a34a",  # green-600
        "GE_15":          "#15803d",  # green-700
        "GR_5":           "#a3e635",  # lime-400
        "GR_10":          "#84cc16",  # lime-500
        "GR_15":          "#65a30d",  # lime-600
        "INS_10":         "#3b82f6",  # blue-500
        "INS_15":         "#2563eb",  # blue-600
        "INS_20":         "#1d4ed8",  # blue-700
        "INS_PRETERM_10": "#8b5cf6",  # violet-500
        "INS_PRETERM_15": "#7c3aed",  # violet-600
        "INS_PRETERM_20": "#6d28d9",  # violet-700
        "ER_10":          "#fbbf24",  # amber-400
        "ER_20":          "#f59e0b",  # amber-500
        "ER_30":          "#d97706",  # amber-600
        "ER_BP_10":       "#f87171",  # red-400
        "ER_BP_20":       "#ef4444",  # red-500
        "ER_BP_30":       "#dc2626",  # red-600
        "NO_ACTION":      "#e5e7eb",  # gray-200
    }

    # ── filter chosen rows --------------------------------------------------------
    chosen = [r for r in raw if r.get("is_chosen", "0") == "1"]
    all_junctions = sorted(set(r["junction_id"] for r in chosen))

    # ── 1. ACTION DISTRIBUTION per junction (heatmap data) ----------------------
    action_counts = {}   # {jct: {action: n}}
    for r in chosen:
        j = r["junction_id"]
        a = r["action"]
        action_counts.setdefault(j, collections.Counter())[a] += 1

    # unique actions present
    present_actions = sorted(
        set(a for c in action_counts.values() for a in c),
        key=lambda x: (ACTION_ORDER.index(x) if x in ACTION_ORDER else 99)
    )
    present_actions_active = [a for a in present_actions if a != "NO_ACTION"]

    heat_jct_labels = all_junctions
    heat_action_labels = present_actions
    heat_matrix = []
    for act in present_actions:
        row_vals = [action_counts.get(j, {}).get(act, 0) for j in all_junctions]
        heat_matrix.append(row_vals)

    # ── 2. UTILITY DECOMPOSITION scatter (bus saved vs car cost, by action) ------
    scatter_points = []
    for r in [x for x in chosen if x["action"] != "NO_ACTION"]:
        scatter_points.append({
            "x":      round(fv(r, "other_inc_pax_s"), 1),    # car disruption pax·s
            "y":      round(fv(r, "bus_saved_pax_s"), 1),    # bus saved pax·s
            "jct":    r["junction_id"],
            "action": r["action"],
            "delay":  round(fv(r, "no_act_delay_s"), 1),
            "t":      round(fv(r, "sim_time_s"), 0),
            "eta":    round(fv(r, "bus_eta_s"), 1),
            "reward": round(fv(r, "reward"), 3),
        })

    scatter_by_action = {}
    for pt in scatter_points:
        scatter_by_action.setdefault(pt["action"], []).append(pt)

    # ── 2b. ALL-EVALUATED by action (for reward bar chart; includes non-chosen) ---
    # Three groups with different inclusion rules:
    #  • ER_BP (cut bus phase for cross-traffic benefit): operates when bus delay=0;
    #    the delay filter would hide all such rows.  Include all ER_BP rows.
    #    bus_saved=0 is expected (cross-traffic gains, bus unaffected).
    #  • GE / GR / ER / INS: require no_act_delay_s > 10 AND bus_saved >= 0.
    #    The delay filter removes rows where no priority was needed.
    #    The bus_saved >= 0 filter removes wrong-phase evaluations and right-phase
    #    misses (action too short to catch the green) whose bus_saved = -action_s×occ
    #    appear as a dense cluster of -200/-400/-600 points that dominate the chart.
    ER_BP_TYPES = {"ER_BP_10", "ER_BP_20", "ER_BP_30"}
    eval_by_action = {}
    for r in raw:
        act = r.get("action", "")
        if not act or act == "NO_ACTION":
            continue
        delay = fv(r, "no_act_delay_s")
        if act not in ER_BP_TYPES:
            if delay <= 10.0:
                continue      # skip near-zero-delay rows for bus-benefit actions
            if fv(r, "bus_saved_pax_s") < 0.0:
                continue      # skip wrong-phase / too-short evaluations (bus hurt)
        ep = {
            "x":      round(fv(r, "other_inc_pax_s"), 1),
            "y":      round(fv(r, "bus_saved_pax_s"), 1),
            "reward": round(fv(r, "reward"), 3),
        }
        eval_by_action.setdefault(act, []).append(ep)
    eval_actions_active = sorted(
        eval_by_action.keys(),
        key=lambda x: (ACTION_ORDER.index(x) if x in ACTION_ORDER else 99)
    )

    # ── 3. DETECTION scatter: bus_eta vs ensemble_delay, colored by action --------
    det_all = []
    for r in chosen:
        det_all.append({
            "x":      round(fv(r, "bus_eta_s"), 1),
            "y":      round(ens_delay(r), 1),   # ensemble (mb-blend); falls back to kinematic
            "action": r["action"],
            "jct":    r["junction_id"],
        })
    det_by_action = {}
    for pt in det_all:
        det_by_action.setdefault(pt["action"], []).append(pt)

    # ── 4. TIMELINE per junction: sim_time vs ensemble_delay (only active) ------
    timeline = {}
    for r in [x for x in chosen if x["action"] != "NO_ACTION"]:
        j = r["junction_id"]
        timeline.setdefault(j, []).append({
            "t":      round(fv(r, "sim_time_s"), 0),
            "delay":  round(ens_delay(r), 1),   # ensemble (mb-blend)
            "action": r["action"],
            "saved":  round(fv(r, "bus_saved_pax_s"), 1),
        })

    # ── 5. RADAR: per-junction summary metrics -----------------------------------
    radar_metrics = ["AvgBusDelay", "ActionRate%", "ExtFraction%",
                     "AvgBusSaved", "AvgCarPaxS"]
    radar_jct = []
    for j in all_junctions:
        jrows = [r for r in chosen if r["junction_id"] == j]
        active = [r for r in jrows if r["action"] != "NO_ACTION"]
        ge_count = sum(1 for r in active if r["action"].startswith("GE"))
        delays = [ens_delay(r) for r in jrows if ens_delay(r) > 0]
        saved  = [fv(r, "bus_saved_pax_s") for r in active]
        cost   = [fv(r, "other_inc_pax_s") for r in active]
        radar_jct.append({
            "label":          j,
            "AvgBusDelay":    round(statistics.mean(delays), 1) if delays else 0,
            "ActionRate%":    round(len(active) / max(len(jrows), 1) * 100, 1),
            "ExtFraction%":   round(ge_count / max(len(active), 1) * 100, 1),
            "AvgBusSaved":    round(statistics.mean(saved), 0) if saved else 0,
            "AvgCarPaxS":     round(statistics.mean(cost), 0) if cost else 0,
        })

    # ── 7. GREEN PHASE BREAKDOWN: phase vs action distribution ────────────────
    # Shows which signal phase the bus was detected in and what action resulted.
    # Key insight: bus-phase detections → mostly GE; wrong-phase → mostly INS/NO_ACTION
    phase_action_counts = {}   # {phase: {action_cat: n}}
    ACTION_CAT_ORDER = ["GE", "GR", "INS", "NO_ACTION"]
    ACTION_CAT_COLORS = {"GE": "#22c55ecc", "GR": "#a3e635cc", "INS": "#3b82f6cc", "NO_ACTION": "#475569cc"}

    def _action_cat(a):
        if a.startswith("GE"): return "GE"
        if a.startswith("GR"): return "GR"
        if "INS" in a:         return "INS"
        return "NO_ACTION"

    all_phases_seen = sorted(set(r["current_phase"] for r in chosen if r.get("current_phase","")),
                             key=lambda x: int(x) if x.isdigit() else 99)
    for r in chosen:
        ph = r.get("current_phase", "?")
        cat = _action_cat(r["action"])
        phase_action_counts.setdefault(ph, collections.Counter())[cat] += 1

    phase_labels = all_phases_seen
    phase_cat_matrix = {cat: [phase_action_counts.get(ph, {}).get(cat, 0) for ph in phase_labels]
                        for cat in ACTION_CAT_ORDER}

    # also: phase breakdown per junction (heatmap: junction × phase, colour = dominant action)
    phase_jct_heat = []
    for ph in phase_labels:
        row_vals = []
        for j in all_junctions:
            jph_rows = [r for r in chosen if r["junction_id"]==j and r.get("current_phase","")==ph]
            n_act = sum(1 for r in jph_rows if r["action"] != "NO_ACTION")
            n_tot = len(jph_rows)
            row_vals.append(round(n_act/max(n_tot,1)*100, 0))
        phase_jct_heat.append(row_vals)
    sample_rows = sorted(
        [r for r in chosen if r["action"] != "NO_ACTION"],
        key=lambda r: -fv(r, "bus_saved_pax_s")
    )[:30]
    bargain_samples = []
    for r in sample_rows:
        bus_util  = fv(r, "bus_saved_pax_s") / max(fv(r, "bus_occ", 1) * max(ens_delay(r), 1), 1)
        car_cost  = fv(r, "other_inc_pax_s")
        bus_saved = fv(r, "bus_saved_pax_s")
        bargain_samples.append({
            "jct":      r["junction_id"],
            "t":        round(fv(r, "sim_time_s"), 0),
            "action":   r["action"],
            "busSaved": round(bus_saved, 0),
            "carCost":  round(car_cost, 0),
            "eta":      round(fv(r, "bus_eta_s"), 1),
            "delay":    round(ens_delay(r), 1),   # ensemble (mb-blend)
            "kin_delay": round(fv(r, "no_act_delay_s"), 1),  # raw kinematic for comparison
            "reward":   round(fv(r, "reward"), 3),
            "busUtil":  round(bus_util, 4),
        })

    # ── 8. NO_ACTION GATE ANALYSIS: categorise why NO_ACTION was chosen ───────
    BG_MIN_DELAY_THR = 10.0
    BG_MIN_GAIN_THR  = 2.5
    gate_by_jct = {}   # {jct: {"GATE_DELAY": n, "GATE_GAIN": n, "NATURAL": n}}
    for r in [x for x in chosen if x["action"] == "NO_ACTION"]:
        ed = ens_delay(r)
        rd = fv(r, "reward_delta", fv(r, "gain", 0.0))
        if ed < BG_MIN_DELAY_THR:
            cat = "GATE_DELAY"
        elif rd < BG_MIN_GAIN_THR:
            cat = "GATE_GAIN"
        else:
            cat = "NATURAL"
        j = r["junction_id"]
        gate_by_jct.setdefault(j, {"GATE_DELAY": 0, "GATE_GAIN": 0, "NATURAL": 0})[cat] += 1
    gate_totals = {"GATE_DELAY": sum(v["GATE_DELAY"] for v in gate_by_jct.values()),
                   "GATE_GAIN":  sum(v["GATE_GAIN"]  for v in gate_by_jct.values()),
                   "NATURAL":    sum(v["NATURAL"]     for v in gate_by_jct.values())}

    # ── 8b. PER-JUNCTION DELAY PROFILE: mean bus delay + active TSP events ────
    # Explains why some junctions (e.g. 39606, 39590) are GATE_DELAY-dominated:
    # buses at those junctions typically arrive with very low delay, so the
    # 10 s threshold gates out all TSP actions.
    _jct_na_delays  = {}   # {jct: [ens_delay values from NO_ACTION rows]}
    _jct_active_imp = {}   # {jct: {n, sum_improvement}}
    for r in chosen:
        j = r["junction_id"]
        if r["action"] == "NO_ACTION":
            _jct_na_delays.setdefault(j, []).append(ens_delay(r))
        else:
            impr = fv(r, "no_strategy_delay_pax_s") - fv(r, "strategy_min_delay_pax_s")
            d = _jct_active_imp.setdefault(j, {"n": 0, "sum": 0.0})
            d["n"] += 1
            d["sum"] += impr
    _all_profile_jcts = sorted(
        set(list(_jct_na_delays.keys()) + list(_jct_active_imp.keys()))
    )
    jct_profile_labels = ["J" + j[-4:] for j in _all_profile_jcts]
    jct_profile_mean_delay = [
        round(sum(_jct_na_delays[j]) / len(_jct_na_delays[j]), 1)
        if j in _jct_na_delays else 0.0
        for j in _all_profile_jcts
    ]
    jct_profile_n_active = [
        _jct_active_imp[j]["n"] if j in _jct_active_imp else 0
        for j in _all_profile_jcts
    ]
    jct_profile_mean_impr = [
        round(_jct_active_imp[j]["sum"] / _jct_active_imp[j]["n"], 1)
        if j in _jct_active_imp else 0.0
        for j in _all_profile_jcts
    ]

    # ── 9. GR CANDIDATES: evaluated but not chosen ─────────────────────────
    gr_evaluated = [r for r in raw if r.get("action", "").startswith("GR")
                    and r.get("is_chosen", "0") == "0"]
    gr_by_jct = {}
    for r in gr_evaluated:
        j = r.get("junction_id", "?")
        d = gr_by_jct.setdefault(j, {"n": 0, "reward_sum": 0.0, "na_reward_sum": 0.0})
        d["n"]           += 1
        d["reward_sum"]  += fv(r, "reward", 0.0)
        d["na_reward_sum"] += fv(r, "no_action_reward", 0.0)
    gr_jct_labels = sorted(gr_by_jct.keys())
    gr_jct_labels_short = ["J" + j[-4:] for j in gr_jct_labels]
    gr_jct_n      = [gr_by_jct[j]["n"] for j in gr_jct_labels]
    gr_jct_avg_r  = [round(gr_by_jct[j]["reward_sum"] / max(gr_by_jct[j]["n"], 1), 3)
                     for j in gr_jct_labels]
    gr_jct_avg_na = [round(gr_by_jct[j]["na_reward_sum"] / max(gr_by_jct[j]["n"], 1), 3)
                     for j in gr_jct_labels]
    n_gr_total = len(gr_evaluated)

    # ── 10. REWARD DECOMPOSITION: headway vs CPD+fairness components ─────────
    W_HW = 0.6
    rd_by_action = {}   # {action: {"hw": [], "residual": []}}
    for r in [x for x in chosen if x["action"] != "NO_ACTION"]:
        a = r["action"]
        sig_in  = fv(r, "sigma_in_s",  0.0)
        sig_out = fv(r, "sigma_out_s", 0.0)
        hw_delta = abs(sig_in) - abs(sig_out)   # positive = headway improved
        hw_comp  = W_HW * hw_delta
        reward   = fv(r, "reward", 0.0)
        residual = reward - hw_comp             # ≈ PAX component − fairness penalty
        d = rd_by_action.setdefault(a, {"hw": [], "residual": []})
        d["hw"].append(hw_comp)
        d["residual"].append(residual)
    rdecomp_labels = present_actions_active
    rdecomp_hw  = [round(statistics.mean(rd_by_action[a]["hw"]), 3)
                   if a in rd_by_action and rd_by_action[a]["hw"] else 0.0
                   for a in rdecomp_labels]
    rdecomp_res = [round(statistics.mean(rd_by_action[a]["residual"]), 3)
                   if a in rd_by_action and rd_by_action[a]["residual"] else 0.0
                   for a in rdecomp_labels]

    # ── summary stats for header cards ----------------------------------------
    n_total   = len(chosen)
    n_active  = len([r for r in chosen if r["action"] != "NO_ACTION"])
    n_ge      = sum(1 for r in chosen if r["action"].startswith("GE"))
    n_ins     = sum(1 for r in chosen if "INS" in r["action"])
    n_na      = sum(1 for r in chosen if r["action"] == "NO_ACTION")
    all_saved = [fv(r, "bus_saved_pax_s") for r in chosen if r["action"] != "NO_ACTION"]
    mean_saved = round(statistics.mean(all_saved), 0) if all_saved else 0
    mean_delay_active = round(
        statistics.mean([ens_delay(r) for r in chosen
                         if r["action"] != "NO_ACTION" and ens_delay(r) > 0]),
        1
    )
    action_rate = round(n_active / max(n_total, 1) * 100, 1)

    # ── serialize for JS ----------------------------------------------------------
    def js(obj):
        return json.dumps(obj, separators=(",", ":"))

    # ── HTML template -------------------------------------------------------------
    html = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>Bargaining-Game TSP Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
    <style>
      :root{{--bg:#0f172a;--card:#1e293b;--border:#334155;--text:#f1f5f9;--sub:#94a3b8;
             --green:#22c55e;--blue:#3b82f6;--orange:#f97316;--red:#ef4444;
             --violet:#8b5cf6;--lime:#a3e635;}}
      *{{box-sizing:border-box;margin:0;padding:0;}}
      body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;
           font-size:13px;padding:16px;}}
      h1{{font-size:1.35rem;font-weight:700;margin-bottom:4px;}}
      .subtitle{{color:var(--sub);font-size:.85rem;margin-bottom:18px;}}
      .cards{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:18px;}}
      .card{{background:var(--card);border:1px solid var(--border);border-radius:8px;
              padding:12px 18px;min-width:130px;flex:1;}}
      .card .val{{font-size:1.5rem;font-weight:700;margin-bottom:2px;}}
      .card .lbl{{color:var(--sub);font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;}}
      .grid{{display:grid;gap:14px;}}
      .grid-2{{grid-template-columns:1fr 1fr;}}
      .grid-3{{grid-template-columns:1fr 1fr 1fr;}}
      @media(max-width:900px){{.grid-2,.grid-3{{grid-template-columns:1fr;}}}}
      .panel{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;}}
      .panel h2{{font-size:.95rem;font-weight:600;margin-bottom:10px;color:var(--sub);
                 text-transform:uppercase;letter-spacing:.06em;}}
      canvas{{max-width:100%;}}
      .theory-box{{background:#1a2a3a;border-left:3px solid var(--blue);
                   padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:14px;
                   font-size:.82rem;line-height:1.7;color:#cbd5e1;}}
      .theory-box .formula{{font-family:'Courier New',monospace;background:#0f172a;
                             padding:8px 12px;border-radius:4px;margin:8px 0;
                             font-size:.8rem;color:#7dd3fc;}}
      .legend-row{{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;}}
      .leg-item{{display:flex;align-items:center;gap:4px;font-size:.75rem;color:var(--sub);}}
      .leg-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0;}}
      .tbl{{width:100%;border-collapse:collapse;font-size:.78rem;}}
      .tbl th{{background:#0f172a;padding:6px 8px;text-align:left;color:var(--sub);
               border-bottom:1px solid var(--border);font-weight:600;}}
      .tbl td{{padding:5px 8px;border-bottom:1px solid #1e293b;}}
      .tbl tr:hover td{{background:#263248;}}
      .badge{{display:inline-block;padding:1px 6px;border-radius:4px;font-size:.7rem;
              font-weight:600;}}
      .tag-ge{{background:#14532d;color:#86efac;}}
      .tag-gr{{background:#1a2e05;color:#bef264;}}
      .tag-ins{{background:#1e3a8a;color:#93c5fd;}}
      .tag-na{{background:#1e293b;color:#94a3b8;}}
    </style>
    </head>
    <body>

    <h1>Bargaining-Game TSP Dashboard</h1>
    <p class="subtitle">Source: {os.path.basename(fn)} &nbsp;|&nbsp;
      Strategy: DCTSP_BARGAIN_SPM &nbsp;|&nbsp;
      Intersections: {len(all_junctions)} &nbsp;|&nbsp;
      Detections: {n_total}</p>

    <!-- THEORY BOX -->
    <div class="theory-box">
      <strong>How the Bargaining Game Works</strong><br>
      Each detected bus triggers a cooperative negotiation between the <em>bus phase</em> and
      <em>cross-traffic phases</em> at the intersection. The bus phase proposes an action
      (green extension GE, insertion INS, or green reallocation GR). The reward encodes
      the Nash bargaining solution: maximise joint utility while protecting cross-traffic
      from breakdown via the stochastic shockwave risk multiplier (SPM).
      <div class="formula">
    R = w<sub>hw</sub>·&Delta;headway + w<sub>pax</sub>·(w<sub>bus</sub>(tier)·BusSaved &minus; &rho;·CarCost) / BusOcc
        &minus; &lambda;<sub>fair</sub>·|u<sub>bus</sub> &minus; u<sub>cross</sub>|
      </div>
      <ul style="padding-left:16px;line-height:1.9;">
        <li><strong>w<sub>bus</sub>(tier)</strong>: detection-distance tier weight
            — immediate ({fv({'BG_BUS_W_IMM':1.6},'BG_BUS_W_IMM',1.6):.2f}×) ›
               near ({fv({'BG_BUS_W_NEAR':1.35},'BG_BUS_W_NEAR',1.35):.2f}×) ›
               far (1.10×) › very far (0.95×)</li>
        <li><strong>&rho;</strong>: SPM stochastic risk = 1 + {1.8}·CV(UpFlow)·SatRatio — amplifies car cost when cross-traffic is near breakdown</li>
        <li><strong>&lambda;<sub>fair</sub></strong> = {0.55}: equity penalty — reduces reward when the bus captures disproportionate gain</li>
        <li>Action is accepted only when bus delay &gt; 10 s AND reward gain &gt; 2.5 over no-action</li>
        <li><strong>Tall buses</strong> (length &gt; 15 m, e.g. articulated): occupancy is doubled (40→80 pax),
            making the bus side of the trade-off twice as valuable — TSP fires more readily for these vehicles.
            Detected at run-time via <code>AKIVehGetStaticInf</code>; logged as [BARGAIN_SPM] TALL_BUS.</li>
        <li><strong>Focus bus</strong>: to prevent conflicting TSP at adjacent junctions, only one bus at a time
            holds corridor focus. Other buses are suppressed until the current focus bus clears.
            Tall buses will benefit from the occupancy boost but do not yet receive priority in the focus queue.</li>
      </ul>
    </div>

    <!-- SUMMARY CARDS -->
    <div class="cards">
      <div class="card"><div class="val" style="color:var(--green)">{n_active}</div><div class="lbl">Active Actions</div></div>
      <div class="card"><div class="val" style="color:var(--blue)">{n_ge}</div><div class="lbl">Green Extensions</div></div>
      <div class="card"><div class="val" style="color:var(--violet)">{n_ins}</div><div class="lbl">Insertions</div></div>
      <div class="card"><div class="val" style="color:var(--sub)">{n_na}</div><div class="lbl">No Action</div></div>
      <div class="card"><div class="val" style="color:var(--orange)">{action_rate}%</div><div class="lbl">Action Rate</div></div>
      <div class="card"><div class="val" style="color:var(--green)">{mean_saved:,.0f}</div><div class="lbl">Avg Bus Saved pax·s</div></div>
      <div class="card"><div class="val" style="color:var(--orange)">{mean_delay_active:.1f}s</div><div class="lbl">Avg Bus Delay on Action</div></div>
    </div>

    <!-- ROW 1 -->
    <div class="grid grid-2" style="margin-bottom:14px;">

      <!-- ACTION HEATMAP -->
      <div class="panel">
        <h2>Action Distribution by Junction</h2>
        <canvas id="heatmapChart" height="220"></canvas>
      </div>

      <!-- ETA vs DELAY scatter -->
      <div class="panel">
        <h2>Detection: Bus ETA vs Expected Delay</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          Each dot = one detection. Colour = chosen action. Size proportional to bus occupancy.
          Top-right quadrant = high-value bargaining opportunities.
        </p>
        <canvas id="etaDelayChart" height="220"></canvas>
      </div>

    </div>

    <!-- ROW 2 -->
    <div class="grid grid-2" style="margin-bottom:14px;">

      <!-- UTILITY DECOMPOSITION -->
      <div class="panel">
        <h2>Bargaining Trade-off: Bus Passengers Saved vs Car Passengers Cost (pax&#183;s)</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          Both axes are in pax&#183;s (passengers &times; seconds of delay). The diagonal line is break-even: bus benefit = car cost.
          Points <strong>above</strong> the diagonal mean the TSP action saves more bus passenger-time than it costs car passenger-time &mdash;
          the bargaining game accepts these. Points below are rejected (fairness or cascade risk may still block some above-diagonal actions).
          Car cost = direct queued delay imposed on cross-traffic passengers at this intersection.
        </p>
        <canvas id="utilityChart" height="220"></canvas>
      </div>

      <!-- REWARD COMPONENT bar -->
      <div class="panel">
        <h2>Mean Reward Components by Action Type (all evaluated)</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          Averages over <em>all</em> evaluations where bus delay&nbsp;&gt;&nbsp;10&nbsp;s
          (chosen and non-chosen), so every action type appears and zero-delay rows
          don't distort GE/INS averages.  ER_BP rows are included without a delay
          filter because ER_BP cuts the bus phase when the bus has <em>no</em> delay
          (sacrificing bus green for cross-traffic benefit).<br>
          <strong>Negative bus-saved (≈&nbsp;−200):</strong> this is a <em>wrong-phase</em>
          evaluation — the action would extend or reallocate a non-bus phase, delaying
          the bus further by action_s&nbsp;×&nbsp;occ&nbsp;pax·s.  It is not a default
          value; it is the correct modelled penalty for acting on the wrong phase.<br>
          <strong>Negative car cost (ER_BP):</strong> for ER_BP the cross-traffic
          <em>gains</em> green time (bus phase shortened), so
          car&nbsp;cost&nbsp;&lt;&nbsp;0 means a car benefit, not a car penalty.
        </p>
        <canvas id="rewardBarChart" height="220"></canvas>
      </div>

    </div>

    <!-- ROW 3 -->
    <div class="grid grid-2" style="margin-bottom:14px;">

      <!-- TIMELINE -->
      <div class="panel">
        <h2>Action Timeline (active only)</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          Each bar shows bus delay at moment of action, coloured by action type.
        </p>
        <canvas id="timelineChart" height="220"></canvas>
      </div>

      <!-- JUNCTION RADAR -->
      <div class="panel">
        <h2>Per-Junction Profile (radar)</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          Normalised to [0,1] per metric. Larger area = more active/effective bargaining.
        </p>
        <canvas id="radarChart" height="220"></canvas>
      </div>

    </div>

    <!-- ROW 4: GREEN PHASE BREAKDOWN -->
    <div class="grid grid-2" style="margin-bottom:14px;">

      <!-- PHASE × ACTION stacked bar -->
      <div class="panel">
        <h2>Green Phase Breakdown: Action by Signal Phase</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          Stacked by phase number detected at detection. Bus-phase detections tend to produce GE;
          wrong-phase detections tend to produce INS or NO_ACTION.
        </p>
        <canvas id="phaseActionChart" height="220"></canvas>
      </div>

      <!-- PHASE × JUNCTION action rate heatmap -->
      <div class="panel">
        <h2>Phase × Junction Active Action Rate (%)</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          Colour intensity = % of detections at that phase &amp; junction that resulted in an active TSP action.
          Hot cells = high bargaining activity.
        </p>
        <canvas id="phaseJctChart" height="220"></canvas>
      </div>

    </div>

    <!-- ROW 5: GATE ANALYSIS + GR CANDIDATES -->
    <div class="grid grid-2" style="margin-bottom:14px;">

      <div class="panel">
        <h2>NO_ACTION Gate Analysis by Junction</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          Why was NO_ACTION chosen? Breakdown per junction:<br>
          <span style="color:#ef4444">■</span> <strong>GATE_DELAY</strong>: ens_delay &lt; 10 s — bus not delayed enough to warrant TSP ({gate_totals['GATE_DELAY']} total).<br>
          <span style="color:#f97316">■</span> <strong>GATE_GAIN</strong>: delay ≥ 10 s but best-action gain &lt; 2.5 — no action worth the cost ({gate_totals['GATE_GAIN']} total).<br>
          <span style="color:#475569">■</span> <strong>NATURAL</strong>: delay ≥ 10 s &amp; gain ≥ 2.5 but NO_ACTION genuinely won ({gate_totals['NATURAL']} total).
        </p>
        <canvas id="gateChart" height="220"></canvas>
      </div>

      <div class="panel">
        <h2>Green Reallocation: Evaluated but Not Chosen ({n_gr_total} events)</h2>
        <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
          GR was evaluated {n_gr_total} times but never chosen as best action — consistently beaten by INS
          (which saves the entire queued delay vs GR which can only cut remaining red time).
          Bars show mean GR reward vs NO_ACTION baseline at those same detection events.
        </p>
        <canvas id="grCandChart" height="220"></canvas>
      </div>

    </div>

    <!-- ROW 5b: JUNCTION DELAY PROFILE -->
    <div class="panel" style="margin-bottom:14px;">
      <h2>Per-Junction Bus Delay Profile</h2>
      <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
        <strong>Left axis / blue bars:</strong> Mean bus ensemble delay&nbsp;(s) at detection
        for NO_ACTION events.  Junctions below the 10&nbsp;s gate threshold (dashed red line)
        are predominantly GATE_DELAY — buses at those junctions typically arrive with very
        little delay, so TSP is never triggered.
        This explains why junctions such as&nbsp;39606 and&nbsp;39590 look similar in the gate
        analysis: both have mean bus delay well below 10&nbsp;s and accumulate no active TSP events.<br>
        <strong>Right axis / orange line:</strong> Count of chosen <em>active</em> TSP actions
        (non-NO_ACTION) per junction.  Junctions with zero active events had no bus that
        crossed the delay threshold during this simulation run.
      </p>
      <canvas id="jctProfileChart" height="160"></canvas>
    </div>

    <!-- ROW 6: REWARD DECOMPOSITION -->
    <div class="panel" style="margin-bottom:14px;">
      <h2>Reward Decomposition: Headway (w<sub>hw</sub>=0.6 × Δheadway) vs Residual (PAX − Fairness)</h2>
      <p style="font-size:.75rem;color:var(--sub);margin-bottom:8px;">
        Mean reward split for each chosen action type. Headway component = 0.6 × (|σ<sub>in</sub>| − |σ<sub>out</sub>|).
        Residual ≈ PAX savings component − fairness penalty. Negative residual means fairness penalty exceeds PAX benefit.
      </p>
      <canvas id="rdChart" height="160"></canvas>
    </div>

    <!-- SAMPLE TABLE -->
    <div class="panel">
      <h2>Top 30 Bargaining Actions (by bus pax·s saved)</h2>
      <div style="overflow-x:auto;">
      <table class="tbl">
        <thead>
          <tr>
            <th>Junction</th><th>Time (s)</th><th>Action</th>
            <th>Bus ETA (s)</th><th>No-Act Delay (s)</th>
            <th>Bus Saved (pax·s)</th><th>Car Cost (pax·s, queued delay)</th>
            <th>Reward</th><th>Bus Util</th>
          </tr>
        </thead>
        <tbody>
          {''.join(
            f"<tr>"
            f"<td>{s['jct']}</td><td>{s['t']:.0f}</td>"
            f"<td><span class='badge {'tag-ge' if s['action'].startswith('GE') else 'tag-gr' if s['action'].startswith('GR') else 'tag-ins' if 'INS' in s['action'] else 'tag-na'}'>{s['action']}</span></td>"
            f"<td>{s['eta']:.1f}</td><td>{s['delay']:.1f}</td>"
            f"<td style='color:#22c55e'>{s['busSaved']:,.0f}</td>"
            f"<td style='color:#f97316'>{s['carCost']:,.0f}</td>"
            f"<td>{s['reward']:.3f}</td>"
            f"<td>{s['busUtil']:.3f}</td>"
            f"</tr>"
            for s in bargain_samples
          )}
        </tbody>
      </table>
      </div>
    </div>

    <script>
    // ── data ──────────────────────────────────────────────────────────────────────
    const JUNCTIONS    = {js(heat_jct_labels)};
    const ACTIONS      = {js(heat_action_labels)};
    const HEATMATRIX   = {js(heat_matrix)};  // [action_idx][jct_idx]
    const ACT_COLORS   = {js({k: ACTION_COLORS.get(k, "#888") for k in present_actions})};
    const SCATTER_ACT  = {js(scatter_by_action)};
    const EVAL_ACT     = {js(eval_by_action)};   // all evaluated (chosen + non-chosen), excl NO_ACTION
    const DET_ACT      = {js(det_by_action)};
    const TIMELINE_JCT = {js(timeline)};
    const RADAR_DATA   = {js(radar_jct)};
    const RADAR_METRICS= {js(radar_metrics)};
    // Phase breakdown data
    const PHASE_LABELS    = {js(phase_labels)};
    const PHASE_CAT_MAT   = {js(phase_cat_matrix)};  // {{GE:[...], INS:[...], NO_ACTION:[...]}}
    const PHASE_CAT_COLORS= {js(ACTION_CAT_COLORS)};
    const PHASE_JCT_HEAT  = {js(phase_jct_heat)};    // [phase_idx][jct_idx] = action_rate%
    // Gate analysis data
    const GATE_BY_JCT   = {js(gate_by_jct)};
    // Junction delay profile data
    const JCT_PROF_LABELS    = {js(jct_profile_labels)};
    const JCT_PROF_MEAN_DEL  = {js(jct_profile_mean_delay)};   // mean bus delay (s) from NO_ACTION rows
    const JCT_PROF_N_ACTIVE  = {js(jct_profile_n_active)};    // count of active TSP chosen events
    const JCT_PROF_MEAN_IMPR = {js(jct_profile_mean_impr)};   // mean pax·s improvement for active rows
    // GR candidates data
    const GR_LABELS     = {js(gr_jct_labels_short)};
    const GR_AVG_R      = {js(gr_jct_avg_r)};
    const GR_AVG_NA     = {js(gr_jct_avg_na)};
    const GR_N          = {js(gr_jct_n)};
    // Reward decomposition data
    const RD_LABELS     = {js(rdecomp_labels)};
    const RD_HW         = {js(rdecomp_hw)};
    const RD_RES        = {js(rdecomp_res)};

    // helper: short junction label
    function jShort(id) {{ return 'J'+id.slice(-4); }}

    // ── Chart 1: heatmap (grouped bar) ─────────────────────────────────────────
    const hmCtx = document.getElementById('heatmapChart').getContext('2d');
    new Chart(hmCtx, {{
      type: 'bar',
      data: {{
        labels: JUNCTIONS.map(jShort),
        datasets: ACTIONS.map((act, i) => ({{
          label: act,
          data: HEATMATRIX[i],
          backgroundColor: ACT_COLORS[act] + 'cc',
          borderRadius: 3,
        }}))
      }},
      options: {{
        plugins: {{ legend: {{ position:'right', labels: {{ color:'#94a3b8', font:{{size:10}} }} }} }},
        responsive: true,
        scales: {{
          x: {{ stacked:true, ticks:{{ color:'#94a3b8', font:{{size:10}} }}, grid:{{ color:'#334155' }} }},
          y: {{ stacked:true, ticks:{{ color:'#94a3b8', font:{{size:10}} }}, grid:{{ color:'#334155' }},
                title:{{ display:true, text:'Actions', color:'#64748b' }} }},
        }}
      }}
    }});

    // ── Chart 2: ETA vs delay scatter ──────────────────────────────────────────
    const edCtx = document.getElementById('etaDelayChart').getContext('2d');
    new Chart(edCtx, {{
      type: 'scatter',
      data: {{
        datasets: Object.keys(DET_ACT).map(act => ({{
          label: act,
          data: DET_ACT[act],
          backgroundColor: (ACT_COLORS[act] || '#888') + 'bb',
          pointRadius: 4,
          pointHoverRadius: 6,
        }}))
      }},
      options: {{
        plugins: {{
          legend: {{ position:'right', labels:{{ color:'#94a3b8', font:{{size:10}} }} }},
          tooltip: {{ callbacks: {{ label: ctx => `${{ctx.dataset.label}} ETA=${{ctx.raw.x}}s delay=${{ctx.raw.y}}s jct=${{ctx.raw.jct}}` }} }},
        }},
        scales: {{
          x: {{ title:{{ display:true, text:'Bus ETA (s)', color:'#64748b' }},
               ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
          y: {{ title:{{ display:true, text:'No-action bus delay (s)', color:'#64748b' }},
               ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
        }}
      }}
    }});

    // ── Chart 3: utility scatter (bus saved vs car cost) ───────────────────────
    const utCtx = document.getElementById('utilityChart').getContext('2d');
    const utMax = Math.max(
      ...Object.values(SCATTER_ACT).flat().map(p => Math.max(p.x, p.y)), 1000
    );
    new Chart(utCtx, {{
      type: 'scatter',
      data: {{
        datasets: [
          // diagonal reference line (bus=car)
          {{ label:'Bus = Car (break-even)',
             data: [{{x:0,y:0}}, {{x:utMax,y:utMax}}],
             type:'line', borderColor:'#475569', borderDash:[4,4],
             pointRadius:0, borderWidth:1, fill:false }},
          ...Object.keys(SCATTER_ACT).map(act => ({{
            label: act,
            data: SCATTER_ACT[act],
            backgroundColor: (ACT_COLORS[act]||'#888')+'bb',
            pointRadius: 5,
          }}))
        ]
      }},
      options: {{
        plugins: {{
          legend: {{ position:'right', labels:{{ color:'#94a3b8', font:{{size:10}} }} }},
          tooltip: {{ callbacks: {{ label: ctx => `${{ctx.dataset.label}} car=${{ctx.raw.x}} bus=${{ctx.raw.y}} delay=${{ctx.raw.delay}}s` }} }},
        }},
        scales: {{
          x: {{ title:{{ display:true, text:'Car passengers additional delay (pax·s)', color:'#64748b' }},
               ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }},
               min:0 }},
          y: {{ title:{{ display:true, text:'Bus passengers saved (pax·s)', color:'#64748b' }},
               ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }},
               min:0 }},
        }}
      }}
    }});

    // ── Chart 4: mean reward by action type (bar) ──────────────────────────────
    (function() {{
      const rcCtx = document.getElementById('rewardBarChart').getContext('2d');
      // Use EVAL_ACT (all evaluated rows) so every action type appears even if rarely chosen.
      const actLabels = {js(eval_actions_active)};
      const meanSaved  = actLabels.map(a => {{
        const pts = (EVAL_ACT[a]||[]);
        return pts.length ? +(pts.reduce((s,p)=>s+p.y,0)/pts.length).toFixed(0) : 0;
      }});
      const meanCar = actLabels.map(a => {{
        const pts = (EVAL_ACT[a]||[]);
        return pts.length ? +(pts.reduce((s,p)=>s+p.x,0)/pts.length).toFixed(0) : 0;
      }});
      const meanRwd = actLabels.map(a => {{
        const pts = (EVAL_ACT[a]||[]);
        return pts.length ? +(pts.reduce((s,p)=>s+p.reward,0)/pts.length).toFixed(3) : 0;
      }});
      new Chart(rcCtx, {{
        type: 'bar',
        data: {{
          labels: actLabels,
          datasets: [
            {{ label:'Mean Bus Saved (pax·s)', data: meanSaved, backgroundColor:'#22c55ecc', yAxisID:'y' }},
            {{ label:'Mean Car Cost (pax·s)',  data: meanCar,   backgroundColor:'#f97316cc', yAxisID:'y' }},
            {{ label:'Mean Reward',            data: meanRwd,   backgroundColor:'#3b82f6cc', yAxisID:'y2',
               type:'line', borderColor:'#3b82f6', pointRadius:5, fill:false }},
          ]
        }},
        options: {{
          plugins: {{ legend: {{ position:'top', labels:{{ color:'#94a3b8', font:{{size:10}} }} }} }},
          scales: {{
            x: {{ ticks:{{ color:'#94a3b8', font:{{size:10}} }}, grid:{{ color:'#334155' }} }},
            y: {{ ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }},
                  title:{{ display:true, text:'pax·s', color:'#64748b' }} }},
            y2:{{ position:'right', ticks:{{ color:'#3b82f6' }}, grid:{{ drawOnChartArea:false }},
                  title:{{ display:true, text:'Reward', color:'#3b82f6' }} }},
          }}
        }}
      }});
    }})();

    // ── Chart 5: timeline (scatter by action, x=time, y=delay) ─────────────────
    (function() {{
      const tlCtx = document.getElementById('timelineChart').getContext('2d');
      // flatten timeline into datasets by action
      const allActive = Object.values(TIMELINE_JCT).flat();
      const byAct = {{}};
      allActive.forEach(p => {{
        if (!byAct[p.action]) byAct[p.action] = [];
        byAct[p.action].push({{x: p.t, y: p.delay, saved: p.saved}});
      }});
      new Chart(tlCtx, {{
        type: 'scatter',
        data: {{
          datasets: Object.keys(byAct).map(act => ({{
            label: act,
            data: byAct[act],
            backgroundColor: (ACT_COLORS[act]||'#888')+'bb',
            pointRadius: 4,
          }}))
        }},
        options: {{
          plugins: {{
            legend: {{ position:'right', labels:{{ color:'#94a3b8', font:{{size:10}} }} }},
            tooltip: {{ callbacks: {{ label: ctx => `${{ctx.dataset.label}} t=${{ctx.raw.x}}s delay=${{ctx.raw.y}}s saved=${{ctx.raw.saved}}pax·s` }} }},
          }},
          scales: {{
            x: {{ title:{{ display:true, text:'Simulation time (s)', color:'#64748b' }},
                 ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
            y: {{ title:{{ display:true, text:'Bus delay at detection (s)', color:'#64748b' }},
                 ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
          }}
        }}
      }});
    }})();

    // ── Chart 6: per-junction radar ─────────────────────────────────────────────
    (function() {{
      const rdCtx = document.getElementById('radarChart').getContext('2d');
      // normalise each metric 0-1 across junctions
      const norms = RADAR_METRICS.map(m => {{
        const vals = RADAR_DATA.map(d => d[m]);
        const mx = Math.max(...vals) || 1;
        return vals.map(v => +(v/mx).toFixed(3));
      }});
      const palette = ['#22c55e','#3b82f6','#f97316','#8b5cf6','#ec4899',
                       '#14b8a6','#eab308','#ef4444','#a3e635','#06b6d4',
                       '#f43f5e','#84cc16'];
      new Chart(rdCtx, {{
        type: 'radar',
        data: {{
          labels: RADAR_METRICS,
          datasets: RADAR_DATA.map((d, i) => ({{
            label: 'J'+d.label.slice(-4),
            data: RADAR_METRICS.map((m, mi) => norms[mi][i]),
            borderColor: palette[i % palette.length],
            backgroundColor: palette[i % palette.length] + '20',
            pointRadius: 3,
            borderWidth: 1.5,
          }}))
        }},
        options: {{
          plugins: {{ legend: {{ position:'right', labels:{{ color:'#94a3b8', font:{{size:10}} }} }} }},
          scales: {{
            r: {{
              ticks: {{ display:false }},
              grid:  {{ color:'#334155' }},
              angleLines: {{ color:'#334155' }},
              pointLabels: {{ color:'#94a3b8', font:{{size:10}} }},
            }}
          }}
        }}
      }});
    }})();

    // ── Chart 7: phase × action stacked bar ─────────────────────────────────────
    (function() {{
      const paCtx = document.getElementById('phaseActionChart').getContext('2d');
      const cats  = Object.keys(PHASE_CAT_MAT);
      new Chart(paCtx, {{
        type: 'bar',
        data: {{
          labels: PHASE_LABELS.map(p => 'Ph '+p),
          datasets: cats.map(cat => ({{
            label: cat,
            data: PHASE_CAT_MAT[cat],
            backgroundColor: PHASE_CAT_COLORS[cat] || '#888',
            borderRadius: 3,
          }}))
        }},
        options: {{
          plugins: {{ legend: {{ position:'top', labels:{{ color:'#94a3b8', font:{{size:10}} }} }} }},
          scales: {{
            x: {{ stacked:true, ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
            y: {{ stacked:true, ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }},
                  title:{{ display:true, text:'Detections', color:'#64748b' }} }},
          }}
        }}
      }});
    }})();

    // ── Chart 8: phase × junction action-rate heatmap (bubble) ─────────────────
    (function() {{
      const pjCtx = document.getElementById('phaseJctChart').getContext('2d');
      // Represent as bubble chart: x=jct, y=phase, r proportional to action rate %
      const bubbles = [];
      PHASE_LABELS.forEach((ph, pi) => {{
        JUNCTIONS.forEach((jct, ji) => {{
          const rate = PHASE_JCT_HEAT[pi][ji];
          if (rate > 0) bubbles.push({{
            x: ji, y: pi, r: Math.max(2, rate / 7),
            rate, jct: 'J'+jct.slice(-4), ph
          }});
        }});
      }});
      new Chart(pjCtx, {{
        type: 'bubble',
        data: {{
          datasets: [{{
            label: 'Action rate %',
            data: bubbles,
            backgroundColor: bubbles.map(b => `rgba(59,130,246,${{(b.rate/100).toFixed(2)}})` ),
            borderColor: '#3b82f6',
            borderWidth: 1,
          }}]
        }},
        options: {{
          plugins: {{
            legend: {{ display:false }},
            tooltip: {{ callbacks: {{ label: ctx => `${{ctx.raw.jct}} Ph${{ctx.raw.ph}}: ${{ctx.raw.rate}}% active` }} }},
          }},
          scales: {{
            x: {{ min:-0.5, max: JUNCTIONS.length-0.5,
                 ticks:{{ color:'#94a3b8', callback: (v,i) => JUNCTIONS[Math.round(v)] ? 'J'+JUNCTIONS[Math.round(v)].slice(-4) : '' }},
                 grid:{{ color:'#334155' }} }},
            y: {{ min:-0.5, max: PHASE_LABELS.length-0.5,
                 ticks:{{ color:'#94a3b8', callback: (v,i) => PHASE_LABELS[Math.round(v)] != null ? 'Ph '+PHASE_LABELS[Math.round(v)] : '' }},
                 grid:{{ color:'#334155' }},
                 title:{{ display:true, text:'Signal Phase', color:'#64748b' }} }},
          }}
        }}
      }});
    }})();

    // ── Chart 9: NO_ACTION gate analysis stacked bar ─────────────────────────
    (function() {{
      const gtCtx = document.getElementById('gateChart').getContext('2d');
      const gCats = ['GATE_DELAY', 'GATE_GAIN', 'NATURAL'];
      const gColors = {{'GATE_DELAY':'#ef4444cc','GATE_GAIN':'#f97316cc','NATURAL':'#475569cc'}};
      const jKeys = Object.keys(GATE_BY_JCT);
      if (jKeys.length === 0) return;
      new Chart(gtCtx, {{
        type: 'bar',
        data: {{
          labels: jKeys.map(j => 'J'+j.slice(-4)),
          datasets: gCats.map(cat => ({{
            label: cat,
            data: jKeys.map(j => (GATE_BY_JCT[j]||{{}})[cat] || 0),
            backgroundColor: gColors[cat],
            borderRadius: 3,
          }}))
        }},
        options: {{
          plugins: {{ legend: {{ position:'top', labels:{{ color:'#94a3b8', font:{{size:10}} }} }} }},
          scales: {{
            x: {{ stacked:true, ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
            y: {{ stacked:true, ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }},
                  title:{{ display:true, text:'NO_ACTION count', color:'#64748b' }} }},
          }}
        }}
      }});
    }})();

    // ── Chart 10: GR candidates grouped bar ──────────────────────────────────
    (function() {{
      const grCtx = document.getElementById('grCandChart').getContext('2d');
      if (!GR_LABELS || GR_LABELS.length === 0) {{
        grCtx.canvas.parentNode.innerHTML += '<p style="color:#64748b;padding:16px;font-size:.8rem;">No GR candidate rows found in this CSV (GR may not have been evaluated).</p>';
        return;
      }}
      new Chart(grCtx, {{
        type: 'bar',
        data: {{
          labels: GR_LABELS,
          datasets: [
            {{ label:'Avg GR reward (evaluated)', data: GR_AVG_R,  backgroundColor:'#a3e635cc', borderRadius:3 }},
            {{ label:'Avg NO_ACTION baseline',    data: GR_AVG_NA, backgroundColor:'#475569cc', borderRadius:3 }},
            {{ label:'GR candidate count', data: GR_N, type:'line', borderColor:'#f97316',
               pointRadius:5, fill:false, yAxisID:'y2' }},
          ]
        }},
        options: {{
          plugins: {{ legend: {{ position:'top', labels:{{ color:'#94a3b8', font:{{size:10}} }} }} }},
          scales: {{
            x: {{ ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
            y: {{ ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }},
                  title:{{ display:true, text:'Mean reward', color:'#64748b' }} }},
            y2:{{ position:'right', ticks:{{ color:'#f97316' }}, grid:{{ drawOnChartArea:false }},
                  title:{{ display:true, text:'GR count', color:'#f97316' }} }},
          }}
        }}
      }});
    }})();

    // ── Chart 11: reward decomposition stacked bar ───────────────────────────
    (function() {{
      const rdCtx = document.getElementById('rdChart').getContext('2d');
      new Chart(rdCtx, {{
        type: 'bar',
        data: {{
          labels: RD_LABELS,
          datasets: [
            {{ label:'Headway component (w_hw × Δhw)', data: RD_HW,
               backgroundColor:'#22c55ecc', stack:'a', borderRadius:3 }},
            {{ label:'Residual (CPD − fairness penalty)', data: RD_RES,
               backgroundColor:'#3b82f6cc', stack:'a', borderRadius:3 }},
          ]
        }},
        options: {{
          plugins: {{ legend: {{ position:'top', labels:{{ color:'#94a3b8', font:{{size:10}} }} }} }},
          scales: {{
            x: {{ ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
            y: {{ ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }},
                  title:{{ display:true, text:'Mean reward component', color:'#64748b' }} }},
          }}
        }}
      }});

      // ── Junction delay profile ─────────────────────────────────────────────
      const jpCtx = document.getElementById('jctProfileChart').getContext('2d');
      new Chart(jpCtx, {{
        type: 'bar',
        data: {{
          labels: JCT_PROF_LABELS,
          datasets: [
            {{
              label: 'Mean bus delay at detection (NO_ACTION events, s)',
              data: JCT_PROF_MEAN_DEL,
              backgroundColor: '#3b82f6aa',
              borderRadius: 3,
              yAxisID: 'yDelay',
            }},
            {{
              label: 'Active TSP events chosen (count)',
              data: JCT_PROF_N_ACTIVE,
              type: 'line',
              borderColor: '#f97316',
              backgroundColor: '#f97316',
              pointRadius: 5,
              pointStyle: 'circle',
              fill: false,
              yAxisID: 'yActive',
            }},
          ]
        }},
        options: {{
          plugins: {{
            legend: {{ position:'top', labels:{{ color:'#94a3b8', font:{{size:10}} }} }},
            annotation: {{
              annotations: {{
                threshold: {{
                  type: 'line',
                  yMin: 10, yMax: 10,
                  yScaleID: 'yDelay',
                  borderColor: '#ef4444',
                  borderWidth: 2,
                  borderDash: [6,4],
                  label: {{
                    content: '10 s gate threshold',
                    enabled: true,
                    color: '#ef4444',
                    font: {{ size: 10 }},
                  }}
                }}
              }}
            }}
          }},
          scales: {{
            x: {{ ticks:{{ color:'#94a3b8' }}, grid:{{ color:'#334155' }} }},
            yDelay: {{
              type: 'linear', position: 'left',
              ticks: {{ color:'#3b82f6' }},
              grid: {{ color:'#334155' }},
              title: {{ display:true, text:'Mean bus delay (s)', color:'#3b82f6' }},
            }},
            yActive: {{
              type: 'linear', position: 'right',
              ticks: {{ color:'#f97316' }},
              grid: {{ drawOnChartArea: false }},
              title: {{ display:true, text:'Active TSP events', color:'#f97316' }},
            }},
          }}
        }}
      }});
    }})();
    </script>
    </body>
    </html>
    """

    out = os.path.join(SCRIPT_DIR, "bargain_game_dashboard.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"[bargain_dashboard] written \u2192 {os.path.abspath(out)}")
    print(f"[bargain_dashboard] open in browser: file://{os.path.abspath(out)}")
    return out


if __name__ == "__main__":
    _parser = argparse.ArgumentParser()
    _parser.add_argument("--csv", default=None)
    _args = _parser.parse_args()
    main(csv_path=_args.csv)
