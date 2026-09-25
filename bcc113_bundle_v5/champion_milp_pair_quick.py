"""
champion_milp_pair_quick.py -- one-shot comparison of both MILPs and NO_TSP.

Run this from the Aimsun Python console with the Logan Road model open.  It
runs exactly one seed in this order:
    1. MILP_TSP  (SciPy mixed-integer TSP action selector)
    2. MILP_MPC  (OR-Tools CP-SAT rolling-horizon controller)
    3. NO_TSP    (fixed-time baseline)

The output is written to champion_milp_pair_quick_<corridor>.csv.
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
        "champion_milp_pair_quick.py: cannot find champion_search.py; "
        f"searched {_candidates!r}.")


_HERE = _find_bundle_dir()
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
_cs_path = _os.path.join(_HERE, "champion_search.py")
_spec_cs = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec_cs)
_sys.modules["champion_search"] = _cs
_spec_cs.loader.exec_module(_cs)

_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []
_cs.DEMAND_SCALARS = [1.0]
_cs.BUS_FREQ_INJECT_SCALAR = 0.0

# The single-cycle greedy SciPy selector is no longer a base ARM (champion_search
# now ships MILP_MPC, the real horizon controller). Define the greedy arm inline
# here so this head-to-head old-vs-new diagnostic still runs.
_milp_tsp = {
    "name": "MILP_TSP_ONE_SHOT",
    "strategy": "GLOBAL_REWARD",
    "method": "MILP_TSP",
    "coordinated": True,
    "coordination_algo": "KALMAN",
    "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "MILP_TSP_MODE": True,
        "MILP_TIME_LIMIT_S": 0.1, "MILP_HORIZON_CYCLES": 2,
        "MILP_BUS_WEIGHT": 1.0, "MILP_CROSS_WEIGHT": 2.0,
        "MILP_MIN_GREEN_S": 5.0, "MILP_MAX_GREEN_S": 60.0,
        "MILP_CYCLE_S": 135.0, "DECIDER_COST_VETO_RATIO": 1.0,
    },
}

_milp_mpc = {
    "name": "MILP_MPC_ONE_SHOT",
    "strategy": "MILP_MPC",
    "method": "MILP_MPC",
    "coordinated": True,
    "coordination_algo": "KALMAN",
    "reward_overrides": {
        "MILP_MPC_HORIZON_S": 300.0,
        "MILP_MPC_REPLAN_S": 30.0,
        "MILP_MPC_TIME_LIMIT_S": 1.5,
        "MILP_MPC_EPSILON_LATE_S": 60.0,
        "MILP_MPC_EPSILON_Z4_S": 90.0,
        "MILP_MPC_Z4_BASELINE": 380.0,
        "MILP_MPC_ACTION_S": 10.0,
    },
}

_no_tsp = next(
    arm for arm in _cs.ARMS if arm["name"] == "NO_TSP"
)
_no_tsp = dict(_no_tsp)
_no_tsp["name"] = "NO_TSP_ONE_SHOT"

# Keep this list in experiment order. champion_search.main preserves it.
ARMS = [_milp_tsp, _milp_mpc, _no_tsp]
_RESULTS_CSV = _os.path.join(
    _cs._ROOT, f"champion_milp_pair_quick_{_cs.CORRIDOR}.csv"
)


if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(
        f"MILP PAIR ONE-SHOT -- corridor={_cs.CORRIDOR} | seed=300 | "
        "MILP_TSP -> MILP_MPC -> NO_TSP"
    )
    _log(f"Results: {_RESULTS_CSV}")
    _log("=" * 70)
    _cs.main(arms=ARMS, results_csv=_RESULTS_CSV)
