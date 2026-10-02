"""
champion_cellq_fix.py -- focused champion search to test the BXT_EPSILON fix.

WHY: the four CELLQ_LEARN_* arms were configured with BXT_EPSILON=0.10 (10%
random actions at deploy time) while CELLQLEARN -- the best performer -- used
0.02. Action counts tracked epsilon exactly:

    arm                    BXT_EPSILON   actions   mean obj
    CELLQLEARN                0.02         1-3      209.96
    DCTSP_MP_ECTM             (none)        6-9      212.06
    CELLQ_LEARN_UNCOORD       0.10        23-38     169.66

champion_search.py was edited to set those four arms to 0.02. This script
re-runs ONLY those four, plus NO_TSP (baseline) and DCTSP_MP_ECTM (the
incumbent champion), on the SAME top-up seeds, writing to a SEPARATE csv so
champion_kg.csv and the full 19-arm matrix are untouched.

WHAT TO READ FIRST: the TSP action counters, not the objective.
    stats_TSP_Extensions + stats_TSP_Insertions + stats_TSP_GreenRealloc +
    stats_TSP_EarlyRed + stats_TSP_OffsetCorr + stats_TSP_PhaseSkip +
    stats_TSP_PhaseRot
If those drop from ~30 to ~3, the epsilon diagnosis was right. If they stay
at ~30, BXT_EPSILON is NOT the deploy-time epsilon and the edit must be undone.

RUN inside Aimsun, corridor model open:
      champion_cellq_fix.py
-> champion_cellqfix_<corridor>.csv
"""

import os as _os
import sys as _sys_cb
import importlib.util as _ilu

# ── Robustly load champion_search by ABSOLUTE PATH ───────────────────────────
# A plain `import champion_search` fails when Aimsun runs this file from a
# working directory where the bundle root is not on sys.path -- the script then
# dies with "No module named 'champion_search'" before any run happens.
#
# Worse: Aimsun may execute this file with __file__ pointing at its OWN
# INSTALLATION directory (observed: "C:\Program Files\Aimsun\Aimsun Next 26.0.0"),
# so trusting __file__ alone is not enough. Resolve the bundle from the ACTIVE
# MODEL's document directory when the adjacent file is not found -- the same
# multi-candidate resolver champion_milp_pair_quick.py uses.
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
            _model_dir = (GKSystem.getSystem().getActiveModel()
                          .getDocumentDirectory().absolutePath())
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
        "champion_cellq_fix.py: cannot find champion_search.py; "
        f"searched {_candidates!r}. Unzip the bundle so both files sit in the "
        "same folder, then run this from Aimsun with the model open.")


_HERE = _find_bundle_dir()
if _HERE not in _sys_cb.path:
    _sys_cb.path.insert(0, _HERE)

# Cache-buster: Aimsun's persistent interpreter caches champion_search from the
# first champion run this session, so edits never load. Purge the chain so it
# re-reads from disk. (In-sim engine still needs a full Aimsun restart.)
for _mn in ("champion_search", "_br_champ"):
    _sys_cb.modules.pop(_mn, None)

_cs_path = _os.path.join(_HERE, "champion_search.py")
_spec_cs = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec_cs)
_sys_cb.modules["champion_search"] = _cs      # so _br_champ / later imports find it
_spec_cs.loader.exec_module(_cs)

# ── keep the SAME seeds as the 19-arm run so results are comparable ──────────
_cs.EVAL_SEEDS = list(_cs.TOPUP_EVAL_SEEDS)   # [300, 1200, 1300, 1400, 1500, 1600]
_cs.SCORED_SEEDS = list(_cs.TOPUP_EVAL_SEEDS) # what the selector must require
_cs.USE_TOPUP_SEEDS = True
# TRAIN_SEEDS left at the default [800, 900, 1000, 1100] so the learners train
# exactly as they did in the 19-arm run -- only epsilon differs.

SUBSET = [
    "NO_TSP",                 # baseline: must be present for the comparison
    "CELLQ_LEARN_UNCOORD",    # \ the four arms whose epsilon was corrected
    "CELLQ_VDET_ON",          #  | 0.10 -> 0.02
    "CELLQ_BUSSPLIT",         #  |
    "CELLQ_VDET_BUSSPLIT",    # /
    "DCTSP_MP_ECTM",          # incumbent champion (212.06, +2.32% vs NO_TSP)
]

_by_name = {a["name"]: a for a in _cs.ARMS}
_arms = [_by_name[n] for n in SUBSET if n in _by_name]   # SUBSET order is the run order
_missing = sorted(set(SUBSET) - set(_by_name))
_results_csv = _os.path.join(_cs._ROOT,
                             f"champion_cellqfix_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"CELLQ EPSILON-FIX SWEEP -- corridor={_cs.CORRIDOR}")
    _log(f"  {len(_arms)} arms x {len(_cs.EVAL_SEEDS)} eval seeds "
         f"| learners train on {_cs.TRAIN_SEEDS}")
    _log(f"  arms: {[a['name'] for a in _arms]}")
    if _missing:
        _log(f"  WARNING: not found in _cs.ARMS -> {_missing}")
    _log(f"  results -> {_results_csv}")
    _log("  READ THE TSP ACTION COUNTERS FIRST (expect ~3, not ~30).")
    _log("=" * 70)
    _cs.main(arms=_arms, results_csv=_results_csv)
