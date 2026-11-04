"""run_scats_suite_seed400.py -- ONE NO_TSP baseline + all test arms, seed 400.

Runs a single batch:
    NO_TSP                              (once)
    CHAMP_PAXWIN_MODELPLAN              (model plan, DS adapt + new failsafe)
    CHAMP_PAXWIN_MODELPLAN_NODS         (model plan, DS adapt OFF)
    CHAMP_PAXWIN_SCATS_CYCLEFIX         (offset-preserving cycle clamp)
    CHAMP_PAXWIN_SCATS_STATE            (offset-preserving SCATS share/cycle)
    CHAMP_PAXWIN_GAME                   (old champion, now with the fixes)

Then prints a per-arm summary and writes two Purdue before/after figures:
    paxwin_scats_suite_seed400_model_ds_purdue.png
    paxwin_scats_suite_seed400_scats_purdue.png

Execute in the Aimsun console with KG open, AFTER a full Aimsun restart:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_scats_suite_seed400.py").read())
"""
import csv
import glob
import importlib
import os as _os
import sys as _sys
import time as _time
import traceback

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
_KG = _os.path.join(_HERE, "kg")
if _KG not in _sys.path:
    _sys.path.insert(0, _KG)

_ARMS = [
    "CHAMP_PAXWIN_MODELPLAN",
    "CHAMP_PAXWIN_MODELPLAN_NODS",
    "CHAMP_PAXWIN_MODELPLAN_JUMP",
    "CHAMP_PAXWIN_SCATS_CYCLEFIX",
    "CHAMP_PAXWIN_SCATS_STATE",
    "CHAMP_PAXWIN_GAME",
]
_OUT = _os.path.join(_HERE, "paxwin_scats_suite_seed400.csv")

_os.environ["PAXWIN_SEEDS"] = "400"
_os.environ["PAXWIN_WARMUP"] = "0"
_os.environ["PAXWIN_ARM"] = _ARMS[0]
_os.environ["PAXWIN_ARMS"] = ",".join(_ARMS)
_os.environ["PAXWIN_OUT_CSV"] = _OUT

_T0 = _time.time()
if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])

_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401  (runs the whole suite)


# --------------------------------------------------------------------------
# Suite summary (one row per arm, same NO_TSP baseline)
# --------------------------------------------------------------------------
def _f(r, k):
    try:
        return float(r.get(k, "") or 0.0)
    except Exception:
        return 0.0


try:
    with open(_OUT, newline="", encoding="utf-8-sig") as _fh:
        _rows = list(csv.DictReader(_fh))
    print("\n" + "=" * 112)
    print("SEED-400 SUITE (single NO_TSP baseline)")
    print("=" * 112)
    print("%-30s %9s %10s %10s %9s %9s %8s %8s"
          % ("arm", "objective", "delay_h", "main_h", "side_h",
             "queue", "busTT", "natGrn"))
    for _r in _rows:
        print("%-30s %9.2f %10.1f %10.1f %9.1f %9.1f %8.1f %8.0f"
              % (str(_r.get("run_experiment", ""))[:30],
                 _f(_r, "stats_Objective_PaxPerDelayHr"),
                 _f(_r, "stats_TotalPassDelay_hrs"),
                 _f(_r, "stats_MainPassDelay_hrs"),
                 _f(_r, "stats_SidePassDelay_hrs"),
                 _f(_r, "stats_Net_MeanQueue_All"),
                 _f(_r, "stats_AvgBusTT_s"),
                 _f(_r, "stats_TSP_NaturalGreen")))
except Exception as _e:
    print("Suite summary failed:", repr(_e))


# --------------------------------------------------------------------------
# Purdue before/after figures
# --------------------------------------------------------------------------
def _newest(arm):
    _fs = glob.glob(_os.path.join(_KG, "logs",
                                  "plan_evolution_%s_*.csv" % arm))
    _fs = [f for f in _fs if _os.path.getmtime(f) >= _T0]
    return max(_fs, key=_os.path.getmtime) if _fs else None


try:
    if "plot_plan_evolution" in _sys.modules:
        importlib.reload(_sys.modules["plot_plan_evolution"])
    import plot_plan_evolution as _ppe

    _before = _newest("NO_TSP")
    _model = _newest("CHAMP_PAXWIN_MODELPLAN")
    _nods = _newest("CHAMP_PAXWIN_MODELPLAN_NODS")
    _game = _newest("CHAMP_PAXWIN_GAME")
    _cyc = _newest("CHAMP_PAXWIN_SCATS_CYCLEFIX")
    _state = _newest("CHAMP_PAXWIN_SCATS_STATE")

    _p1 = None
    try:
        _p1 = _ppe.run_compare(
            [_before, _model, _nods, _game],
            labels=["BEFORE (NO_TSP / model plan)",
                    "MODELPLAN (DS/PBIL + failsafe)",
                    "MODELPLAN_NODS (DS off)",
                    "CHAMP_PAXWIN_GAME"],
            out_path=_os.path.join(
                _HERE, "paxwin_scats_suite_seed400_model_ds_purdue_v2.png"),
            title="Purdue green band, seed 400: model plan / DS adaptation")
        print("\nPurdue (model/DS) ->", _p1)
    except Exception as _e1:
        print("Purdue (model/DS) FAILED:", repr(_e1))
        traceback.print_exc()

    _p2 = None
    try:
        _p2 = _ppe.run_compare(
            [_before, _cyc, _state],
            labels=["BEFORE (NO_TSP / model plan)",
                    "CYCLEFIX (offset-preserving)",
                    "SCATS_STATE (offset-preserving)"],
            out_path=_os.path.join(
                _HERE, "paxwin_scats_suite_seed400_scats_purdue_v3.png"),
            title="Purdue green band, seed 400: SCATS plan rewrites")
        print("Purdue (SCATS)   ->", _p2)
    except Exception as _e2:
        print("Purdue (SCATS) FAILED:", repr(_e2))
        traceback.print_exc()
except Exception as _e:
    print("Purdue suite figures FAILED:", repr(_e))
    traceback.print_exc()
