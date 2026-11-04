"""run_fixed_action_pbil_3seeds.py -- fixed plan + PBIL actions, 3 seeds.

For each seed in 400,401,402 this runs ONE NO_TSP baseline and three arms:
    CHAMP_FIXED_PBIL_GE           small green extensions only
    CHAMP_FIXED_PBIL_GE_ER        green extensions + early red
    CHAMP_FIXED_PBIL_GE_ER_INS    + phase insertion/advance

The commissioned plan is never re-timed; PBIL chooses one small action per
junction per interval and queues it one interval ahead.

Run in the Aimsun console AFTER a full Aimsun restart:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_fixed_action_pbil_3seeds.py").read())
"""
import csv
import importlib
import os as _os
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)
_KG = _os.path.join(_HERE, "kg")
if _KG not in _sys.path:
    _sys.path.insert(0, _KG)

_ARMS = [
    "CHAMP_FIXED_PBIL_GE",
    "CHAMP_FIXED_PBIL_GE_ER",
    "CHAMP_FIXED_PBIL_GE_ER_INS",
]
_OUT = _os.path.join(_HERE, "paxwin_fixed_action_pbil_3seeds.csv")

_os.environ["PAXWIN_SEEDS"] = "400,401,402"
_os.environ["PAXWIN_WARMUP"] = "0"
_os.environ["PAXWIN_ARM"] = _ARMS[0]
_os.environ["PAXWIN_ARMS"] = ",".join(_ARMS)
_os.environ["PAXWIN_OUT_CSV"] = _OUT

if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])

_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401  (runs the suite)


def _f(r, k):
    try:
        return float(r.get(k, "") or 0.0)
    except Exception:
        return 0.0


try:
    with open(_OUT, newline="", encoding="utf-8-sig") as _fh:
        _rows = list(csv.DictReader(_fh))
    print("\n" + "=" * 112)
    print("FIXED-TIME + PBIL ACTIONS, 3 SEEDS")
    print("=" * 112)
    print("%-32s %6s %9s %10s %10s %9s %8s"
          % ("arm", "seed", "objective", "delay_h", "main_h", "queue", "natGrn"))
    for _r in _rows:
        print("%-32s %6s %9.2f %10.1f %10.1f %9.1f %8.0f"
              % (str(_r.get("run_experiment", ""))[:32],
                 str(_r.get("seed", ""))[:6],
                 _f(_r, "stats_Objective_PaxPerDelayHr"),
                 _f(_r, "stats_TotalPassDelay_hrs"),
                 _f(_r, "stats_MainPassDelay_hrs"),
                 _f(_r, "stats_Net_MeanQueue_All"),
                 _f(_r, "stats_TSP_NaturalGreen")))
except Exception as _e:
    print("Fixed-action summary failed:", repr(_e))
