"""
champion_search.py -- Phase 1 of the BCC113 simulation matrix.

CHAMPION SEARCH: 8 strategy arms x 5 seeds at x1.0 demand = 40 runs per corridor.
Determines the champion (best mean objective vs NO_TSP) for KG and Logan Road.

HOW TO RUN (inside Aimsun, one corridor at a time)
--------------------------------------------------
  1. Open the KG model in Aimsun  -> run this script from the Python console.
     It auto-detects "kg" from the open model and writes champion_kg.csv.
  2. Open the Logan Road model    -> run this script again.
     It writes champion_logan_road_new.csv.
  3. From a normal terminal:  python rank_champions.py
     -> prints the ranked arms and the champion for each corridor.

The 10 arms (9 TSP strategies + NO_TSP baseline; edit ARMS to taste):
  NO_TSP, CELLQLEARN (BXT), DCTSP_ZIG (HSLWR), DCTSP_MP_ECTM (CTMGS),
  DCTSP_BARGAIN_SPM (Nash), DCTSP_MARL, CENTRALISED, CELLQLEARN_DP,
  MAXPRESSURE_FIX, MAXPRESSURE_FLEX (Varaiya 2013, via sumoITScontrol).
CELLQLEARN_DP is the "one more" pick -- a dynamic-programming CellQLearn variant
to test whether DP planning beats the tabular-Q champion.
"""
import os as _os, sys as _sys, time as _time, glob as _glob, importlib.util as _ilu

# ── 1. Detect which corridor's model is open (most-recent Aimsun lock file) ────
_ROOT = _os.path.dirname(_os.path.abspath(__file__))
def _detect_corridor():
    cands = []
    for c in ("kg", "logan_road_new"):
        d = _os.path.join(_ROOT, c)
        locks = _glob.glob(_os.path.join(d, "*.ang.lck")) + _glob.glob(_os.path.join(d, "*.sang.lck"))
        if locks:
            cands.append((c, d, max(_os.path.getmtime(p) for p in locks)))
    if cands:
        cands.sort(key=lambda t: -t[2]); return cands[0][0], cands[0][1]
    # fallback: current working directory
    cwd = _os.path.abspath(_os.getcwd())
    for c in ("kg", "logan_road_new"):
        if _os.path.normcase(cwd).endswith(c):
            return c, _os.path.join(_ROOT, c)
    raise RuntimeError("Could not detect corridor (no .ang.lck under kg/ or logan_road_new/). "
                       "Open the corridor model in Aimsun before running.")

CORRIDOR, CORR_DIR = _detect_corridor()

# ── 2. Import that corridor's batch-runner infrastructure ─────────────────────
_br_path = _os.path.join(CORR_DIR, "batch_runner.py")
_spec = _ilu.spec_from_file_location("_br_champ", _br_path)
_br = _ilu.module_from_spec(_spec); _sys.modules["_br_champ"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

# ── 3. Champion-search design (Phase 1) ───────────────────────────────────────
# FAIR COMPARISON: the learning arms (CELLQLEARN, CELLQLEARN_DP) must TRAIN before
# they are scored, else they cold-start every seed and are crippled (measured: KG
# CELLQLEARN -8% under per_seed vs +14% on a warmed single seed). So learners
# train on TRAIN_SEEDS (Q accumulates, exploration on) then freeze and are scored
# on EVAL_SEEDS. Non-learning arms just run EVAL_SEEDS. EVERY arm is ranked ONLY
# on EVAL_SEEDS, so the comparison is apples-to-apples.
EVAL_SEEDS = [300, 400, 500, 600, 700]     # the 5 champion seeds (all arms scored here)
TRAIN_SEEDS = [800, 900, 1000, 1100]       # learners pre-train here (ignored in ranking)
LEARNING_ARMS = {"CELLQLEARN", "CELLQLEARN_SAFE"}
BXT_TRAIN_EPSILON = 0.30                    # exploration during the learners' train phase
DEMAND_SCALARS = [1.0]                      # x1.0 demand
RESULTS_CSV = _os.path.join(_ROOT, f"champion_{CORRIDOR}.csv")


def _set_controller_bxt_seeds(controller_path, train, eval_, train_eps):
    """Patch BXT_TRAIN_SEEDS / BXT_EVAL_SEEDS / BXT_TRAIN_EPSILON in the corridor
    controller so the engine trains-then-freezes (learners) or runs per_seed
    (empty lists -> non-learners). Adds the lines if the controller lacks them
    (Logan's controller does)."""
    import re
    with open(controller_path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    repl = {
        "BXT_TRAIN_SEEDS": repr(list(train)),
        "BXT_EVAL_SEEDS": repr(list(eval_)),
        "BXT_TRAIN_EPSILON": repr(float(train_eps)),
    }
    for var, val in repl.items():
        pat = re.compile(r"(?m)^(%s)\s*=.*$" % re.escape(var))
        if pat.search(txt):
            txt = pat.sub(r"\1 = " + val.replace("\\", "\\\\"), txt)
        else:
            # insert after the imports block (first blank line past 'import')
            txt = txt.replace("\nimport math\n", "\nimport math\n%s = %s\n" % (var, val), 1) \
                if "\nimport math\n" in txt else (var + " = " + val + "\n" + txt)
    with open(controller_path, "w", encoding="utf-8", newline="") as f:
        f.write(txt)


def _set_controller_flag(controller_path, flag, value):
    """Force a top-level boolean flag in the controller (e.g. disable the heavy
    per-run plotting during a batch)."""
    import re
    with open(controller_path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    pat = re.compile(r"(?m)^(%s)(\s*:\s*bool)?\s*=.*$" % re.escape(flag))
    if pat.search(txt):
        txt = pat.sub(lambda m: "%s%s = %s" % (m.group(1), m.group(2) or "", value), txt)
        with open(controller_path, "w", encoding="utf-8", newline="") as f:
            f.write(txt)


def _disable_batch_plotting(controller_path):
    """Per-run dashboards/space-time/shockwave/per-bus plots (gated by
    MARK_DETECTION_POINTS) cost ~5 min PER RUN -- prohibitive for a 48-run batch
    and pointless (you want the final CSV, not 48 sets of plots). Turn them off
    for the batch so runs are ~3x faster and less exposed to a mid-plot crash."""
    for flag, val in (("MARK_DETECTION_POINTS", "False"),
                      ("OVERLAY_DETECTIONS_ON_MAP", "False"),
                      ("TRACK_BUS_POSITIONS", "False"),
                      ("STATUS_DASHBOARD_INTERVAL_S", "0.0")):
        try:
            _set_controller_flag(controller_path, flag, val)
        except Exception:
            pass

# Shared safety knobs applied to every analytic arm so they cannot gridlock the
# corridor (v4): a strict cost veto proxies the downstream cascade the per-
# decision models cannot see.  CellQLearn keeps ratio 1.0 (its Q learns cascade).
_SAFE_VETO = 3.0

ARMS = [
    {"name": "NO_TSP", "strategy": "NORMAL", "method": "NO_TSP",
     "coordinated": False, "coordination_algo": "KALMAN", "reward_overrides": {}},

    {"name": "CELLQLEARN", "strategy": "GLOBAL_REWARD", "method": "CELLQLEARN",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "BXT_DT_S": 1.0, "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.2, "BXT_GAMMA": 0.01,
        "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        # v6: DEFICIT timing solver -- use the closed-form bus deficit, skip the
        # degenerate shockwave objective that gridlocked golden (KG 140->105).
        # 2026-08-24: veto 3.0 REVERTED to 1.5 — the 3.0 test DISPROVED the "veto
        # blocks INS" theory: INS stayed 0 at 3.0 (the learner's Q never picks it,
        # it is not a veto issue) AND 3.0 let the learner OVER-EXTEND green during
        # training → gridlock (car up to 63). 1.5 keeps a little headroom over the
        # old 1.3 now that OFFSET_CORRECTION is out of the grid.
        "DECIDER_COST_VETO_RATIO": 1.5, "BXT_WARMSTART_FROM_SHARED": True,
        "BXT_SOLVER": "deficit",
        # v7 bus-equity + corridor reward sharing (see specialized_modes):
        # buses carry ~27x a car's pax so their seconds count double; on-time
        # buses inside the reachable window get a small green-keep credit so
        # the cost veto stops killing every action; each Q-update also credits
        # the signed realized-delay delta of corridor neighbors (w=0.5) so
        # queue-shoving onto the next junction no longer pays locally.
        # #3 (2026-08-24): dialed BUS_PAX_WEIGHT 2.0->1.3 and rolled back the
        # multi-bus platoon amplification (MULTIBUS_MAX_FACTOR 3.0->1.0) — both
        # were over-buying bus time and driving the uncounted OC/GR car cascade.
        "BUS_PAX_WEIGHT": 1.3, "GREEN_KEEP_CREDIT_S": 3.0,
        "MULTIBUS_MAX_FACTOR": 1.0,
        "CORRIDOR_REWARD_NEIGHBOR_W": 0.5,
        "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1}},

    {"name": "DCTSP_ZIG", "strategy": "GLOBAL_REWARD", "method": "DCTSP_ZIG",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "DCTSP_ZIG_MODE": True,
        "MP_ECTM_MODE": False, "BXT_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "ZIG_ENABLE_INS": False, "ZIG_ENABLE_SEQ": False, "ZIG_ENABLE_GR": False,
        "ZIG_BALANCE_FACTOR": 0.35, "ZIG_GE_BALANCE_FACTOR": 0.6,
        "ZIG_MIN_GAIN_S": 15.0, "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        "DCTSP_CONGESTION_GATE": True, "DCTSP_CONGESTION_GATE_FRACTION": 0.65}},

    {"name": "DCTSP_MP_ECTM", "strategy": "GLOBAL_REWARD", "method": "DCTSP_MP_ECTM",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "MP_ECTM_MODE": True,
        "DCTSP_ZIG_MODE": False, "BXT_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "MP_ECTM_DT_S": 1.0, "MP_ECTM_MIN_EXT_S": 5.0, "MP_ECTM_MAX_EXT_S": 10.0,
        "MP_ECTM_CAR_OCC": 1.2, "MP_ECTM_BALANCE_FACTOR": 0.6,
        "SELFORG_MIN_BUS_DELAY_S": 15.0, "DECIDER_COST_VETO_RATIO": _SAFE_VETO}},

    {"name": "DCTSP_BARGAIN_SPM", "strategy": "GLOBAL_REWARD", "method": "DCTSP_BARGAIN_SPM",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
        "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False, "BXT_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        "BG_BUS_W_IMM": 1.6, "BG_BUS_W_NEAR": 1.35, "BG_BUS_W_FAR": 1.10,
        "BG_MIN_BUS_DELAY_S": 5.0, "BG_MIN_GAIN_S": 5.0, "BG_CASCADE_MULT": 2.0,
        "DCTSP_CONGESTION_GATE": True, "DCTSP_CONGESTION_GATE_FRACTION": 0.75,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO}},

    {"name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD", "method": "DCTSP_MARL",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0, "REWARD_BETA": 1.0,
        "REWARD_GAMMA": 1.0, "DCTSP_GREEN_REALLOC_MODE": True,
        "GREEN_REALLOC_RECOVER_FRACTION": 1.0, "DCTSP_W_H": 0.50,
        "DCTSP_CAR_WEIGHT": 1.00, "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        "BXT_MODE": False, "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False,
        "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False}},

    {"name": "CENTRALISED", "strategy": "GLOBAL_REWARD", "method": "CENTRALISED",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "CENTRALIZED_MODE": True, "CENTRALIZED_INTERVAL_S": 1.0,
        "BXT_MODE": False, "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False,
        "BARGAIN_SPM_MODE": False, "CELLQLEARN_DP_MODE": False,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO}},

    # 8th arm (was CELLQLEARN_DP, which flopped at -37.8% -- the DP variant is
    # under-developed). Replaced with CELLQLEARN_SAFE: the same learner but MORE
    # SELECTIVE -- higher veto + the person-delay warrant + conditional priority
    # so it only fires for buses that are genuinely delayed and carry enough
    # people, testing whether "act rarely but well" generalises across seeds
    # better than the base CELLQLEARN.
    {"name": "CELLQLEARN_SAFE", "strategy": "GLOBAL_REWARD", "method": "CELLQLEARN",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "BXT_DT_S": 1.0, "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.2, "BXT_GAMMA": 0.01,
        "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        # v6: made genuinely DIFFERENT from CELLQLEARN (v5's veto 1.8/pd 400 were
        # in a dead zone -> byte-identical results). Now a BINDING conservatism:
        # SELFORG gate 15s means it only acts on buses delayed >15s (far fewer,
        # more-justified actions) + deficit solver + veto 2.0.
        "DECIDER_COST_VETO_RATIO": 2.0, "BXT_WARMSTART_FROM_SHARED": True,
        "BXT_SOLVER": "deficit",
        "SELFORG_MIN_BUS_DELAY_S": 15.0,
        "RULE_PERSON_DELAY_WARRANT": True, "PERSON_DELAY_WARRANT_MIN_PAXS": 400.0,
        # #3 (2026-08-24): dialed BUS_PAX_WEIGHT 2.0->1.3 and rolled back the
        # multi-bus platoon amplification (MULTIBUS_MAX_FACTOR 3.0->1.0) — both
        # were over-buying bus time and driving the uncounted OC/GR car cascade.
        "BUS_PAX_WEIGHT": 1.3, "GREEN_KEEP_CREDIT_S": 3.0,
        "MULTIBUS_MAX_FACTOR": 1.0,
        "CORRIDOR_REWARD_NEIGHBOR_W": 0.5,
        "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1}},

    # 9th/10th arms — MaxPressure (Varaiya 2013) via sumoITScontrol.
    # Ported from DerKevinRiehl/sumoITScontrol (GPL-3.0, ETHZ).  Pressure =
    # Σ upstream queue – Σ downstream queue (pax-weighted, bus ×27) using
    # detector + section counts (AKIVehStateGetNbVehiclesSection) and the
    # control_plans dump for per-phase signal-group→turning mapping.
    # Fix = fixed cycle, Flex = re-evaluates every T_A.  Both use ALL Aimsun
    # info: section geometries/turnings/detectors/control_plans/PT lines/OD
    # matrices + live MaxQueueLength/UpFlowList/JamDensity/SaturationFlow.
    {"name": "MAXPRESSURE_FIX", "strategy": "GLOBAL_REWARD", "method": "MAXPRESSURE_FIX",
     "coordinated": False, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "MAXPRESSURE_FIX_MODE": True,
        "MAXPRESSURE_FLEX_MODE": False, "BXT_MODE": False, "MP_ECTM_MODE": False,
        "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        # Cyclic (Varaiya-faithful): per-step pressure scheduler, bus-independent
        "MAXPRESSURE_CYCLIC": True,
        "MAXPRESSURE_G_MIN": 5, "MAXPRESSURE_G_MAX": 50, "MAXPRESSURE_T_L": 3,
        "MAXPRESSURE_CYCLE_FIX": 120, "MAXPRESSURE_MEAS_PERIOD": 4}},

    {"name": "MAXPRESSURE_FLEX", "strategy": "GLOBAL_REWARD", "method": "MAXPRESSURE_FLEX",
     "coordinated": False, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "MAXPRESSURE_FLEX_MODE": True,
        "MAXPRESSURE_FIX_MODE": False, "BXT_MODE": False, "MP_ECTM_MODE": False,
        "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        # Cyclic: FLEX re-evaluates argmax pressure every step (min-green +
        # hysteresis guarded) instead of only at bus detections.
        "MAXPRESSURE_CYCLIC": True,
        "MAXPRESSURE_G_MIN": 5, "MAXPRESSURE_G_MAX": 50, "MAXPRESSURE_T_L": 3,
        "MAXPRESSURE_CYCLE_FLEX": 120, "MAXPRESSURE_T_A": 5,
        "MAXPRESSURE_MEAS_PERIOD": 4}},
]


def _obj_ok(m):
    """True if the collected metrics carry a valid (non-blank, non-zero) objective."""
    try:
        v = m.get("stats_Objective_PaxPerDelayHr", "")
        return v not in ("", None) and float(v) != 0.0
    except Exception:
        return False


def _fnum(m, key):
    try:
        v = float(m.get(key))
        return v if v == v else None          # NaN -> None
    except Exception:
        return None


# Healthy reference points these thresholds were chosen against:
#   KG   (detectors cover cars):  ~8300 cars, avg car delay ~20 s, 56 buses
#   Logan (Option-B rev2 subst.): ~18700 cars, avg car delay ~224 s, 292 buses
# A run outside ANY of these bands is the silent-failure signature we spent
# days chasing (car counting collapsed / denominator garbage / PT scan dead),
# so shout [SANITY] immediately instead of poisoning 40 rows silently.
SANITY_MIN_CARS      = 500.0
SANITY_MAX_CAR_AVG_S = 600.0
SANITY_MIN_BUSES     = 5.0


def _kpi_sanity(m):
    """Return a list of human-readable problems with this run's KPIs ([] = healthy)."""
    problems = []
    ncars  = _fnum(m, 'stats_N_DistinctCars')
    nbuses = _fnum(m, 'stats_N_DistinctBuses')
    avgcar = _fnum(m, 'stats_AvgCarPassDelay_s')
    avgbus = _fnum(m, 'stats_AvgBusPassDelay_s')
    pax    = _fnum(m, 'stats_PaxEquivPassages')
    dur    = _fnum(m, 'stats_SimDuration_hrs')
    if ncars is None or ncars < SANITY_MIN_CARS:
        problems.append(f"N_DistinctCars={ncars} (<{SANITY_MIN_CARS:.0f} -- car counting collapsed)")
    if avgcar is None or not (0.0 < avgcar < SANITY_MAX_CAR_AVG_S):
        problems.append(f"AvgCarPassDelay_s={avgcar} "
                        f"(outside (0,{SANITY_MAX_CAR_AVG_S:.0f}) -- passenger denominator broken)")
    if nbuses is not None and nbuses < SANITY_MIN_BUSES:
        problems.append(f"N_DistinctBuses={nbuses} (<{SANITY_MIN_BUSES:.0f} -- PT/bus scan found nothing)")
    elif nbuses is None:
        problems.append("N_DistinctBuses missing -- stats row incomplete")
    if avgbus is not None and not (0.0 < avgbus < SANITY_MAX_CAR_AVG_S):
        problems.append(f"AvgBusPassDelay_s={avgbus} outside (0,{SANITY_MAX_CAR_AVG_S:.0f})")
    if pax is not None and pax <= 0.0:
        problems.append("PaxEquivPassages<=0 -- no passengers counted at all")
    if dur is not None and dur <= 0.0:
        problems.append("SimDuration_hrs<=0 -- network-stats finish hook likely never ran")
    return problems


_SIG_KEYS = ('stats_Objective_PaxPerDelayHr', 'stats_N_DistinctCars',
             'stats_N_DistinctBuses', 'stats_CarPaxEquivPassages',
             'stats_AvgCarPassDelay_s')


def _run_signature(m):
    """Rounded fingerprint of a run's headline KPIs (None if unusable)."""
    vals = tuple(round(_fnum(m, k) or 0.0, 3) for k in _SIG_KEYS)
    return vals if any(vals) else None


def _run_and_collect(_br, rep, name, strategy, seed, scalar, coordinated, coord_algo,
                     global_reward, reward_cfg, bus_pred, CONTROLLER_PATH,
                     RUN_CONFIG_PATH, PROJECT_DIR, RESULTS_CSV, log,
                     max_reruns=1, recollect_waits=(4, 8, 12)):
    """Run one replication and collect its metrics, hardened against the
    intermittent stats-collection race that silently blanked BARGAIN 400/700 on
    KG: if the objective comes back blank, WAIT and re-collect (the sim's
    post-processing may still be writing simulation_results.csv); only if that
    still fails do we re-run the whole replication (up to max_reruns)."""
    attempt = 0
    while True:
        _br.set_seed(rep, seed)
        _br.write_run_config(name, strategy, seed, scalar, coordinated, coord_algo,
                             RUN_CONFIG_PATH, global_reward_mode=global_reward,
                             reward_cfg=reward_cfg, bus_predictor=bus_pred,
                             results_csv_name=_os.path.basename(RESULTS_CSV))
        _br._purge_pyc(CONTROLLER_PATH)
        t0 = _time.time(); ok = True
        try:
            _br.run_replication(rep)
        except Exception as e:
            ok = False; log(f"  EXCEPTION: {e}")
        dt = _time.time() - t0

        m = None
        for w in (0,) + tuple(recollect_waits):
            if w:
                _time.sleep(w)
            try:
                m = _br.collect_run_metrics(PROJECT_DIR, strategy, seed, scalar,
                                            name, coordinated, dt, ok, bus_predictor=bus_pred)
            except Exception as e:
                log(f"  metrics FAIL: {e}"); m = None
            if m is not None and _obj_ok(m):
                return m
            if w:
                log(f"  blank stats — re-collecting after {w}s wait")
        # re-collect exhausted; re-run the whole replication if allowed
        if attempt < max_reruns:
            attempt += 1
            log(f"  still blank after re-collect — RE-RUNNING (attempt {attempt}/{max_reruns})")
            continue
        log(f"  WARNING: {name} seed={seed} produced no objective after {attempt} rerun(s); "
            f"keeping best-effort row")
        return m   # may be blank; ranker drops it


def main(arms=None, results_csv=None):
    """Run the champion search. Pass `arms` (a subset of ARMS) and `results_csv`
    to run a subset (see champion_subset.py); defaults to the full 8-arm search."""
    if arms is None:
        arms = ARMS
    RESULTS_CSV_ = results_csv or RESULTS_CSV
    log = _br.log
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    _learn_runs = sum(len(TRAIN_SEEDS) + len(EVAL_SEEDS) for a in arms if a["name"] in LEARNING_ARMS)
    _other_runs = sum(len(EVAL_SEEDS) for a in arms if a["name"] not in LEARNING_ARMS)
    n_total = (_learn_runs + _other_runs) * len(DEMAND_SCALARS)
    log("=" * 70)
    log(f"CHAMPION SEARCH (Phase 1) -- corridor={CORRIDOR}")
    log(f"  {len(arms)} arms | eval seeds={EVAL_SEEDS} | learners train on {TRAIN_SEEDS}")
    log(f"  total runs = {n_total}  (learners: train+eval; others: eval)")
    log(f"  -> {RESULTS_CSV_}")
    log("=" * 70)

    # fresh results file
    try:
        if _os.path.exists(RESULTS_CSV_):
            _os.remove(RESULTS_CSV_)
    except Exception:
        pass

    try:
        _br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    # Disable the ~5-min/run dashboards/plots for the whole batch (speed + fewer
    # points to crash on). Re-enable MARK_DETECTION_POINTS/TRACK_BUS_POSITIONS in
    # the controller afterwards if you want plots for a single diagnostic run.
    _disable_batch_plotting(CONTROLLER_PATH)

    rep = _br.get_first_replication()
    run_num = 0
    _flagged_runs = 0
    _last_sig = None
    base_demands = {}
    try:
        for scalar in DEMAND_SCALARS:
            try:
                _br.set_demand_scalar(scalar, base_demands)
            except Exception as e:
                log(f"WARN demand scalar {scalar}: {e}")

            for arm in arms:
                name = arm["name"]; strategy = arm["strategy"]
                coordinated = arm.get("coordinated", False)
                coord_algo = arm.get("coordination_algo", "KALMAN")
                rov = dict(arm.get("reward_overrides", {}) or {})
                is_baseline = (strategy == "NORMAL")
                if not is_baseline:
                    rov["Z4_CONSTRAINT_MODE"] = True
                    rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
                bus_pred = str(rov.get("BUS_PREDICTOR_TYPE", "ADAPTIVE_KALMAN")).upper()
                try:
                    _br.set_control_mode(strategy, CONTROLLER_PATH, arm.get("active_intersections"))
                    _br.set_coordinated(CONTROLLER_PATH, coordinated)
                    _br.set_coordination_algo(CONTROLLER_PATH, coord_algo)
                except Exception as e:
                    log(f"FATAL patch {name}: {e}"); continue
                _global_reward = bool(rov.get("GLOBAL_REWARD_MODE", False))
                _numeric = {k: v for k, v in rov.items() if k != "GLOBAL_REWARD_MODE"}
                # ALWAYS reset/patch reward weights: overrides for TSP arms, None
                # for the baseline. Passing None resets every mode flag to False in
                # the controller file so a prior arm's flags cannot LEAK into a
                # later baseline run (defensive — NO_TSP runs first here so it is
                # already clean, but this makes the dispatch order-independent and
                # rules out the "all arms identical" failure mode).
                try:
                    _br.set_reward_weights(
                        CONTROLLER_PATH,
                        (_numeric or None) if not is_baseline else None)
                except Exception as e:
                    log(f"WARN reward patch {name}: {e}")

                # ── FAIR TRAINING: learners train-then-freeze; others per_seed ──
                is_learner = name in LEARNING_ARMS
                if is_learner:
                    seeds_to_run = list(TRAIN_SEEDS) + list(EVAL_SEEDS)
                    _set_controller_bxt_seeds(CONTROLLER_PATH, TRAIN_SEEDS, EVAL_SEEDS, BXT_TRAIN_EPSILON)
                else:
                    seeds_to_run = list(EVAL_SEEDS)
                    _set_controller_bxt_seeds(CONTROLLER_PATH, [], [], BXT_TRAIN_EPSILON)

                for seed in seeds_to_run:
                    run_num += 1
                    _phase = "train" if (is_learner and seed in TRAIN_SEEDS) else "eval"
                    log(f"[{run_num}/{n_total}] {CORRIDOR} | {name} | seed={seed} | {_phase}")
                    # collection-race retry: re-collect (short wait) then re-run once
                    m = _run_and_collect(_br, rep, name, strategy, seed, scalar,
                                         coordinated, coord_algo, _global_reward,
                                         (None if is_baseline and not _numeric else (_numeric or None)),
                                         bus_pred, CONTROLLER_PATH, RUN_CONFIG_PATH,
                                         PROJECT_DIR, RESULTS_CSV_, log)
                    if m is not None:
                        _br.append_master_csv(RESULTS_CSV_, m)
                        # ── [SANITY] live health gate ──────────────────────
                        _problems = _kpi_sanity(m)
                        for _p in _problems:
                            log(f"  [SANITY] WARNING: {_p}")
                        _sig = _run_signature(m)
                        if _sig is not None and _sig == _last_sig:
                            log("  [SANITY] WARNING: headline KPIs byte-identical to the "
                                "previous run -- suspect a no-op controller patch or a "
                                "stale module that never reloaded")
                        if _problems or (_sig is not None and _sig == _last_sig):
                            _flagged_runs += 1
                        _last_sig = _sig
    finally:
        try:
            _br._set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    log("=" * 70)
    log(f"DONE ({CORRIDOR}) -> {RESULTS_CSV_}")
    if _flagged_runs:
        log(f"SANITY SUMMARY: {_flagged_runs}/{run_num} run(s) FLAGGED -- "
            f"review the [SANITY] WARNING lines above before ranking")
    else:
        log(f"SANITY SUMMARY: all {run_num} runs healthy")
    log("=" * 70)


if __name__ == "__main__":
    main()
