"""
champion_search.py -- Phase 1 of the BCC113 simulation matrix.

CHAMPION SEARCH: 11 strategy arms x 5 evaluation seeds at x1.0 demand;
learning arms also run the configured pre-training seeds.
Determines the champion (best mean objective vs NO_TSP) for KG and Logan Road.

HOW TO RUN (inside Aimsun, one corridor at a time)
--------------------------------------------------
  1. Open the KG model in Aimsun  -> run this script from the Python console.
     It auto-detects "kg" from the open model and writes champion_kg.csv.
  2. Open the Logan Road model    -> run this script again.
     It writes champion_logan_road_new.csv.
  3. From a normal terminal:  python rank_champions.py
     -> prints the ranked arms and the champion for each corridor.

The 11 arms (10 TSP strategies + NO_TSP baseline; edit ARMS to taste):
  NO_TSP, CELLQLEARN (BXT), DCTSP_ZIG (HSLWR), DCTSP_MP_ECTM (CTMGS),
    DCTSP_BARGAIN_SPM (bargaining heuristic), NASH_BARGAIN (real Nash game),
    DCTSP_MARL, CENTRALISED,
        CELLQLEARN_SAFE, CELLQLEARN_FORCED, MILP_MPC.
MILP_MPC is the real OR-Tools CP-SAT rolling-horizon controller (CONTROL_MODE),
replacing the former single-cycle greedy MILP_TSP selector (which never actually
optimised over MILP_HORIZON_CYCLES). It REQUIRES OR-Tools in Aimsun's Python.
CELLQLEARN_SAFE is the "one more" pick -- a more-selective CellQLearn variant
testing whether acting rarely-but-well generalises across seeds better than
the base learner.
"""
import os as _os, sys as _sys, time as _time, glob as _glob, importlib.util as _ilu

# ── 1. Detect which corridor's model is open (most-recent Aimsun lock file) ────
def _module_root(_marker="champion_search.py"):
    # __file__ is undefined when loaded in the Aimsun console (import/paste);
    # fall back to the open model's document directory, then CWD. (2026-09-22)
    try:
        return _os.path.dirname(_os.path.abspath(__file__))
    except (NameError, TypeError):
        pass
    try:
        from PyANGKernel import GKSystem
        _d = _os.path.abspath(str(GKSystem.getSystem().getActiveModel(
            ).getDocumentDirectory().absolutePath()))
        for _i in range(4):
            if _os.path.isfile(_os.path.join(_d, _marker)):
                return _d
            _d = _os.path.dirname(_d)
    except Exception:
        pass
    return _os.path.abspath(_os.getcwd())

_ROOT = _module_root()
def _detect_corridor():
    # ── PRIMARY: the model ACTUALLY OPEN in Aimsun ───────────────────────────
    # A stale <corridor>/*.ang.lck (left by an unclean close) must NOT decide the
    # corridor -- that silently loads the WRONG corridor's batch_runner + configs
    # (and hides [TIMING], which only kg's runner has). The active model's own
    # document directory / name is authoritative; locks are only a fallback.
    try:
        from PyANGKernel import GKSystem
        _m = GKSystem.getSystem().getActiveModel()
        _dd = ""
        try:
            _dd = _os.path.normcase(_os.path.abspath(
                _m.getDocumentDirectory().absolutePath()))
        except Exception:
            _dd = ""
        for c in ("kg", "logan_road_new"):
            _cd = _os.path.normcase(_os.path.abspath(_os.path.join(_ROOT, c)))
            if _dd and (_dd == _cd or _dd.startswith(_cd + _os.sep)
                        or _os.path.basename(_dd) == c):
                return c, _os.path.join(_ROOT, c)
        _nm = ""
        try:
            _nm = (_m.getName() or "").lower()
        except Exception:
            _nm = ""
        if "logan" in _nm:
            return "logan_road_new", _os.path.join(_ROOT, "logan_road_new")
        if "kger" in _nm or "teg_kg" in _nm or _nm.startswith("kg"):
            return "kg", _os.path.join(_ROOT, "kg")
    except Exception:
        pass
    # ── FALLBACK: lock files (only when the active model is unresolvable) ─────
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
    raise RuntimeError("Could not detect corridor (no active model and no "
                       ".ang.lck under kg/ or logan_road_new/). "
                       "Open the corridor model in Aimsun before running.")

CORRIDOR, CORR_DIR = _detect_corridor()
try:
    print(f"[CHAMPION] corridor={CORRIDOR!r}  runner={_os.path.join(CORR_DIR, 'batch_runner.py')}")
except Exception:
    pass


def _assert_corridor_matches_active_model(chosen):
    """Belt-and-suspenders: independently re-derive the corridor from the OPEN
    model and ABORT if it contradicts `chosen`. Guards against ever running one
    corridor's runner/config against the other corridor's network (the stale-
    lock trap). If the active model is unresolvable (offline/no model), only
    warn -- running requires an open model, so the real run still gets checked.
    """
    try:
        from PyANGKernel import GKSystem
        _m = GKSystem.getSystem().getActiveModel()
    except Exception:
        _m = None
    if _m is None:
        print("[CHAMPION] WARN: no active model to verify corridor against "
              f"(chose {chosen!r} from lock/cwd fallback).")
        return
    _dd = ""
    try:
        _dd = _os.path.normcase(_os.path.abspath(
            _m.getDocumentDirectory().absolutePath()))
    except Exception:
        _dd = ""
    _nm = ""
    try:
        _nm = (_m.getName() or "").lower()
    except Exception:
        _nm = ""
    # Independently decide what the OPEN model says the corridor is.
    _model_says = None
    for c in ("kg", "logan_road_new"):
        _cd = _os.path.normcase(_os.path.abspath(_os.path.join(_ROOT, c)))
        if _dd and (_dd == _cd or _dd.startswith(_cd + _os.sep)
                    or _os.path.basename(_dd) == c):
            _model_says = c
            break
    if _model_says is None:
        if "logan" in _nm:
            _model_says = "logan_road_new"
        elif "kger" in _nm or "teg_kg" in _nm or _nm.startswith("kg"):
            _model_says = "kg"
    if _model_says is None:
        print(f"[CHAMPION] WARN: could not classify active model "
              f"(name={_nm!r}, dir={_dd!r}); trusting chosen corridor {chosen!r}.")
        return
    if _model_says != chosen:
        raise RuntimeError(
            "CORRIDOR GUARD: the OPEN Aimsun model is corridor "
            f"{_model_says!r} (name={_nm!r}, dir={_dd!r}) but the pipeline "
            f"selected {chosen!r}. Refusing to run one corridor's "
            "runner/config against the other's network. This is usually a "
            "STALE <corridor>/*.ang.lck -- close/reopen the intended model (or "
            "clear the stale lock) and re-run.")
    print(f"[CHAMPION] corridor guard OK: open model agrees ({chosen!r}).")


_assert_corridor_matches_active_model(CORRIDOR)

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
LEARNING_ARMS = {
    "CELLQLEARN", "CELLQLEARN_FORCED", "CELLQLEARN_GATED",
    "CELLQLEARN_SAFE", "CELLQ_BUSSPLIT", "CELLQ_LEARN_UNCOORD",
    "CELLQ_VDET_BUSSPLIT", "CELLQ_VDET_ON", "DCTSP_MARL_RL",
}
BXT_TRAIN_EPSILON = 0.30                    # exploration during the learners' train phase

TOPUP_EVAL_SEEDS = [300, 1200, 1300, 1400, 1500, 1600]
GATE_SEED = 300
GATE_EXPECT_BUSES = 516
GATE_EXPECT_INTERVENTIONS = 26
GATE_EXPECT_S_PER_PAX = 15.84

# Whether the learner Q-table is FROZEN during the scored seeds.
#   True  -> legacy train-then-freeze: reproduces the September champion numbers
#            and the seed-300 gate above. The engine default (False, "never
#            freeze") is deliberately NOT used here because September's
#            bit-identical repeat runs are the signature of a frozen policy.
#   False -> the table keeps learning through the scored seeds (exploration at
#            BXT_TRAIN_EPSILON). That is a DIFFERENT experiment: repeat runs of
#            the same seed legitimately differ, so it cannot reproduce September
#            and its numbers must not be pooled with frozen-policy results.
LEARNERS_FREEZE_ON_EVAL = True

# Set True to run the top-up seed set instead of EVAL_SEEDS.
USE_TOPUP_SEEDS = True
DEMAND_SCALARS = [1.0]                      # x1.0 demand
BUS_FREQ_INJECT_SCALAR = 0.0                # runtime PT frequency scaling
RESULTS_CSV = _os.path.join(_ROOT, f"champion_{CORRIDOR}.csv")

# Effective scored-seed set. The top-up keeps GATE_SEED in the list so the
# reproduction gate is produced by the same run as the new seeds.
SCORED_SEEDS = list(TOPUP_EVAL_SEEDS) if USE_TOPUP_SEEDS else list(EVAL_SEEDS)
DEMAND_SCALARS = [1.0]                      # x1.0 demand
BUS_FREQ_INJECT_SCALAR = 0.0                # runtime PT frequency scaling
# Multi-regime (domain-randomization) training (task a): when non-empty, each
# LEARNER TRAIN seed is paired with a demand level cycled from this list, so the
# policy sees varying demand during training and can generalize to real-time
# level changes. EVAL seeds always run at DEMAND_SCALARS (1.0) for a fair, fixed
# comparison. Pair with BXT_DEMAND_STATE=True in the arm so the policy can
# actually CONDITION on the regime (otherwise it just averages over them).
BXT_TRAIN_DEMAND_SCALARS = []               # e.g. [0.5, 0.75, 1.0, 1.5, 2.0]
# GLOBAL_MEASURED_FEED: feed EVERY arm the MEASURED (verified section-total) flow
# state AND the measured queue floor -- not just the *_MEAS variants. The
# measured method is far more reliable than the LWR/shockwave estimate, so all
# controllers should decide on it (2026-09-10). Injected as a setdefault so an
# arm can still opt out explicitly. Engine reads MEASURED_STATE_FEED /
# MEASURED_QUEUE_FEED from run_config (already in the propagation list).
GLOBAL_MEASURED_FEED = True
# SMOKE_HEURISTIC_PRIOR: in the SMOKE run learners are eval-only with train=[], so
# their Q-table is empty and a frozen BXT learner argmaxes NO_ACTION for every bus
# -> byte-identical to NO_TSP (looks "broken"). When this is on, _run_and_collect
# injects BXT_INS_OPTIMISTIC_INIT into every BXT learner arm so an UNTRAINED
# CELLQLEARN acts like traditional TSP (advance held buses / extend green) instead
# of doing nothing -- making the smoke comparison meaningful. Set by the pipeline's
# _apply_smoke; OFF by default so the FULL pipeline's training is untouched (the
# seed gridlocked training -- see BXT_INS_OPTIMISTIC_INIT note in specialized_modes).
SMOKE_HEURISTIC_PRIOR = False
SMOKE_HEURISTIC_PRIOR_INIT = 120.0   # optimistic Q seed (pax-s) used when the above is on
# GLOBAL_MEASURED_SIDE_COST: price the cross (side) cost from the MEASURED cross-
# approach congestion (spillback-severity) so a near-jammed cross street is never
# under-priced -- the fix for the seed-lottery car cascades where predicted cross
# cost was ~uncorrelated with realized. Injects MEASURED_SIDE_COST into every arm
# (setdefault); the engine's _compute_side_delay_penalty then returns the WORSE of
# analytic vs measured, which flows into the net-benefit gate + cost veto.
GLOBAL_MEASURED_SIDE_COST = True
# GLOBAL_CASCADE_COST: price the DOWNSTREAM multi-hop cascade (projected-
# saturation spillback 2-3 junctions along the corridor) into every TSP arm's
# cross cost -- the real seed-lottery lever (gridlock forms downstream, not on
# the immediate cross approach). Injected (setdefault) into every non-baseline
# arm; the engine's _cascade_spillback_paxs charges on POST-release saturation.
GLOBAL_CASCADE_COST = True
# EVAL_DIAGNOSTICS: emit the [BXT_EVAL] predicted-vs-realized line for BXT arms in
# ANY run (not just smoke), so you can get per-seed calibration on the bad seeds
# (500/700). Policy stays frozen in eval (no Q update). Toggle via env
# BXT_EVAL_DIAG=1 without editing the file. Parse with analyze_bxt_predictions.py.
EVAL_DIAGNOSTICS = (_os.environ.get("BXT_EVAL_DIAG", "0") == "1")
RESULTS_CSV = _os.path.join(_ROOT, f"champion_{CORRIDOR}.csv")


def _set_controller_bxt_seeds(controller_path, train, eval_, train_eps,
                              freeze_on_eval=None):
    """Patch BXT_TRAIN_SEEDS / BXT_EVAL_SEEDS / BXT_TRAIN_EPSILON in the corridor
    controller so the engine trains-then-freezes (learners) or runs per_seed
    (empty lists -> non-learners). Adds the lines if the controller lacks them
    (Logan's controller does).

    freeze_on_eval (2026-09-30): whether the Q-table keeps learning during the
    SCORED seeds. None = leave the engine default alone (BXT_FREEZE_ON_EVAL =
    False, "never freeze"). True = restore the legacy frozen-policy behaviour
    that produced the September champion numbers, which the seed-300
    reproduction gate (516 buses / 26 interventions / 15.84 s per pax) requires.
    Note the distinction that the September twins expose: with train+eval lists
    set, the table is trained then HELD across eval seeds (bit-identical
    repeats); with BOTH lists cleared the phase is per_seed and the engine
    calls reset_bxt_learning() every run, which cold-starts instead of freezing
    -- that is the bug in run_kg_champion_and_phase2, not a freeze."""
    import re
    with open(controller_path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    repl = {
        "BXT_TRAIN_SEEDS": repr(list(train)),
        "BXT_EVAL_SEEDS": repr(list(eval_)),
        "BXT_TRAIN_EPSILON": repr(float(train_eps)),
    }
    if freeze_on_eval is not None:
        repl["BXT_FREEZE_ON_EVAL"] = repr(bool(freeze_on_eval))
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

    # ── ABLATION WINNERS promoted into the champion matrix (2026-10-01) ──────
    # Four arms run in run_all_test.py that each BEAT fixed-time on seed 300:
    #   CELLQ_LEARN_UNCOORD   +12.0%
    #   CELLQ_VDET_ON         +11.2%
    #   CELLQ_BUSSPLIT        +17.4%   <-- best
    #   CELLQ_VDET_BUSSPLIT   +11.2%
    # Promoted so the full champion_search scores them against the paper's arms on
    # the same seeds. Config copied verbatim from run_all_test._CELLQ_BASE, so both
    # runners test the SAME thing; only the two flag deltas differ between arms.
    {"name": "CELLQ_LEARN_UNCOORD", "strategy": "GLOBAL_REWARD",
     "method": "CELLQLEARN", "coordinated": False, "coordination_algo": "KALMAN",
     "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_ALPHA": 0.3, "BXT_GAMMA": 0.5, "BXT_EPSILON": 0.02,
        "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
        "MEASURED_SIDE_COST": True}},

    {"name": "CELLQ_VDET_ON", "strategy": "GLOBAL_REWARD",
     "method": "CELLQLEARN", "coordinated": False, "coordination_algo": "KALMAN",
     "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_ALPHA": 0.3, "BXT_GAMMA": 0.5, "BXT_EPSILON": 0.02,
        "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
        "MEASURED_SIDE_COST": True,
        "VIRTUAL_DET_FROM_PLAN": True}},

    {"name": "CELLQ_BUSSPLIT", "strategy": "GLOBAL_REWARD",
     "method": "CELLQLEARN", "coordinated": False, "coordination_algo": "KALMAN",
     "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_ALPHA": 0.3, "BXT_GAMMA": 0.5, "BXT_EPSILON": 0.02,
        "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
        "MEASURED_SIDE_COST": True,
        "EXCLUDE_BUS_FROM_CAR_QUEUE": True}},

    {"name": "CELLQ_VDET_BUSSPLIT", "strategy": "GLOBAL_REWARD",
     "method": "CELLQLEARN", "coordinated": False, "coordination_algo": "KALMAN",
     "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_CORRIDOR_MODE": True,
        "CELLQ_CORRIDOR_LEARN": True,
        "BXT_ALPHA": 0.3, "BXT_GAMMA": 0.5, "BXT_EPSILON": 0.02,
        "MEASURED_STATE_FEED": True, "MEASURED_QUEUE_FEED": True,
        "MEASURED_SIDE_COST": True,
        "VIRTUAL_DET_FROM_PLAN": True,
        "EXCLUDE_BUS_FROM_CAR_QUEUE": True}},

    {"name": "CELLQLEARN", "strategy": "GLOBAL_REWARD", "method": "CELLQLEARN",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "BXT_DT_S": 1.0, "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.2, "BXT_GAMMA": 0.01,
        "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        # 2026-08-26: Logan cross-street pressure is ~2x KG. Added minimum gain
        # so the learner only acts when TSP genuinely saves bus time, avoiding
        # the 0% action rate seen on Logan where every extension hurts more than it helps.
        "CELLQLEARN_MIN_GAIN_S": 15.0,
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

    # CELLQLEARN_GATED (2026-09-10): identical to CELLQLEARN but with the
    # NET-BENEFIT GATE on -- a BXT action is vetoed unless the bus
    # passenger-seconds saved exceed the cross-traffic passenger-seconds cost
    # (TOTAL-passenger accounting, no bus-priority weight in the gate itself).
    # Tests whether gating out net-negative actions stops TSP being worse than
    # NO_TSP on the car-dominated KG corridor. Compare head-to-head vs CELLQLEARN.
    {"name": "CELLQLEARN_GATED", "strategy": "GLOBAL_REWARD", "method": "CELLQLEARN",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "BXT_DT_S": 1.0, "BXT_EPSILON": 0.02, "BXT_ALPHA": 0.2, "BXT_GAMMA": 0.01,
        "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        "CELLQLEARN_MIN_GAIN_S": 15.0,
        "DECIDER_COST_VETO_RATIO": 1.5, "BXT_WARMSTART_FROM_SHARED": True,
        "BXT_SOLVER": "deficit",
        "BXT_NET_BENEFIT_GATE": True,
        # CTM cell-to-cell cascade: price the downstream-spillback cost so the
        # net-benefit gate rejects actions that gridlock the corridor (the local
        # cost missed this; it's why un-gated CELLQLEARN was seed-lottery).
        "CASCADE_COST_MODE": True,
        "BUS_PAX_WEIGHT": 1.3, "GREEN_KEEP_CREDIT_S": 3.0,
        "MULTIBUS_MAX_FACTOR": 1.0,
        "CORRIDOR_REWARD_NEIGHBOR_W": 0.5,
        "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1}},

    # Forced CellQLearn: relaxed action gates and stronger bus weighting, while
    # disabling the separate CorridorCoordinator so this run tests CTM/Q-learning
    # coordination on its own rather than BXT plus SHOCKWAVE pre-arming.
    {"name": "CELLQLEARN_FORCED", "strategy": "GLOBAL_REWARD", "method": "CELLQLEARN",
     "coordinated": False, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "BXT_DT_S": 1.0, "BXT_EPSILON": 0.1, "BXT_ALPHA": 0.3, "BXT_GAMMA": 0.01,
        "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
        "CELLQLEARN_MIN_GAIN_S": 2.0,
        "DECIDER_COST_VETO_RATIO": 0.8,
        "BUS_PAX_WEIGHT": 2.0, "GREEN_KEEP_CREDIT_S": 3.0,
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
        # 2026-08-26: corridor-tuned balance factor: KG permissive (0.8), Logan conservative (0.4)
"MP_ECTM_CAR_OCC": 1.2, "MP_ECTM_BALANCE_FACTOR": 0.8,
        "SELFORG_MIN_BUS_DELAY_S": 15.0, "DECIDER_COST_VETO_RATIO": _SAFE_VETO}},

    {"name": "DCTSP_BARGAIN_SPM", "strategy": "GLOBAL_REWARD", "method": "DCTSP_BARGAIN_SPM",
     "coordinated": True, "coordination_algo": "SHOCKWAVE", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
        "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False, "BXT_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        # BARGAIN is -25.2% KG / -14.6% Logan — over-eager. Gate harder and
        # weight buses lower, but keep KG's original aggressiveness behind a
        # corridor switch so KG cannot regress.
        "BG_BUS_W_IMM": 1.25 if CORRIDOR == "logan_road_new" else 1.6,
        "BG_BUS_W_NEAR": 1.15 if CORRIDOR == "logan_road_new" else 1.35,
        "BG_BUS_W_FAR": 1.00 if CORRIDOR == "logan_road_new" else 1.10,
        "BG_MIN_BUS_DELAY_S": 15.0 if CORRIDOR == "logan_road_new" else 5.0,
        "BG_MIN_GAIN_S": 12.0 if CORRIDOR == "logan_road_new" else 5.0,
        "BG_CASCADE_MULT": 3.0 if CORRIDOR == "logan_road_new" else 2.0,
        "DCTSP_CONGESTION_GATE": True,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.60 if CORRIDOR == "logan_road_new" else 0.75,
        # 2026-09-14: hard NET-BENEFIT VETO (was only a weighted sum) so the
        # cascade/measured cross cost can actually STOP a net-negative bargain.
        "BXT_NET_BENEFIT_GATE": True,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO}},

    {"name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD", "method": "DCTSP_MARL",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0, "REWARD_BETA": 1.0,
        "REWARD_GAMMA": 1.0, "DCTSP_GREEN_REALLOC_MODE": True,
        "GREEN_REALLOC_RECOVER_FRACTION": 1.0, "DCTSP_W_H": 0.50,
        "DCTSP_CAR_WEIGHT": 1.00,
        # 2026-08-26: Logan runs ~2x car pressure of KG. Earlier regression
        # was NOT this tuning — it was wave/focus gating starving late-bus
        # services (now fixed: all gates are adherence-aware).
        "DECIDER_COST_VETO_RATIO": 3.5 if CORRIDOR == "logan_road_new" else _SAFE_VETO,
        # Viability gate ON (2026-09-12): stand down to fixed-time when the
        # junction saturates or cross pressure dominates, instead of firing
        # into gridlock on heavy demand samples (MARL 163-246 seed spread).
        "DCTSP_CONGESTION_GATE": True,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.70,
        "BXT_MODE": False, "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False,
        "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False}},

    # DCTSP_MARL_MEAS / DCTSP_MARL_MEAS_Q REMOVED 2026-09-11 (audited out): with
    # GLOBAL_MEASURED_FEED forcing MEASURED_STATE_FEED+MEASURED_QUEUE_FEED on
    # EVERY arm, these were byte-identical to DCTSP_MARL (confirmed: same obj/car/
    # actions). Re-add only if GLOBAL_MEASURED_FEED is turned off to compare
    # measured-vs-LWR.

    # DCTSP_MARL_RL: the same MARL lineage but as a REAL learner — per-junction
    # tabular Q-learning (CPDQL_MODE) over the paper's 54 states x 7 actions,
    # epsilon-greedy, alpha=0.1, gamma=0.9, trained on TRAIN_SEEDS and frozen
    # on EVAL_SEEDS like the other learning arms.
    {"name": "DCTSP_MARL_RL", "strategy": "GLOBAL_REWARD", "method": "DCTSP_MARL",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "CPDQL_MODE": True,
        "CPDQL_ALPHA": 0.1, "CPDQL_GAMMA": 0.9, "CPDQL_EPSILON": 0.1,
        "CPDQL_TRAIN_EPSILON": BXT_TRAIN_EPSILON,
        "CPDQL_W_H": 0.5, "CPDQL_CAR_OCC": 1.5, "CPDQL_MIN_GAIN_S": 0.0,
        "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
        "DCTSP_GREEN_REALLOC_MODE": False,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        "BXT_MODE": False, "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False,
        "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False}},

    # DCTSP_MARL_RL_MEAS REMOVED 2026-09-11 (audited out): identical to
    # DCTSP_MARL_RL once GLOBAL_MEASURED_FEED is on (its only delta was
    # MEASURED_STATE_FEED, now global).

    {"name": "CENTRALISED", "strategy": "GLOBAL_REWARD", "method": "CENTRALISED",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "CENTRALIZED_MODE": True, "CENTRALIZED_INTERVAL_S": 1.0,
        "BXT_MODE": False, "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False,
        "BARGAIN_SPM_MODE": False, "CELLQLEARN_DP_MODE": False,
        "DECIDER_COST_VETO_RATIO": 3.5 if CORRIDOR == "logan_road_new" else _SAFE_VETO,
        "DCTSP_CONGESTION_GATE": True if CORRIDOR == "logan_road_new" else False,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.70}},

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
        # 2026-08-26: Logan cross-street pressure is ~2x KG. Added minimum gain
        # so the learner only acts when TSP genuinely saves bus time, avoiding
        # the 0% action rate seen on Logan where every extension hurts more than it helps.
        "CELLQLEARN_MIN_GAIN_S": 15.0,
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

    # NASH_BARGAIN: the REAL (generalized) Nash bargaining controller. Tier 1
    # maximizes the Nash PRODUCT of Transit vs Cross-street gains-over-threat
    # (dctsp_nash_bargain); Tier 2 (NASH_CORRIDOR_MODE) couples junctions along
    # the bus route into a Gauss-Seidel best-response equilibrium. This REPLACES
    # the old NASH_GATE, which was just the bargaining heuristic under a different
    # log tag (a weighted SUM, with its NASH_* knobs inert).
    {"name": "NASH_BARGAIN", "strategy": "GLOBAL_REWARD", "method": "NASH_BARGAIN",
     "coordinated": True, "coordination_algo": "NASH", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "NASH_BARGAIN_MODE": True,
        "NASH_CORRIDOR_MODE": True,
        "NASH_GATE_MODE": False, "BARGAIN_SPM_MODE": False, "DCTSP_ZIG_MODE": False,
        "MP_ECTM_MODE": False, "BXT_MODE": False,
        "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
        # bargaining powers p_T (transit) vs p_C (cross). NET-SURPLUS objective
        # (p_T=0, p_C=1): select the action that reduces TOTAL passenger delay the
        # MOST (max surplus = bus pax-s saved - cross pax-s cost), the Coase-
        # efficient bargaining outcome -- this is what "reduce net total passenger
        # delay" requires. The symmetric product (1,1) instead maximises
        # bps*surplus and over-weights raw bus benefit (2026-09-10). Individual
        # rationality (bps>cpc) is still enforced inside _nash_bargain_pick.
        "NASH_BUS_WEIGHT": 0.0, "NASH_CROSS_WEIGHT": 1.0,
        # CTM cell-to-cell cascade in cpc: the bargain surplus (bps-cpc) now
        # includes downstream spillback, so it won't "bargain" an action that
        # gridlocks the corridor.
        "CASCADE_COST_MODE": True,
        # corridor best-response coupling + convergence
        "NASH_NEIGHBOR_WEIGHT": 0.5, "NASH_MAX_ITER": 10,
        "NASH_CONVERGENCE_TOL": 0.01,
        # bargain the action DURATION at integer-second resolution, not {5,10,15}
        "NASH_INTEGER_DURATIONS": True,
        "NASH_MIN_BUS_DELAY_S": 5.0, "NASH_MIN_GAIN_S": 5.0,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        # Viability gate ON (2026-09-12): stand down on saturation instead of
        # bargaining into gridlock (NASH seed spread 113-193 on KG).
        "DCTSP_CONGESTION_GATE": True,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.70}},

    # ── MaxPressure family ────────────────────────────────────────────────────
    # Pax-weighted MaxPressure with transit priority (Riehl et al. 2026 base): a
    # queued bus counts ~27x a car, so the pressure calc itself prioritises
    # transit. FIX recomputes a proportional green split each cycle boundary;
    # FLEX re-evaluates every T_A. Both were dispatched in the engine but never
    # entered in the champion search -- add them as the MaxPressure benchmark.
    {"name": "MAXPRESSURE_FIX", "strategy": "GLOBAL_REWARD", "method": "MAXPRESSURE_FIX",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "MAXPRESSURE_FIX_MODE": True,
        "MAXPRESSURE_FLEX_MODE": False,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BXT_MODE": False,
        "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False,
        "CELLQLEARN_DP_MODE": False, "NASH_BARGAIN_MODE": False,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        "DCTSP_CONGESTION_GATE": True,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.70}},

    {"name": "MAXPRESSURE_FLEX", "strategy": "GLOBAL_REWARD", "method": "MAXPRESSURE_FLEX",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "MAXPRESSURE_FLEX_MODE": True,
        "MAXPRESSURE_FIX_MODE": False,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BXT_MODE": False,
        "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False,
        "CELLQLEARN_DP_MODE": False, "NASH_BARGAIN_MODE": False,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        "DCTSP_CONGESTION_GATE": True,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.70}},

    # MAXPRESSURE_LB: MP-TSP-LB (Kobeissi, Li, Mahmassani & Chen 2026,
    # doi:10.1177/03611981261444712). The FLEX MaxPressure PLUS the paper's two
    # CORRIDOR terms (both default OFF in the engine; this arm turns them on):
    #  (1) dwelling-bus LANE BLOCKAGE -- a bus dwelling at a near-side stop blocks
    #      a through lane, so that phase's pressure is scaled by the surviving
    #      lane fraction: MaxPressure stops pouring green onto a queue the stopped
    #      bus physically blocks (and the bus, boarding, does not need it yet).
    #  (2) CORRIDOR COORDINATION -- the through-phase pressure is discounted when
    #      the DOWNSTREAM main link is near jam (capacity-aware back-pressure via
    #      the CorridorCoordinator route index + the measured queue), so the
    #      junction does not push a platoon into a link that will spill back.
    # Compare head-to-head vs MAXPRESSURE_FLEX to isolate the LB + coordination gain.
    {"name": "MAXPRESSURE_LB", "strategy": "GLOBAL_REWARD", "method": "MAXPRESSURE_FLEX",
     "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "MAXPRESSURE_FLEX_MODE": True,
        "MAXPRESSURE_FIX_MODE": False,
        "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BXT_MODE": False,
        "BARGAIN_SPM_MODE": False, "CENTRALIZED_MODE": False,
        "CELLQLEARN_DP_MODE": False, "NASH_BARGAIN_MODE": False,
        # (1) dwelling-bus lane blockage
        "MP_LANEBLOCK_MODE": True, "MP_LANEBLOCK_LANES": 1.0, "MP_DWELL_MIN_S": 5.0,
        # (2) corridor coordination (downstream-spillback discount on through phase)
        "MP_CORRIDOR_COORD_MODE": True, "MP_CORRIDOR_COORD_WEIGHT": 1.0,
        "MP_CORRIDOR_SAT_THRESHOLD": 0.6,
        "DECIDER_COST_VETO_RATIO": _SAFE_VETO,
        "DCTSP_CONGESTION_GATE": True,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.70}},

    # MILP-based TSP — selects a fixed-duration signal action with bus priority.
    # It does not optimize a continuous timing schedule.
    # MILP_MPC: the REAL multi-period rolling-horizon MILP (OR-Tools CP-SAT,
    # milp_mpc_controller.py) run as its own CONTROL_MODE -- NOT the old
    # single-cycle greedy dctsp_milp_tsp decider (which never actually used
    # MILP_HORIZON_CYCLES). strategy="MILP_MPC" makes set_control_mode patch
    # CONTROL_MODE="MILP_MPC" so the per-second horizon controller runs.
    # REQUIRES OR-Tools installed in Aimsun's Python; the engine logs
    # [MILP_MPC] FATAL and produces no TSP if it is missing.
    {"name": "MILP_MPC", "strategy": "MILP_MPC", "method": "MILP_MPC",
    "coordinated": True, "coordination_algo": "KALMAN", "reward_overrides": {
        "MILP_MPC_HORIZON_S": 300.0, "MILP_MPC_REPLAN_S": 30.0,
        "MILP_MPC_TIME_LIMIT_S": 1.5, "MILP_MPC_EPSILON_LATE_S": 60.0,
        "MILP_MPC_EPSILON_Z4_S": 90.0, "MILP_MPC_Z4_BASELINE": 380.0,
        "MILP_MPC_ACTION_S": 10.0}},
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
# ── CARRY-OVER sentinel ───────────────────────────────────────────────────
# When the SimulationStats singleton is not reset per run (stale engine / no
# Aimsun restart), EVERY count accumulates across runs: N_BusTrips explodes
# into the tens of thousands while N_DistinctBuses SATURATES at the model's
# total (~320 KG). The corridor-agnostic signature is the ratio: real runs do
# ~5-10 bus trips per distinct bus (KG 500/56~9, Logan 1600/292~5.5); a
# carried-over run does 100s (KG corruption seen at 94122/320 = 294). Flagging
# on the RATIO avoids corridor-specific absolute thresholds. See the memory
# note stats-cross-arm-carryover.
SANITY_MAX_TRIPS_PER_BUS = 30.0


def _check_september_gate(name, m, log):
    """Reproduce the 14 Sep champion numbers on GATE_SEED, or declare the batch void.

    The top-up seeds are only meaningful if the harness still reproduces the
    September champion.  September's runs were frozen-policy (identical repeats),
    so this gate also proves BXT_FREEZE_ON_EVAL actually took effect.  A FAIL
    means the engine or the controller config has drifted since 14 Sep and every
    new-seed number in this batch must be discarded.

    Bus count is the strongest single check: it is what the broken .ang breaks
    first (516 buses expected; a model whose bus type cannot be resolved injects
    514 regardless of any demand scalar), so it catches the Phase-2 model defect
    as well as a config regression.
    """
    def g(*keys):
        for k in keys:
            v = _fnum(m, k)
            if v is not None:
                return v
        return None

    trips = g('stats_N_BusTrips', 'N_BusTrips')
    ext = g('stats_TSP_Extensions', 'TSP_Extensions')
    er = g('stats_TSP_EarlyRed', 'TSP_EarlyRed')
    busdelay = g('stats_AvgBusPassDelay_s', 'AvgBusPassDelay_s')

    interven = None
    if ext is not None and er is not None:
        interven = ext + er

    log(f"  [GATE] {name} seed={GATE_SEED}: buses={trips} interventions={interven} "
        f"bus_delay={busdelay}")

    fails = []
    if trips is None:
        fails.append("bus count missing (cannot verify the model/probe)")
    elif abs(trips - GATE_EXPECT_BUSES) > 0.5 * GATE_EXPECT_BUSES:
        fails.append(f"bus count {trips:.0f} != September {GATE_EXPECT_BUSES} "
                     f"({trips / GATE_EXPECT_BUSES:.2f}x) -- check the .ang bus-type "
                     f"object registration before trusting any seed")
    if interven is not None and abs(interven - GATE_EXPECT_INTERVENTIONS) > 0.5 * GATE_EXPECT_INTERVENTIONS:
        fails.append(f"interventions {interven:.0f} != September "
                     f"{GATE_EXPECT_INTERVENTIONS} -- action path changed")
    if busdelay is not None and abs(busdelay - GATE_EXPECT_S_PER_PAX) > 0.5 * GATE_EXPECT_S_PER_PAX:
        fails.append(f"bus delay {busdelay:.2f} s/pax != September "
                     f"{GATE_EXPECT_S_PER_PAX:.2f} -- reward/plumbing drifted")

    if fails:
        for f_ in fails:
            log(f"  [GATE] FAIL -- {f_}")
        log("  [GATE] BATCH VOID: do not report the top-up seeds until the "
            "seed-300 run matches 14 Sep.")
    else:
        log("  [GATE] PASS -- reproduces 14 Sep; top-up seeds are valid.")
    return not fails


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
    # ── CARRY-OVER sentinel: trips-per-distinct-bus ratio ──────────────────
    # Real ~5-10 (KG baseline ~56 buses / ~500 trips); a carried-over run does
    # 100s because N_BusTrips accumulates while N_DistinctBuses saturates at the
    # model total. Prefixed "CARRY-OVER" so the [SANITY] gate can ABORT (the
    # whole session is corrupted -- no point running more).
    ntrips = _fnum(m, 'stats_N_BusTrips')
    if (ntrips is not None and nbuses is not None and nbuses > 0
            and ntrips / nbuses > SANITY_MAX_TRIPS_PER_BUS):
        problems.append(
            f"CARRY-OVER: N_BusTrips/N_DistinctBuses={ntrips / nbuses:.0f} "
            f"(>{SANITY_MAX_TRIPS_PER_BUS:.0f}; real ~5-10) -- stats did NOT reset "
            f"between runs (N_BusTrips={ntrips:.0f}, N_DistinctBuses={nbuses:.0f} "
            f"saturated vs ~56 baseline). FULLY restart Aimsun so the bundle engine "
            f"reloads -- confirm ENGINE_BUILD on the [LOAD] line -- before trusting ANY row.")
    return problems


_SIG_KEYS = ('stats_Objective_PaxPerDelayHr', 'stats_N_DistinctCars',
             'stats_N_DistinctBuses', 'stats_CarPaxEquivPassages',
             'stats_AvgCarPassDelay_s')


def _run_signature(m):
    """Rounded fingerprint of a run's headline KPIs (None if unusable)."""
    vals = tuple(round(_fnum(m, k) or 0.0, 3) for k in _SIG_KEYS)
    return vals if any(vals) else None


# ── Mode-dispatch guard ───────────────────────────────────────────────────────
# Maps each arm NAME to the ACTIVE_TSP_MODE token the engine must report if the
# arm's specialised decider actually ran. NO_TSP / analytic-baseline arms run the
# generic path by design and are exempt (None). If a named strategy silently
# falls through to GENERIC (mode flag never propagated, or no decider exists —
# e.g. CENTRALIZED), the run is FLAGGED so it can never masquerade as a strategy.
# Arms parked OUT of the campaign (execution + ranking + champion pick).
# MILP_MPC: its solver backend (OR-Tools, else HiGHS-via-scipy) imports fine
# in CONSOLE Python so the old backend gate passed, but inside Aimsun's
# embedded interpreter the import dies with [WinError 127] every replication
# (proven 2026-09-09: 10+ [MILP_MPC] FATALs, rows bit-identical to NO_TSP per
# seed). Revisit iff the Aimsun-visible interpreter gains a working scipy.
PARKED_ARMS = {"MILP_MPC"}


_EXPECTED_ACTIVE_MODE = {
    "NO_TSP": None,
    "CELLQLEARN": "BXT", "CELLQLEARN_SAFE": "BXT", "CELLQLEARN_FORCED": "BXT",
    "CELLQLEARN_DP": "CELLQLEARN_DP",
    "DCTSP_ZIG": "ZIG", "DCTSP_MP_ECTM": "MP_ECTM",
    "DCTSP_BARGAIN_SPM": "BARGAIN", "NASH_GATE": "NASH_GATE",
    "NASH_BARGAIN": "NASH_BARGAIN",
    "MILP_TSP": "MILP_TSP", "DCTSP_MARL_RL": "CPDQL",
    "CENTRALISED": "CENTRALIZED",
    # MARL-family arms run CONTROL_MODE=DRL_DENSITY with per-arm run_config
    # overlays (GLOBAL_REWARD_MODE, MEASURED_*_FEED, CPDQL_MODE). The engine
    # reports ACTIVE_TSP_MODE=GENERIC for all of them, so verify the control
    # mode from the run summary instead -- this is the tripwire that catches
    # a stuck mode dispatcher (proven 2026-09-09: 95 rows silently NORMAL).
    # NOTE: DCTSP_MARL itself was historically unchecked (None); it is checked
    # from here on. Rows written before this fix cannot be re-verified.
    "DCTSP_MARL": "@DRL_DENSITY",
    "DCTSP_MARL_MEAS": "@DRL_DENSITY",
    "DCTSP_MARL_MEAS_Q": "@DRL_DENSITY",
    "DCTSP_MARL_RL_MEAS": "@DRL_DENSITY",
    "MAXPRESSURE_FIX": "MAXPRESSURE_FIX", "MAXPRESSURE_FLEX": "MAXPRESSURE_FLEX",
    # MP-TSP-LB rides the FLEX decider (+ lane-blockage + corridor coordination),
    # so the engine reports ACTIVE_TSP_MODE=MAXPRESSURE_FLEX for it.
    "MAXPRESSURE_LB": "MAXPRESSURE_FLEX",
    # '@X' = a whole CONTROL_MODE arm (not a _spm decider flag): the engine
    # reports ACTIVE_TSP_MODE=GENERIC, so verify CONTROL_MODE==X from the summary.
    "MILP_MPC": "@MILP_MPC",
}


_ORTOOLS_OK = None
def _ortools_available():
    """True if OR-Tools CP-SAT is importable in THIS (Aimsun) Python. Cached.
    Kept for diagnostics; the MILP_MPC gate uses _milp_backend() below."""
    global _ORTOOLS_OK
    if _ORTOOLS_OK is None:
        try:
            from ortools.sat.python import cp_model  # noqa: F401
            _ORTOOLS_OK = True
        except Exception as _e:
            _ORTOOLS_OK = False
            try:
                _br.log(f"[PREFLIGHT] OR-Tools not importable: {_e!r}")
            except Exception:
                pass
    return _ORTOOLS_OK


_MILP_BACKEND = None
_MILP_WARMED = [False]
def _milp_backend():
    """Solver backend for MILP_MPC in THIS (Aimsun) Python. Cached.

    'ortools' when CP-SAT imports (exact); else 'highs' via scipy, which is
    in-process safe -- OR-Tools' bundled abseil/protobuf DLLs collide with
    Aimsun's own and fail with WinError 127 inside the Aimsun process, while
    HiGHS is statically linked. None when neither works: the arm is skipped
    (without a backend the engine tick FATALs and would abort the pipeline).

    HONESTY (2026-09-11): the old gate checked IMPORTS only, which pass on
    Aimsun's console/main thread but die with [WinError 127] when scipy's
    native HiGHS extension first loads on the SIMULATION thread in-sim
    (proven 2026-09-09: gate passed, 10+ in-sim FATALs, NO_TSP-clone rows).
    The gate now SOLVES a trivial 1-variable MILP on THIS (main) thread,
    forcing native init here: a pass means the sim thread inherits loaded
    libraries; a fail skips the arm cleanly with zero wasted simulations.
    """
    global _MILP_BACKEND
    if _MILP_BACKEND is None:
        if _ortools_available():
            _MILP_BACKEND = "ortools"
        else:
            _err = _warmup_highs()
            if _err is None:
                _MILP_BACKEND = "highs"
                try:
                    _br.log("[PREFLIGHT] OR-Tools missing; MILP_MPC will run "
                            "on HiGHS (scipy) backend (trivial solve OK)")
                except Exception:
                    pass
            else:
                _MILP_BACKEND = None
                try:
                    _br.log(f"[PREFLIGHT] No MILP backend usable: {_err!r}")
                except Exception:
                    pass
    return _MILP_BACKEND


def _warmup_highs():
    """Force scipy native init on THIS thread + solve trivially. Returns None
    on success, else the error repr. Cached: native libs stay loaded for the
    whole Aimsun session once initialised here."""
    if _MILP_WARMED[0]:
        return None
    try:
        import os as _os
        try:
            import scipy as _sc
            _sdir = _os.path.dirname(_sc.__file__)
            for _sub in ("libs", ".libs"):
                _ld = _os.path.join(_sdir, _sub)
                if _os.path.isdir(_ld):
                    try:
                        _os.add_dll_directory(_ld)
                    except Exception:
                        pass
        except Exception:
            pass
        import numpy as _np
        from scipy.optimize import milp as _milp_fn
        from scipy.optimize import LinearConstraint as _LC
        from scipy.optimize import Bounds as _BD
        _res = _milp_fn(_np.zeros(1), constraints=_LC(_np.ones((1, 1)), lb=1.0, ub=1.0),
                        bounds=_BD(lb=0.0, ub=2.0), integrality=_np.ones(1))
        if not bool(getattr(_res, "success", False)):
            return f"trivial solve failed: {getattr(_res, 'message', _res)!r}"
        _MILP_WARMED[0] = True
        return None
    except Exception as _e:
        return repr(_e)


def _read_active_mode(m):
    """Read ACTIVE_TSP_MODE from the newest tsp_run_summary_*.txt in the run's
    logs dir. Returns the token string, or None if it can't be determined."""
    folder = (m or {}).get('stats_results_folder') if m else None
    if not folder:
        return None
    # results/<run>/ ; logs live at <corridor>/logs/
    _corr = _os.path.dirname(_os.path.dirname(_os.path.abspath(folder)))
    _logs = _os.path.join(_corr, 'logs')
    try:
        cands = _glob.glob(_os.path.join(_logs, 'tsp_run_summary_*.txt'))
        if not cands:
            return None
        newest = max(cands, key=_os.path.getmtime)
        with open(newest, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('ACTIVE_TSP_MODE:'):
                    return line.split(':', 1)[1].strip()
    except Exception:
        return None
    return None


def _read_control_mode(m):
    """Read CONTROL_MODE from the newest tsp_run_summary_*.txt (same location as
    ACTIVE_TSP_MODE). Returns the token string, or None if not determinable."""
    folder = (m or {}).get('stats_results_folder') if m else None
    if not folder:
        return None
    _corr = _os.path.dirname(_os.path.dirname(_os.path.abspath(folder)))
    _logs = _os.path.join(_corr, 'logs')
    try:
        cands = _glob.glob(_os.path.join(_logs, 'tsp_run_summary_*.txt'))
        if not cands:
            return None
        newest = max(cands, key=_os.path.getmtime)
        with open(newest, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('CONTROL_MODE:'):
                    return line.split(':', 1)[1].strip()
    except Exception:
        return None
    return None


def _mode_dispatch_problem(name, m):
    """Return a problem string if the arm's declared mode did not actually run,
    or None if healthy / not checkable."""
    expected = _EXPECTED_ACTIVE_MODE.get(name, '__unknown__')
    if expected is None:
        return None                      # generic-by-design arm
    if expected == '__unknown__':
        return None                      # arm not in the map -- don't guess
    # '@X' arms are whole CONTROL_MODE controllers (e.g. MILP_MPC), not _spm
    # decider flags -- verify CONTROL_MODE instead of ACTIVE_TSP_MODE.
    if isinstance(expected, str) and expected.startswith('@'):
        want_cm = expected[1:]
        actual_cm = _read_control_mode(m)
        if actual_cm is None:
            return None                  # summary unreadable -- don't false-alarm
        if actual_cm != want_cm:
            return (f"CONTROL MODE: arm '{name}' declared CONTROL_MODE={want_cm} "
                    f"but the engine ran CONTROL_MODE={actual_cm} -- this arm did "
                    f"NOT run its controller; results are NOT valid for '{name}'.")
        return None
    actual = _read_active_mode(m)
    if actual is None:
        return None                      # run summary unreadable -- don't false-alarm
    if actual != expected:
        return (f"MODE DISPATCH: arm '{name}' declared mode {expected} but the "
                f"engine ran ACTIVE_TSP_MODE={actual} -- this arm did NOT run its "
                f"strategy (it fell through to the generic path); results are "
                f"NOT valid for '{name}'.")
    return None


def _run_and_collect(_br, rep, name, strategy, seed, scalar, coordinated, coord_algo,
                     global_reward, reward_cfg, bus_pred, CONTROLLER_PATH,
                     RUN_CONFIG_PATH, PROJECT_DIR, RESULTS_CSV, log,
                     max_reruns=0, recollect_waits=(4, 8, 12, 16),
                     active_intersections=None):
    """Run one replication and collect its metrics, hardened against the
    intermittent stats-collection race that silently blanked BARGAIN 400/700 on
    KG: if the objective comes back blank, WAIT and re-collect (the sim's
    post-processing may still be writing simulation_results.csv); only if that
    still fails do we re-run the whole replication (up to max_reruns)."""
    attempt = 0
    while True:
        _br.set_seed(rep, seed)
        _run_reward_cfg = dict(reward_cfg or {})
        _run_reward_cfg.setdefault("BUS_FREQ_INJECT_SCALAR",
                                   BUS_FREQ_INJECT_SCALAR)
        if GLOBAL_MEASURED_FEED:
            # All arms decide on the measured flow + queue feed (not LWR estimate).
            _run_reward_cfg.setdefault("MEASURED_STATE_FEED", True)
            _run_reward_cfg.setdefault("MEASURED_QUEUE_FEED", True)
        if SMOKE_HEURISTIC_PRIOR and bool(_run_reward_cfg.get("BXT_MODE", False)):
            # SMOKE only: give the UNTRAINED BXT learner a traditional-TSP prior so
            # it acts instead of argmaxing NO_ACTION on an empty Q-table (which is
            # byte-identical to NO_TSP). setdefault so an arm can still override.
            _run_reward_cfg.setdefault("BXT_INS_OPTIMISTIC_INIT",
                                       SMOKE_HEURISTIC_PRIOR_INIT)
        if (SMOKE_HEURISTIC_PRIOR or EVAL_DIAGNOSTICS) \
                and bool(_run_reward_cfg.get("BXT_MODE", False)):
            # Emit the predicted-vs-realized [BXT_EVAL] diagnostic (policy stays
            # frozen in eval; only logs). Smoke sets it automatically; a full run
            # gets it via env BXT_EVAL_DIAG=1. Parse with analyze_bxt_predictions.py.
            _run_reward_cfg.setdefault("BXT_EVAL_DIAGNOSTICS", True)
        if GLOBAL_MEASURED_SIDE_COST:
            # Every arm prices the cross cost from MEASURED cross congestion so a
            # jammed cross approach is never under-priced (seed-lottery fix).
            _run_reward_cfg.setdefault("MEASURED_SIDE_COST", True)
            # Diagnostic: log [MEAS_SIDE] per junction so we can SEE whether the
            # measured cross cost engages (and if not, why: NO_MEAS/STALE).
            _run_reward_cfg.setdefault("MEASURED_SIDE_COST_DIAG", True)
        if GLOBAL_CASCADE_COST and strategy != "NORMAL":
            # The real seed-lottery lever: the DOWNSTREAM multi-hop cascade cost
            # (projected-saturation) -- gridlock forms 2-3 junctions down, not on
            # the immediate cross approach. Price it into every TSP arm's cross
            # cost / gate (only CELLQLEARN_GATED+NASH had it before).
            _run_reward_cfg.setdefault("CASCADE_COST_MODE", True)
        _br.write_run_config(name, strategy, seed, scalar, coordinated, coord_algo,
                             RUN_CONFIG_PATH, global_reward_mode=global_reward,
                             reward_cfg=_run_reward_cfg, bus_predictor=bus_pred,
                             results_csv_name=_os.path.basename(RESULTS_CSV),
                             active_intersections=active_intersections)
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


def main(arms=None, results_csv=None, resume=False):
    """Run the champion search. Pass `arms` (a subset of ARMS) and `results_csv`
    to run a subset (see champion_subset.py); defaults to the full 11-arm search.
    resume=True keeps an existing results CSV and skips (experiment, seed,
    demand) combos already present with success -- use after an interrupted
    batch instead of redoing completed runs. Only successful rows are skipped;
    failed rows re-run."""
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

    # fresh results file (unless resuming an interrupted batch)
    _done_keys = set()
    if resume and _os.path.isfile(RESULTS_CSV_):
        try:
            import csv as _csv
            with open(RESULTS_CSV_, newline='', encoding='utf-8-sig') as _fh:
                for _r in _csv.DictReader(_fh):
                    if str(_r.get("run_success", "")).strip().lower() in (
                            "true", "1", "yes"):
                        _done_keys.add((str(_r.get("run_experiment", "")),
                                        str(_r.get("run_seed", "")).split(".")[0],
                                        str(_r.get("run_demand_scalar", ""))))
            log(f"RESUME: {len(_done_keys)} successful runs already in "
                f"{RESULTS_CSV_} -- skipping those")
        except Exception as _e:
            log(f"RESUME: could not read {RESULTS_CSV_} ({_e}); starting fresh")
            _done_keys = set()
    else:
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
                _br.set_demand_scalar(scalar, base_demands, rep=rep)
            except Exception as e:
                log(f"WARN demand scalar {scalar}: {e}")

            for arm in arms:
                name = arm["name"]; strategy = arm["strategy"]
                # Parked arms (PARKED_ARMS): known-broken in the live Aimsun
                # env -- skip execution AND ranking so no more dead rows accrue.
                if name in PARKED_ARMS:
                    log(f"SKIP {name}: parked (see PARKED_ARMS) -- no runs, "
                        f"no ranking.")
                    continue
                # MILP_MPC needs a solver backend in Aimsun's Python (OR-Tools
                # CP-SAT, else HiGHS via scipy -- OR-Tools cannot load
                # in-process: DLL collision with Aimsun's own). Without one
                # the engine tick FATALs and would abort the ENTIRE pipeline.
                # Skip the arm (logged) so every other arm still runs.
                if strategy == "MILP_MPC" and _milp_backend() is None:
                    log(f"SKIP {name}: no MILP backend importable in this Aimsun "
                        f"Python (need ortools or scipy>=1.9); skipping it "
                        f"so the rest of the champion search still completes.")
                    continue
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
                # later run; this makes dispatch order-independent and rules out
                # the "all arms identical" failure mode.
                try:
                    _br.set_reward_weights(
                        CONTROLLER_PATH,
                        (_numeric or None) if not is_baseline else None)
                except Exception as e:
                    log(f"WARN reward patch {name}: {e}")

                # ── FAIR TRAINING: learners train-then-freeze; others per_seed ──
                is_learner = name in LEARNING_ARMS
                if is_learner:
                    seeds_to_run = list(TRAIN_SEEDS) + list(SCORED_SEEDS)
                    _set_controller_bxt_seeds(CONTROLLER_PATH, TRAIN_SEEDS, SCORED_SEEDS,
                                              BXT_TRAIN_EPSILON,
                                              freeze_on_eval=LEARNERS_FREEZE_ON_EVAL)
                else:
                    seeds_to_run = list(SCORED_SEEDS)
                    _set_controller_bxt_seeds(CONTROLLER_PATH, [], [], BXT_TRAIN_EPSILON)

                # Multi-regime training (task a): demand levels to cycle over the
                # learner's TRAIN seeds. Empty -> classic single-demand training.
                _mr_demands = (list(BXT_TRAIN_DEMAND_SCALARS)
                               if (is_learner and BXT_TRAIN_DEMAND_SCALARS) else [])
                _train_i = 0
                for seed in seeds_to_run:
                    run_num += 1
                    _is_train = (is_learner and seed in TRAIN_SEEDS)
                    _phase = "train" if _is_train else "eval"
                    # Set the demand level for THIS run: a cycled train regime, or
                    # the base scalar (eval, and non-multiregime train).
                    _run_scalar = scalar
                    if _mr_demands:
                        if _is_train:
                            _run_scalar = float(_mr_demands[_train_i % len(_mr_demands)])
                            _train_i += 1
                    # Resume: skip combos already banked as successful.
                    if (name, str(seed), str(_run_scalar)) in _done_keys or \
                            (name, str(seed), str(float(_run_scalar))) in _done_keys:
                        log(f"[{run_num}/{n_total}] {CORRIDOR} | {name} | seed={seed} | "
                            f"{_phase} -- SKIP (done)")
                        continue
                    if _mr_demands:
                        try:
                            _br.set_demand_scalar(_run_scalar, base_demands, rep=rep)
                        except Exception as e:
                            log(f"  WARN demand x{_run_scalar:g}: {e}")
                    _reg = f" | demand x{_run_scalar:g}" if _mr_demands else ""
                    log(f"[{run_num}/{n_total}] {CORRIDOR} | {name} | seed={seed} | {_phase}{_reg}")
                    # collection-race retry: re-collect (short wait) then re-run once
                    m = _run_and_collect(_br, rep, name, strategy, seed, _run_scalar,
                                         coordinated, coord_algo, _global_reward,
                                         (None if is_baseline and not _numeric else (_numeric or None)),
                                         bus_pred, CONTROLLER_PATH, RUN_CONFIG_PATH,
                                         PROJECT_DIR, RESULTS_CSV_, log,
                                         active_intersections=arm.get("active_intersections"))
                    if m is not None:
                        _br.append_master_csv(RESULTS_CSV_, m)
                        if (USE_TOPUP_SEEDS and is_learner
                                and seed == GATE_SEED):
                            _check_september_gate(name, m, log)
                        # ── [SANITY] live health gate ──────────────────────
                        _problems = _kpi_sanity(m)
                        # Mode-dispatch guard: did THIS arm's decider actually run?
                        _mode_prob = _mode_dispatch_problem(name, m)
                        if _mode_prob:
                            _problems = list(_problems) + [_mode_prob]
                        for _p in _problems:
                            log(f"  [SANITY] WARNING: {_p}")
                        # CARRY-OVER is FATAL: the stats singleton never reset,
                        # so this row AND every later one is corrupted. Abort the
                        # whole sweep loudly rather than write a poisoned CSV that
                        # looks plausible (as champion_kg.csv did -- 58 columns
                        # accumulated, champion undeterminable even after the fact).
                        _carry = [p for p in _problems if p.startswith("CARRY-OVER")]
                        if _carry:
                            raise RuntimeError(
                                "ABORTING sweep at run "
                                f"{run_num}/{n_total} -- stats CARRY-OVER: {_carry[0]}")
                        _sig = _run_signature(m)
                        if _sig is not None and _sig == _last_sig:
                            log("  [SANITY] WARNING: headline KPIs byte-identical to the "
                                "previous run -- suspect a no-op controller patch, a "
                                "stale module that never reloaded, or an arm that fell "
                                "through to the generic path (see MODE DISPATCH above)")
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
    _argv0 = (_sys.argv[0] if getattr(_sys, "argv", None) else "")
    if "champion_search" not in _argv0:
        # Loaded in the Aimsun console (import/paste: no argv available) --
        # do NOT auto-run; call main() explicitly instead.
        print("champion_search loaded in-console; run "
              "cs.main(resume=True) to resume (no flags available here).")
    else:
        main(resume=("--resume" in _sys.argv))
