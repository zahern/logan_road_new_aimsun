"""
champion_quick.py -- ONE-seed sweep across ALL EIGHT arms (~18 min).

Purpose: verify the full mechanism stack actually fires before committing to
a multi-hour Phase-1/2 run:
  * every arm acts (extension/insertion counters > 0 where expected)
  * [SANITY] stays clean, zero duplicate rows
  * indicative ranking vs NO_TSP on a single seed

NOT statistically meaningful (n=1): use rank only as a smoke signal.

RUN inside Aimsun, corridor model open:
      champion_quick.py
-> champion_quick_<corridor>.csv
"""

import os as _os
import champion_search as _cs

# ── quick-mode overrides ──────────────────────────────────────────────────────
_cs.EVAL_SEEDS = [300]     # single eval seed
_cs.TRAIN_SEEDS = []       # learners run per_seed (no training phase)

SUBSET = ["NO_TSP", "CELLQLEARN", "CELLQLEARN_SAFE", "DCTSP_ZIG",
          "DCTSP_MP_ECTM", "DCTSP_BARGAIN_SPM", "DCTSP_MARL", "CENTRALISED",
          "MAXPRESSURE_FIX", "DCTSP_HYBRID_MP", "MILP_TSP"]

_arms = [a for a in _cs.ARMS if a["name"] in SUBSET]
_results_csv = _os.path.join(_cs._ROOT, f"champion_quick_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"QUICK CHAMPION SWEEP -- corridor={_cs.CORRIDOR} "
         f"| 8 arms x seed 300 | smoke test only")
    _log("=" * 70)
    _cs.main(arms=_arms, results_csv=_results_csv)
