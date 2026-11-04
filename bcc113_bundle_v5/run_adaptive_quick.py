"""run_adaptive_quick.py -- quick NO_TSP vs adaptive-controller A/B/C/D.

Runs one seed (400 by default) with ONE NO_TSP baseline followed by:
    CHAMP_ADAPTIVE_AIMSUN       (pressure-forecast cycle planner -- the baseline adaptive arm)
    CHAMP_ADAPTIVE_DS           (DS-driven splits, commissioned band, planner OFF -- SCATS-faithful)
    CHAMP_ADAPTIVE_AIMSUN_DSW   (cycle planner, but plan CHOICE made saturation-dominant: service_gap>>pressure, frozen)

Set ADAPTIVE_SEEDS="400,401,402" for the 3-seed check.
Set ADAPTIVE_ARMS="CHAMP_ADAPTIVE_DS" to run just one.

Run in the Aimsun console AFTER a full restart:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_adaptive_quick.py").read())
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

_SEEDS = _os.environ.get("ADAPTIVE_SEEDS", "400").strip() or "400"
_ARMS = (_os.environ.get("ADAPTIVE_ARMS", "").strip()
         or "CHAMP_ADAPTIVE_AIMSUN,CHAMP_ADAPTIVE_DS,CHAMP_ADAPTIVE_AIMSUN_DSW")
_OUT = _os.path.join(_HERE, "paxwin_adaptive_quick.csv")

_os.environ["PAXWIN_SEEDS"] = _SEEDS
_os.environ["PAXWIN_WARMUP"] = "0"
# PAXWIN_ARMS runs ONE NO_TSP baseline followed by every listed arm.
_os.environ["PAXWIN_ARM"] = _ARMS.split(",")[0].strip()
_os.environ["PAXWIN_ARMS"] = _ARMS
_os.environ["PAXWIN_OUT_CSV"] = _OUT

if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])
_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401


def _f(r, k):
    try:
        return float(r.get(k, "") or 0.0)
    except Exception:
        return 0.0


try:
    with open(_OUT, newline="", encoding="utf-8-sig") as _fh:
        _rows = list(csv.DictReader(_fh))
    print("\n" + "=" * 96)
    print("QUICK ADAPTIVE A/B -- seeds %s" % _SEEDS)
    print("=" * 96)
    print("%-30s %6s %9s %10s %10s %8s"
          % ("arm", "seed", "objective", "delay_h", "queue", "natGrn"))
    for _r in _rows:
        print("%-30s %6s %9.2f %10.1f %10.1f %8.0f"
              % (str(_r.get("run_experiment", ""))[:30],
                 str(_r.get("run_seed", ""))[:6],
                 _f(_r, "stats_Objective_PaxPerDelayHr"),
                 _f(_r, "stats_TotalPassDelay_hrs"),
                 _f(_r, "stats_Net_MeanQueue_All"),
                 _f(_r, "stats_TSP_NaturalGreen")))
except Exception as _e:
    print("Adaptive quick summary failed:", repr(_e))
