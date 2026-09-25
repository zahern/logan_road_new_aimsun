"""
champion_milp_quick.py -- Quick sweep: NO_TSP vs MILP_TSP only (~5 min).
"""

import os as _os
import champion_search as _cs

# ── quick-mode overrides ──────────────────────────────────────────────────────
_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []

# Only NO_TSP and MILP_TSP
SUBSET = ["NO_TSP", "MILP_TSP"]

_arms = [a for a in _cs.ARMS if a["name"] in SUBSET]

_results_csv = _os.path.join(_cs._ROOT, f"champion_milp_quick_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"MILP QUICK SWEEP -- corridor={_cs.CORRIDOR} "
         f"| 2 arms x seed 300 | NO_TSP vs MILP_TSP")
    _log("=" * 70)
    _cs.main(arms=_arms, results_csv=_results_csv)