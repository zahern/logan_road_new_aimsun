"""
champion_zigdog_runner.py -- small paired A/B: NO_TSP vs ZIGDOG.

ZIGDOG (dctsp_zigdog, shared_tsp_engine/specialized_modes.py) is the per-cycle
receding-horizon AOG (arrivals-on-green) optimizer:
  * every cycle it re-solves the NEXT cycle's phase service (HOLD / EXTEND /
    END_EARLY + seconds) to maximise the expected arrivals-on-green of the
    buses predicted to reach the junction, using the timetable ETAs + the live
    schedule deviation, and the MEASURED demands;
  * it inherits the CellQLearn-corridor CTM controller's cross cost
    (ZIGDOG_CTM -> engine _ctm_cross_cost_paxs) instead of the analytic term;
  * the chosen plan is cached between cycle boundaries and re-optimised at
    every new cycle (one coherent plan per cycle, no per-action drift).

RUN inside Aimsun with the corridor model open:
      champion_zigdog_runner.py
-> champion_zigdog_<corridor>.csv

WHAT TO CHECK
  1. tsp_run_summary_*.txt: ACTIVE_TSP_MODE must be ZIGDOG (champion_search's
     mode-dispatch tripwire flags a row that fell through to GENERIC).
  2. TSP log [ZIGDOG] lines: per junction/cycle eta/late/rem_green/pick/score.
  3. Paired objective delta vs NO_TSP on the SAME seeds (the selector does not
     rank ZIGDOG automatically -- read the CSV per arm).

NOTES
  * ZIGDOG is not a learner: it needs no training seeds; the full-sim length
    and the bus timetables come from the model.
  * Engine + specialized_modes edits are cached per Aimsun SESSION -- restart
    Aimsun before the first run of a new ZIGDOG revision.
"""

import os as _os
import sys as _sys_cb
import importlib.util as _ilu


# ── Robustly load champion_search by ABSOLUTE PATH ───────────────────────────
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
        "champion_zigdog_runner.py: cannot find champion_search.py; "
        f"searched {_candidates!r}. Unzip the bundle so both files sit in the "
        "same folder, then run this from Aimsun with the model open.")


_HERE = _find_bundle_dir()
if _HERE not in _sys_cb.path:
    _sys_cb.path.insert(0, _HERE)

# Cache-buster: Aimsun's persistent interpreter caches champion_search from the
# first champion run this session, so edits never load. Purge the chain so it
# re-reads from disk. (In-sim ENGINE still needs a full Aimsun restart.)
for _mn in ("champion_search", "_br_champ"):
    _sys_cb.modules.pop(_mn, None)

_cs_path = _os.path.join(_HERE, "champion_search.py")
_spec_cs = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec_cs)
_sys_cb.modules["champion_search"] = _cs
_spec_cs.loader.exec_module(_cs)

# ── replication selection (same guidance as the other runners) ───────────────
# If Aimsun refuses the auto-picked replication, force the one you run with Play:
# _cs._br.REPLICATION_NAME = "Replication 1 560 - TSP1"
# _cs._br.REPLICATION_ID = 11129240

# ── seeds: small paired A/B first; widen to the SUMO set when happy ──────────
SEEDS = [300, 400]                 # widen: [300, 400, 500, 600, 700]
_cs.EVAL_SEEDS = list(SEEDS)
_cs.SCORED_SEEDS = list(SEEDS)     # what the selector must require
_cs.USE_TOPUP_SEEDS = False

SUBSET = [
    "ZIGCTM",    # normal CTM controller, phase-binary state, NO AOG term
    "ZIGDOG_Q",  # plain Q-learner + AOG on the phase-binary state space
    "ZIGDOG",    # the heuristic AOG optimizer (same state/reward, no learning)
    "NO_TSP",    # paired baseline on the SAME seeds -> direct delta
]

_by_name = {a["name"]: a for a in _cs.ARMS}
_arms = [_by_name[n] for n in SUBSET if n in _by_name]   # SUBSET order = run order
_missing = sorted(set(SUBSET) - set(_by_name))
_results_csv = _os.path.join(_cs._ROOT, f"champion_zigdog_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"ZIGDOG A/B -- corridor={_cs.CORRIDOR}")
    _log(f"  {len(_arms)} arms x {len(SEEDS)} eval seeds")
    _log(f"  arms: {[a['name'] for a in _arms]}")
    if _missing:
        _log(f"  WARNING: not found in _cs.ARMS -> {_missing}")
    _log(f"  results -> {_results_csv}")
    _log("  READ FIRST: run summary ACTIVE_TSP_MODE == ZIGDOG; then [ZIGDOG] log lines")
    _log("=" * 70)
    _cs.main(arms=_arms, results_csv=_results_csv)
