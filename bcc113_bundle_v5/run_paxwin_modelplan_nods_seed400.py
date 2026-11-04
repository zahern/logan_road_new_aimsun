"""run_paxwin_modelplan_nods_seed400.py -- clean model plan, DS adapt OFF.

Runs seed 400 only:
  NO_TSP                    (model plan)
  CHAMP_PAXWIN_MODELPLAN_NODS (model plan untouched + TSP, no DS split/cycle
                              adaptation, no startup rewrite, no offsets)

Then writes a Purdue before/after (NO_TSP vs NODS final plan).

Execute in the Aimsun console with KG open, AFTER a full Aimsun restart:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_paxwin_modelplan_nods_seed400.py").read())
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

_os.environ["PAXWIN_ARM"] = "CHAMP_PAXWIN_MODELPLAN_NODS"
_os.environ["PAXWIN_OUT_CSV"] = _os.path.join(
    _HERE, "paxwin_modelplan_nods_seed400_vs_notsp.csv")
_os.environ["PAXWIN_WARMUP"] = "0"
_os.environ["PAXWIN_SEEDS"] = "400"

if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])

_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401  (runs the batch)


def _newest(pattern):
    fs = glob.glob(_os.path.join(_KG, "logs", pattern))
    return max(fs, key=_os.path.getmtime) if fs else None


try:
    if "plot_plan_evolution" in _sys.modules:
        importlib.reload(_sys.modules["plot_plan_evolution"])
    import plot_plan_evolution as _ppe
    _n = _newest("plan_evolution_NO_TSP_*.csv")
    _a = _newest("plan_evolution_CHAMP_PAXWIN_MODELPLAN_NODS_*.csv")
    _out = _os.path.join(
        _HERE, "paxwin_modelplan_nods_purdue_before_after_seed400.png")
    _p = _ppe.run_compare(
        [_n, _a],
        labels=["BEFORE (NO_TSP / model plan)",
                "MODELPLAN_NODS final (no DS adapt)"],
        out_path=_out,
        title="Purdue time-space green band, seed 400: model plan vs NODS")
    print("\nPurdue before/after figure ->", _p)
except Exception as _e:
    print("Purdue before/after figure FAILED:", repr(_e))
