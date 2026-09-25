"""
champion_milp_quick.py -- Quick sweep: NO_TSP vs MILP_TSP only (~5 min).
"""

import os as _os
import sys as _sys_cb
# Cache-buster: Aimsun's persistent interpreter caches champion_search (and the
# batch_runner it exec-loads) from the first champion run this session, so edits
# never load. Purge the chain so it re-reads from disk each run. (In-sim engine
# still needs a full Aimsun restart. See champion_marl_meas_quick.py.)
for _mn in ("champion_search", "_br_champ"):
    _sys_cb.modules.pop(_mn, None)
import champion_search as _cs

# ── quick-mode overrides ──────────────────────────────────────────────────────
_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []
_cs.BUS_FREQ_INJECT_SCALAR = 1.0

# MILP_TSP is not one of the base champion_search.ARMS (it lives in
# champion_nash_sweep.py's _milp_arm) -- define it here too, else the SUBSET
# filter below silently drops it and only NO_TSP ever runs.
_milp_arm = {
    "name": "MILP_TSP",
    "strategy": "GLOBAL_REWARD",
    "method": "MILP_TSP",
    "coordinated": True,
    "coordination_algo": "KALMAN",
    "reward_overrides": {
        "GLOBAL_REWARD_MODE": True,
        "MILP_TSP_MODE": True,
        "MILP_TIME_LIMIT_S": 0.1,
        "MILP_HORIZON_CYCLES": 2,
        "MILP_BUS_WEIGHT": 1.0,
        "MILP_CROSS_WEIGHT": 2.0,
        "MILP_REQUIRE_MAIN_FLOW": True,
        "MILP_MIN_MAIN_FLOW_VPH": 1.0,
        "MILP_MIN_GREEN_S": 5.0,
        "MILP_MAX_GREEN_S": 60.0,
        "MILP_CYCLE_S": 135.0,
        "DECIDER_COST_VETO_RATIO": 1.0,
    }
}

# Only NO_TSP and MILP_TSP
SUBSET = ["NO_TSP", "MILP_TSP"]

_arms = [a for a in _cs.ARMS if a["name"] in SUBSET]
_arms.append(_milp_arm)

_results_csv = _os.path.join(_cs._ROOT, f"champion_milp_quick_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"MILP QUICK SWEEP -- corridor={_cs.CORRIDOR} "
         f"| calibration + 2 arms x seed 300 | NO_TSP vs MILP_TSP")
    _log("=" * 70)

    # x1.0 records the natural PT entry pattern. The comparison pass then
    # disables injection so it measures schedule deviation at the same demand.
    _calibration_csv = _os.path.join(
        _cs._ROOT, f"champion_milp_quick_calibration_{_cs.CORRIDOR}.csv")
    _cs.BUS_FREQ_INJECT_SCALAR = 1.0
    _cs.main(arms=[a for a in _arms if a["name"] == "NO_TSP"],
             results_csv=_calibration_csv)
    _cs.BUS_FREQ_INJECT_SCALAR = 0.0
    _cs.main(arms=_arms, results_csv=_results_csv)