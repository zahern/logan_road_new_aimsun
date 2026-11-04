"""run_paxwin_scats_both_seed400.py -- one-file, seed-400 A/B for both variants.

Runs, sequentially, on seed 400 only (NO_TSP baseline included in each):
  1) CHAMP_PAXWIN_MODELPLAN       (clean: model plan untouched, TSP only)
  2) CHAMP_PAXWIN_SCATS_CYCLEFIX  (cycle clamp only, splits held)
  3) CHAMP_PAXWIN_SCATS_STATE     (SCATS share + cycle clamp, splits held)

Then writes a combined Purdue time-space green-band figure with the BEFORE plan
(NO_TSP / model commission) next to the CYCLEFIX and SCATS_STATE final plans:

  paxwin_scats_purdue_before_after_seed400_v3.png

Execute in the Aimsun console with KG open, AFTER a full Aimsun restart:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_paxwin_scats_both_seed400.py").read())
"""
import glob
import importlib
import os as _os
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
_KG = _os.path.join(_HERE, "kg")
if _KG not in _sys.path:
    _sys.path.insert(0, _KG)

_os.environ["PAXWIN_SEEDS"] = "400"
_os.environ["PAXWIN_WARMUP"] = "0"

# Aimsun caches modules; reload the arm table so MODELPLAN is visible without
# a full restart (the engine build is unchanged at 1800).
if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])


def _newest(pattern):
    fs = glob.glob(_os.path.join(_KG, "logs", pattern))
    return max(fs, key=_os.path.getmtime) if fs else None


def _run(arm, out_csv):
    _os.environ["PAXWIN_ARM"] = arm
    _os.environ["PAXWIN_OUT_CSV"] = _os.path.join(_HERE, out_csv)
    _mod = "run_paxwin_game_vs_notsp"
    if _mod in _sys.modules:
        importlib.reload(_sys.modules[_mod])
    else:
        import run_paxwin_game_vs_notsp  # noqa: F401  (runs the batch)


# 1) CLEAN isolation first (fresh-session NO_TSP baseline): model plan
#    untouched, no SCATS-hist/Webster rewrite, no offsets, TSP controller on.
_run("CHAMP_PAXWIN_MODELPLAN",
     "paxwin_modelplan_seed400_vs_notsp.csv")
_notsp_csv = _newest("plan_evolution_NO_TSP_*.csv")
_model_csv = _newest("plan_evolution_CHAMP_PAXWIN_MODELPLAN_*.csv")

# 2) cycle-clamp-only arm
_run("CHAMP_PAXWIN_SCATS_CYCLEFIX",
     "paxwin_scats_cyclefix_v2_seed400_vs_notsp.csv")
_cyc_csv = _newest("plan_evolution_CHAMP_PAXWIN_SCATS_CYCLEFIX_*.csv")

# 3) guarded full-state arm
_run("CHAMP_PAXWIN_SCATS_STATE_SAFE",
     "paxwin_scats_state_safe_seed400_vs_notsp.csv")
_state_csv = _newest("plan_evolution_CHAMP_PAXWIN_SCATS_STATE_SAFE_*.csv")

# 4) Purdue BEFORE (NO_TSP / model plan) vs MODELPLAN / CYCLEFIX / STATE
try:
    if "plot_plan_evolution" in _sys.modules:
        importlib.reload(_sys.modules["plot_plan_evolution"])
    import plot_plan_evolution as _ppe
    _out = _os.path.join(
        _HERE, "paxwin_scats_purdue_before_after_seed400_v3.png")
    _p = _ppe.run_compare(
        [_notsp_csv, _model_csv, _cyc_csv, _state_csv],
        labels=["BEFORE (NO_TSP / model plan)",
                "MODELPLAN (no startup rewrite)",
                "CYCLEFIX final",
                "SCATS_STATE_SAFE final"],
        out_path=_out,
        title="Purdue time-space green band, seed 400: before vs after")
    print("\nPurdue before/after figure ->", _p)
except Exception as _e:
    print("Purdue before/after figure FAILED:", repr(_e))

print("\nPer-arm plan-evolution figures (initial vs final) were also written "
      "beside each plan_evolution_*.csv in kg/logs.")
