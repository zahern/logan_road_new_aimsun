"""
champion_gated10.py -- 10-seed baseline comparison: CELLQLEARN_GATED vs NO_TSP.

WHY: CELLQLEARN_GATED was a NO_TSP CLONE on the 6-seed champion run -- zero TSP
actions across every seed (207.26 = NO_TSP exactly), because the net-benefit gate
vetoed every action. That was on the 12-bus scenario. This runs it against the
105-bus scenario over TEN seeds to answer two questions:

  1. does the gate ever open when there is real bus demand to justify an action?
  2. if it does, does acting beat doing nothing?

NO_TSP is included as the baseline on the SAME seeds, so the comparison is
paired and the answer is a direct delta, not a cross-run inference.

The SUMO/Gadi twin of this run was submitted as PRE_OVERRIDE=champgated10
(CELLQLEARN_GATED train + 10 evals, NO_TSP 10 evals), so the two platforms
answer the same question on the same seeds.

RUN inside Aimsun, corridor model open:
      champion_gated10.py
-> champion_gated10_<corridor>.csv
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
        "champion_gated10.py: cannot find champion_search.py; "
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

# ── Replication selection ────────────────────────────────────────────────────
# The open model has MANY replications under the Micro SRC experiment (incl.
# auto-named "Replication <id>" entries). get_first_replication auto-picks a real,
# executable child replication. If it still hits "Action execute for object type
# GKReplication cannot be executed", force the exact replication you run by hand in
# the Aimsun GUI by UNCOMMENTING one of these (name is easiest):
# _cs._br.REPLICATION_NAME = "Replication 1 560 - TSP1"
# _cs._br.REPLICATION_ID = 11136764

# ── ten seeds: the union of the eval sets used so far ────────────────────────
SEEDS10 = [300, 400, 500, 600, 700, 1200, 1300, 1400, 1500, 1600]
_cs.EVAL_SEEDS = list(SEEDS10)
_cs.SCORED_SEEDS = list(SEEDS10)     # what the selector must require
_cs.USE_TOPUP_SEEDS = False
# TRAIN_SEEDS left at the default [800, 900, 1000, 1100]: CELLQLEARN_GATED is a
# learner, so it trains before its evals exactly as in the champion run.

SUBSET = [
    "CELLQLEARN_GATED",   # the arm under test -- FIRST: NO_TSP has already run
                          # all 10 seeds, so start the new work immediately rather
                          # than re-running the baseline before it.
    "NO_TSP",             # baseline, same seeds -> paired comparison
]

_by_name = {a["name"]: a for a in _cs.ARMS}
_arms = [_by_name[n] for n in SUBSET if n in _by_name]   # SUBSET order is the run order
_missing = sorted(set(SUBSET) - set(_by_name))
_results_csv = _os.path.join(_cs._ROOT,
                             f"champion_gated10_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"GATED-10 BASELINE SWEEP -- corridor={_cs.CORRIDOR}")
    _log(f"  {len(_arms)} arms x {len(SEEDS10)} eval seeds "
         f"| learner trains on {_cs.TRAIN_SEEDS}")
    _log(f"  arms: {[a['name'] for a in _arms]}")
    if _missing:
        _log(f"  WARNING: not found in _cs.ARMS -> {_missing}")
    _log(f"  results -> {_results_csv}")
    _log("  READ FIRST: does CELLQLEARN_GATED take ANY TSP action?")
    _log("    actions == 0 on all 10 seeds -> the gate never opens; it is a")
    _log("    NO_TSP clone and the arm is dead on this scenario.")
    _log("    actions  > 0 -> read the paired objective delta vs NO_TSP.")
    _log("=" * 70)
    _cs.main(arms=_arms, results_csv=_results_csv)
