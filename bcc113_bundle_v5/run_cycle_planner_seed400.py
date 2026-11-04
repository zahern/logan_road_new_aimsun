"""run_cycle_planner_seed400.py -- rolling cycle-level plan variants, seed 400.

One NO_TSP baseline, then four one-cycle-delayed planners:
    CHAMP_PAXWIN_CYCLE_PBIL       SCATS seed + joint PBIL, 120 s cadence
    CHAMP_PAXWIN_CYCLE_PBIL_FAST  90 s cadence, smaller moves, 12 candidates
    CHAMP_PAXWIN_CYCLE_SCATS      SCATS seed only, no PBIL
    CHAMP_PAXWIN_CYCLE_PBIL_MAIN  larger main-share PBIL moves

Run in the Aimsun console AFTER a full Aimsun restart:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_cycle_planner_seed400.py").read())
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
    "CHAMP_PAXWIN_CYCLE_PBIL",
    "CHAMP_PAXWIN_CYCLE_PBIL_FAST",
    "CHAMP_PAXWIN_CYCLE_SCATS",
    "CHAMP_PAXWIN_CYCLE_PBIL_MAIN",
]
_OUT = _os.path.join(_HERE, "paxwin_cycle_planner_seed400.csv")

_os.environ["PAXWIN_SEEDS"] = "400"
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
    print("CYCLE-PLANNER SUITE (single NO_TSP baseline)")
    print("=" * 112)
    print("%-32s %9s %10s %10s %9s %9s %8s %8s"
          % ("arm", "objective", "delay_h", "main_h", "side_h",
             "queue", "busTT", "natGrn"))
    for _r in _rows:
        print("%-32s %9.2f %10.1f %10.1f %9.1f %9.1f %8.1f %8.0f"
              % (str(_r.get("run_experiment", ""))[:32],
                 _f(_r, "stats_Objective_PaxPerDelayHr"),
                 _f(_r, "stats_TotalPassDelay_hrs"),
                 _f(_r, "stats_MainPassDelay_hrs"),
                 _f(_r, "stats_SidePassDelay_hrs"),
                 _f(_r, "stats_Net_MeanQueue_All"),
                 _f(_r, "stats_AvgBusTT_s"),
                 _f(_r, "stats_TSP_NaturalGreen")))
except Exception as _e:
    print("Cycle-planner summary failed:", repr(_e))
