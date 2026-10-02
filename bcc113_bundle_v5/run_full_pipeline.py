"""
run_full_pipeline.py -- ONE launcher that tests ALL algorithms end-to-end on the
open corridor model, against the fixed-time NO_TSP baseline, and writes one CSV.

Runs every arm in champion_search.ARMS (all families):
  NO_TSP, CELLQ_LEARN_UNCOORD, CELLQ_VDET_ON, CELLQ_BUSSPLIT, CELLQ_VDET_BUSSPLIT,
  CELLQLEARN, CELLQLEARN_GATED, CELLQLEARN_FORCED, DCTSP_ZIG, DCTSP_MP_ECTM,
  DCTSP_BARGAIN_SPM, DCTSP_MARL, DCTSP_MARL_RL, CENTRALISED, CELLQLEARN_SAFE,
  NASH_BARGAIN, MAXPRESSURE_FIX, MAXPRESSURE_FLEX, MAXPRESSURE_LB, MILP_MPC
(arms with no solver backend / parked are skipped by champion_search automatically).

HOW TO RUN (inside Aimsun, corridor model open):
    run_full_pipeline.py
-> run_full_pipeline_<corridor>.csv

IF A RUN HANGS "waiting for sim to START" OR you see
"Action execute for object type GKReplication cannot be executed":
    the model has many replications and the auto-pick chose one Aimsun won't run.
    Set the replication you run with Play in the GUI by UNCOMMENTING one line in
    the REPLICATION SELECTION block below, then re-run.
"""

import os as _os
import sys as _sys_fp
import importlib.util as _ilu


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
        "run_full_pipeline.py: cannot find champion_search.py; searched "
        f"{_candidates!r}. Run this from Aimsun with the bundle model open.")


_HERE = _find_bundle_dir()
if _HERE not in _sys_fp.path:
    _sys_fp.path.insert(0, _HERE)

# Cache-bust so edits to champion_search / batch_runner reload from disk (the
# in-sim ENGINE still needs a full Aimsun restart to pick up engine.py edits).
for _mn in ("champion_search", "_br_champ"):
    _sys_fp.modules.pop(_mn, None)

_cs_path = _os.path.join(_HERE, "champion_search.py")
_spec_cs = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec_cs)
_sys_fp.modules["champion_search"] = _cs
_spec_cs.loader.exec_module(_cs)

# ── REPLICATION SELECTION ─────────────────────────────────────────────────────
# Auto-pick chooses a real, lowest-id replication. If the open model has several
# replications and Aimsun refuses the auto-picked one, force the exact replication
# you run with Play in the GUI by UNCOMMENTING one (name is easiest):
# _cs._br.REPLICATION_NAME = "Replication 1 560 - TSP1"
# _cs._br.REPLICATION_ID = 11129240

# ── Test design ───────────────────────────────────────────────────────────────
# Keep seeds small for a full-algorithm smoke; widen once execution is confirmed.
SEEDS = [300, 400]
_cs.EVAL_SEEDS = list(SEEDS)
_cs.SCORED_SEEDS = list(SEEDS)
_cs.USE_TOPUP_SEEDS = False
# TRAIN_SEEDS left at the champion default: the learner arms train before eval.

# ALL arms (full algorithm sweep). To test a subset, set SUBSET to a name list.
SUBSET = None
_arms = list(_cs.ARMS) if not SUBSET else [a for a in _cs.ARMS if a["name"] in SUBSET]
_results_csv = _os.path.join(_cs._ROOT, f"run_full_pipeline_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"FULL PIPELINE -- corridor={_cs.CORRIDOR}")
    _log(f"  {len(_arms)} arms x {len(SEEDS)} eval seeds "
         f"| learners train on {_cs.TRAIN_SEEDS}")
    _log(f"  arms: {[a['name'] for a in _arms]}")
    _log(f"  results -> {_results_csv}")
    _log("  If a run hangs 'waiting for sim to START' or logs 'cannot be "
         "executed', set _cs._br.REPLICATION_NAME (see the file header).")
    _log("=" * 70)
    _cs.main(arms=_arms, results_csv=_results_csv)
