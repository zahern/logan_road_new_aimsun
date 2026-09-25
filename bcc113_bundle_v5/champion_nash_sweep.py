"""
champion_nash_sweep.py -- Quick sweep with Nash equilibrium model, 
forced CELLQLEARN/BARGAIN actions, hybrid ARM, and MILP-based TSP.
"""

import os as _os
import sys as _sys
import importlib.util as _ilu

# Aimsun may execute this file with a working directory outside the bundle, or
# may expose its own installation path as __file__. Resolve the bundle from the
# active model directory when the adjacent file is not found.
def _find_bundle_dir():
    _candidates = []
    try:
        _candidates.append(_os.path.dirname(_os.path.abspath(__file__)))
    except (NameError, TypeError):
        pass
    if not _candidates or not _os.path.isfile(
            _os.path.join(_candidates[0], "champion_search.py")):
        try:
            from PyANGKernel import GKSystem
            _model_dir = GKSystem.getSystem().getActiveModel().getDocumentDirectory().absolutePath()
            _candidates.extend((
                _model_dir,
                _os.path.dirname(_model_dir),
                _os.path.dirname(_os.path.dirname(_model_dir)),
            ))
        except Exception:
            pass
    for _candidate in _candidates:
        _candidate = _os.path.abspath(_candidate)
        if _os.path.isfile(_os.path.join(_candidate, "champion_search.py")):
            return _candidate
    raise RuntimeError(
        "champion_nash_sweep.py: cannot find champion_search.py; "
        f"searched {_candidates!r}.")


_HERE = _find_bundle_dir()
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
_cs_path = _os.path.join(_HERE, "champion_search.py")
_spec_cs = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec_cs)
_sys.modules["champion_search"] = _cs
_spec_cs.loader.exec_module(_cs)

# ── quick-mode overrides ──────────────────────────────────────────────────────
_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []

# ── Logan-specific ARM overrides for aggressive action ────────────────────────

# Force CELLQLEARN to act: lower min_gain, lower veto, enable all actions
_cellqlearn_overrides = {
    "CELLQLEARN_MIN_GAIN_S": 2.0,        # Was 15.0 - much lower threshold
    "DECIDER_COST_VETO_RATIO": 0.8,      # Was 1.5 - less conservative
    "BXT_EPSILON": 0.1,                  # More exploration
    "BXT_ALPHA": 0.3,                    # Higher learning rate
    "BUS_PAX_WEIGHT": 2.0,               # Higher bus priority
}

# Force BARGAIN to act: lower gates, lower min_gain
_bargain_overrides = {
    "BG_MIN_BUS_DELAY_S": 2.0,           # Was 15.0
    "BG_MIN_GAIN_S": 2.0,                # Was 12.0
    "BG_BUS_W_IMM": 3.0,                 # Was 1.25 - much higher bus weight
    "BG_BUS_W_NEAR": 2.5,
    "BG_BUS_W_FAR": 1.5,
    "DCTSP_CONGESTION_GATE_FRACTION": 0.9,  # Was 0.6 - much more permissive
    "DCTSP_CONGESTION_GATE": True,
    "DECIDER_COST_VETO_RATIO": 1.0,
}

# ── MILP-based ARM ────────────────────────────────────────────────────────────
# MILP-based TSP controller: solves mixed-integer linear program for optimal
# signal timing with bus priority. Uses scipy.optimize for MILP solving.
_milp_arm = {
    "name": "MILP_TSP",
    "strategy": "GLOBAL_REWARD",
    "method": "MILP_TSP",
    "coordinated": True,
    "coordination_algo": "KALMAN",
    "reward_overrides": {
        "GLOBAL_REWARD_MODE": True,
        "MILP_TSP_MODE": True,
        "MILP_TIME_LIMIT_S": 0.1,        # Solve time limit per decision
        "MILP_HORIZON_CYCLES": 2,        # Optimization horizon in cycles
        "MILP_BUS_WEIGHT": 1.0,          # Bus priority weight in objective
        "MILP_CROSS_WEIGHT": 2.0,        # Cross-street penalty weight
        "MILP_MIN_GREEN_S": 5.0,         # Minimum green per phase
        "MILP_MAX_GREEN_S": 60.0,        # Maximum green per phase
        "MILP_CYCLE_S": 135.0,           # Fixed cycle length
        "DECIDER_COST_VETO_RATIO": 1.0,
    }
}

# ── Nash Equilibrium ARM (NashGate) ──────────────────────────────────────────
# Implements a simple Nash equilibrium gate: each intersection computes its
# best response given neighbors' strategies, converges to equilibrium.
_nash_arm = {
    "name": "NASH_GATE",
    "strategy": "GLOBAL_REWARD",
    "method": "NASH_GATE",
    "coordinated": True,
    "coordination_algo": "NASH",  # Custom Nash coordination
    "reward_overrides": {
        "GLOBAL_REWARD_MODE": True,
        "NASH_GATE_MODE": True,
        "NASH_CONVERGENCE_TOL": 0.01,
        "NASH_MAX_ITER": 10,
        "NASH_NEIGHBOR_WEIGHT": 0.5,
        "NASH_BUS_WEIGHT": 2.0,
        "NASH_CROSS_WEIGHT": 0.5,
        "DECIDER_COST_VETO_RATIO": 1.0,
    }
}

# ── SUBSET for sweep ──────────────────────────────────────────────────────────
SUBSET = [
    "NO_TSP",
    "CELLQLEARN",
    "CELLQLEARN_SAFE", 
    "DCTSP_ZIG",
    "DCTSP_MP_ECTM",
    "DCTSP_BARGAIN_SPM",
    "DCTSP_MARL",
    "CENTRALISED",
    "MAXPRESSURE_FIX",
    "DCTSP_HYBRID_MP",
]

# Add our custom arms
_custom_arms = [
    # CELLQLEARN with forced action
    {
        "name": "CELLQLEARN_FORCED",
        "strategy": "GLOBAL_REWARD",
        "method": "CELLQLEARN",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "reward_overrides": {
            **_cellqlearn_overrides,
            "GLOBAL_REWARD_MODE": True, "BXT_MODE": True,
            "MP_ECTM_MODE": False, "DCTSP_ZIG_MODE": False, "BARGAIN_SPM_MODE": False,
            "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
            "BXT_DT_S": 1.0, "BXT_GAMMA": 0.01,
            "BXT_CAR_OCC": 1.2, "BXT_BALANCE_FACTOR": 1.1,
            "DECIDER_COST_VETO_RATIO": 0.8,
            "BUS_PAX_WEIGHT": 2.0, "GREEN_KEEP_CREDIT_S": 3.0,
            "MULTIBUS_MAX_FACTOR": 1.0,
            "CORRIDOR_REWARD_NEIGHBOR_W": 0.5,
            "CELLQLEARN_MIN_GAIN_S": 2.0,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1}},
    # BARGAIN with forced action
    {
        "name": "DCTSP_BARGAIN_FORCED",
        "strategy": "GLOBAL_REWARD",
        "method": "DCTSP_BARGAIN_SPM",
        "coordinated": True,
        "coordination_algo": "SHOCKWAVE",
        "reward_overrides": {
            **_bargain_overrides,
            "GLOBAL_REWARD_MODE": True, "BARGAIN_SPM_MODE": True,
            "DCTSP_ZIG_MODE": False, "MP_ECTM_MODE": False, "BXT_MODE": False,
            "CENTRALIZED_MODE": False, "CELLQLEARN_DP_MODE": False,
            "DCTSP_GREEN_REALLOC_MODE": True, "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
            "BG_CASCADE_MULT": 2.0,
            "TSP_CYCLE_LENGTH_OVERRIDE_S": 135.0, "PHASE_SEQ_MAX_PER_CYCLE": 1}},
    # Nash Gate arm
    _nash_arm,
    # MILP TSP arm
    _milp_arm,
]

# Build arms list with MILP first so its log and result are available before
# the remaining comparison arms run.
_arms = [_milp_arm]
_arms.extend(arm for arm in _cs.ARMS if arm["name"] in SUBSET)
_arms.extend(arm for arm in _custom_arms if arm["name"] != _milp_arm["name"])

_results_csv = _os.path.join(_cs._ROOT, f"champion_nash_sweep_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"NASH SWEEP -- corridor={_cs.CORRIDOR} "
         f"| {len(_arms)} arms x seed 300 | Nash + forced actions + MILP")
    _log("=" * 70)
    _cs.main(arms=_arms, results_csv=_results_csv)