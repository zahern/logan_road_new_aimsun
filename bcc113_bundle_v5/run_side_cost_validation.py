"""run_side_cost_validation.py -- validate the MEASURED side-cost fix + reward calibration.

Runs ONLY the arms that swung between much-better and much-worse across seeds
(NO_TSP baseline, CELLQLEARN, CELLQLEARN_GATED, DCTSP_BARGAIN_SPM, MAXPRESSURE_LB)
on ALL 5 EVAL seeds (300,400,500,600,700 -- so it hits the bad seeds 500/700),
Phase-1 only (no bus-demand / sensitivity phases). It turns on:
  * MEASURED_SIDE_COST (global) -- price the cross cost from MEASURED cross
    congestion so a jammed cross approach is never under-priced, and
  * BXT_EVAL_DIAGNOSTICS -- emit the [BXT_EVAL] predicted-vs-realized line for the
    BXT (CELLQLEARN) arms so you can check calibration per seed.
Writes champion_sidecostval_<corridor>.csv -- does NOT touch champion_<corridor>.csv,
so your Sep-12 baseline stays intact for comparison.

**RESTART AIMSUN FIRST.** The engine + specialized_modes changes (the measured
side cost) are loaded once per Aimsun SESSION -- a fresh pipeline launch canNOT
reload them. Confirm ENGINE_BUILD=...measured-side-cost on the [LOAD] line.

Run in the Aimsun Python console with one corridor model open:
    run_side_cost_validation.py
Then analyse:
    python analyze_bxt_predictions.py        # newest kg/logs log
    # and eyeball champion_sidecostval_<corridor>.csv: on seeds 500/700 the
    # CELLQLEARN/BARGAIN car delta vs NO_TSP should be much smaller than before.

To run the FULL pipeline instead (all arms + bus-demand + sensitivity), set
os.environ['BXT_EVAL_DIAG']='1' and run run_champion_pipeline.py (main(smoke=False)).
"""
import os as _os
import sys as _sys
import importlib.util as _ilu

# Turn on the [BXT_EVAL] predicted-vs-realized diagnostics for this session.
_os.environ["BXT_EVAL_DIAG"] = "1"

# Only the arms that showed the seed-lottery swing (plus the NO_TSP baseline).
_SUBSET = {"NO_TSP", "CELLQLEARN", "CELLQLEARN_GATED",
           "DCTSP_BARGAIN_SPM", "MAXPRESSURE_LB"}


def _find_bundle_dir():
    cands = []
    try:
        cands.append(_os.path.dirname(_os.path.abspath(__file__)))
    except (NameError, TypeError):
        pass
    try:
        from PyANGKernel import GKSystem
        _md = GKSystem.getSystem().getActiveModel().getDocumentDirectory().absolutePath()
        cands += [_md, _os.path.dirname(_md), _os.path.dirname(_os.path.dirname(_md))]
    except Exception:
        pass
    cands.append(_os.getcwd())
    for c in cands:
        try:
            c = _os.path.abspath(c)
        except Exception:
            continue
        if _os.path.isfile(_os.path.join(c, "champion_search.py")):
            return c
    raise RuntimeError(
        "run_side_cost_validation.py: cannot find champion_search.py; "
        f"searched {cands!r}. Open the corridor model and run from the bundle.")


_HERE = _find_bundle_dir()
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

# Fresh reload of champion_search + the phase modules it caches so edits load
# without an Aimsun restart. This list MIRRORS run_champion_pipeline's cache-bust
# EXACTLY -- in particular it does NOT pop "batch_runner": popping it forces
# champion_search to import a SECOND, fresh batch_runner while the session still
# holds the original, splitting the runner's completion-detection state (marker
# baselines) across two module instances so [LOAD]/[FINISH] are never detected ->
# every run times out at 30 min and is recorded run_success=False (blank rows).
# Reusing the session's batch_runner (only re-registering _br_champ) keeps ONE
# runner instance. (The ENGINE + specialized_modes still need a real Aimsun
# restart -- session-cached; this only refreshes the Python orchestration layer.)
for _mn in ("champion_search", "_br_champ", "_pipeline_phase1",
            "_pipeline_phase2", "_pipeline_phase3"):
    _sys.modules.pop(_mn, None)

_spec = _ilu.spec_from_file_location(
    "champion_search", _os.path.join(_HERE, "champion_search.py"))
_cs = _ilu.module_from_spec(_spec)
_sys.modules["champion_search"] = _cs
_spec.loader.exec_module(_cs)

_arms = [a for a in _cs.ARMS if a["name"] in _SUBSET]
_missing = _SUBSET - {a["name"] for a in _arms}
if _missing:
    print(f"[SIDECOST-VAL] WARNING: arms not found in champion_search.ARMS: {sorted(_missing)}")
_csv = _os.path.join(_HERE, f"champion_sidecostval_{_cs.CORRIDOR}.csv")

print("=" * 70)
print(f"[SIDECOST-VAL] corridor={_cs.CORRIDOR}  arms={[a['name'] for a in _arms]}")
print(f"[SIDECOST-VAL] eval seeds={_cs.EVAL_SEEDS}  (learners also train on {_cs.TRAIN_SEEDS})")
print(f"[SIDECOST-VAL] MEASURED_SIDE_COST global={_cs.GLOBAL_MEASURED_SIDE_COST}  "
      f"EVAL_DIAGNOSTICS={_cs.EVAL_DIAGNOSTICS}")
print(f"[SIDECOST-VAL] writing -> {_csv}")
print("[SIDECOST-VAL] RESTART AIMSUN if you have not -- confirm ENGINE_BUILD="
      "...measured-side-cost on the [LOAD] line.")
print("=" * 70)

_cs.main(arms=_arms, results_csv=_csv)
