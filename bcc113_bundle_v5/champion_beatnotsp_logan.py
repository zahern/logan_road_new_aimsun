"""
champion_beatnotsp_logan.py -- can anything beat NO_TSP on Logan Road?

Picks the two most likely winners from the Aimsun Logan evidence and re-tests
them under the NEW stack (detailed SCATS detectors + just-in-time insertion
lead cap INS_MAX_LEAD_S=20 + GE solved-not-fixed), because the old champion
numbers were measured WITHOUT those fixes:

  NO_TSP            control (155.96 baseline; unbeaten in champion matrix)
  CELLQLEARN_GATED   nearest challenger (-0.06%, 3.9% action rate -- the only
                      selective arm; net-benefit gate is what separates survival
                      from loss on the action-rate curve)
  DCTSP_MP_ECTM       pure-insertion arm (-6.7% with 76 insertions/run at
                      AvgInsertionWait ~56 s); the lead-cap fix targets exactly
                      its failure mode, so it has the biggest upside -- or the
                      cleanest refutation if it still loses.

RUN (inside Aimsun, Logan_RD_for_QUT_with_detectors.ang OPEN):
    champion_beatnotsp_logan.py
Then read champion_beatnotsp_logan_road_new.csv (NO_TSP is the reference row).

Runs: NO_TSP (3 eval) + CELLQLEARN_GATED (4 train + 3 eval) +
      DCTSP_MP_ECTM (3 eval, analytic, no train) = 13 runs.

BEFORE running: quit Aimsun completely and restart (module caching), then
confirm the [LOAD] line shows ENGINE_BUILD 2026-10-07T00:00-ins-lead-cap --
otherwise you are testing the OLD engine (shadow-copy saga).

READ-OUT (compare vs champion_logan_road_new.csv baselines):
  - objective (stats_Objective_PaxPerDelayHr): does GATED or MP_ECTM clear 155.96?
  - on-time% (= 100 - schedule_pct_late - schedule_pct_bunched): baseline ~36.5%.
  - AvgInsertionWait: must drop to <= ~20 s (was 13-56 s) -- the fix working.
  - eta_horizon skips rising = deferrals (good); insertions granted with
    ETA<=20 s.
Pass resume=True so an interrupted batch continues instead of restarting.
"""
import os as _os
import sys as _sys

# ── Import bootstrap (Aimsun GUI path fix) ──────────────────────────────
# Aimsun's Run Script menu does NOT put this script's folder on sys.path, so
# a bare `import champion_search` fails with ModuleNotFoundError when the
# console CWD is elsewhere (e.g. the model folder). Anchor to THIS file's
# directory (falling back to cwd, then to the open model's document dir).
_HERE = None
try:
    _HERE = _os.path.dirname(_os.path.abspath(__file__))
except Exception:
    _HERE = None
if not _HERE or not _os.path.isfile(_os.path.join(_HERE, "champion_search.py")):
    _HERE = _os.path.abspath(_os.getcwd())
if not _os.path.isfile(_os.path.join(_HERE or "", "champion_search.py")):
    # Pasted into the Aimsun console (__file__ undefined and CWD elsewhere):
    # start from the open model's folder and walk up to the bundle root.
    _HERE = None
    try:
        from PyANGKernel import GKSystem
        _d = _os.path.abspath(str(GKSystem.getSystem().getActiveModel(
            ).getDocumentDirectory().absolutePath()))
        for _ in range(6):
            if _os.path.isfile(_os.path.join(_d, "champion_search.py")):
                _HERE = _d
                break
            _d = _os.path.dirname(_d)
    except Exception:
        pass
if _HERE and _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
import champion_search as _cs

SUBSET = {"NO_TSP", "CELLQLEARN_GATED", "DCTSP_MP_ECTM",
          "CELLQ_LEARN_UNCOORD", "CELLQ_BUSSPLIT", "CELLQ_VDET_ON",
          "DCTSP_ZIG", "DCTSP_BARGAIN_SPM", "NASH_BARGAIN",
          "ZIGDOG", "MAXPRESSURE_FIX"}

# Narrow Seeds only; keep default TRAIN_SEEDS so GATED trains exactly like the
# champion runs it is compared against.
_cs.EVAL_SEEDS = [300, 400, 500]

_subset_arms = [a for a in _cs.ARMS if a["name"] in SUBSET]
assert {a["name"] for a in _subset_arms} == SUBSET, \
    "missing arms: %s" % (SUBSET - {a["name"] for a in _subset_arms})
_subset_csv = _os.path.join(_cs._ROOT, "champion_beatnotsp_%s.csv" % _cs.CORRIDOR)


if __name__ == "__main__":
    _cs._br.log("=" * 70)
    _cs._br.log("BEAT-NO_TSP TEST -- corridor=%s | arms=%s | eval=%s" % (
        _cs.CORRIDOR, sorted(SUBSET), _cs.EVAL_SEEDS))
    _cs._br.log("  -> %s" % _subset_csv)
    _cs._br.log("=" * 70)
    _cs.main(arms=_subset_arms, results_csv=_subset_csv, resume=True)
