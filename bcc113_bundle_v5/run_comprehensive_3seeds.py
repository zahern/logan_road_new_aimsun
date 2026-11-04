"""run_comprehensive_3seeds.py -- all current directions, seeds 400/401/402.

For each seed: ONE NO_TSP baseline, then the existing plan/DS/SCATS arms and
the new rolling-cycle and fixed-time PBIL-action arms. This is the broad
direction test; expect 3 x (1 + 14) replications.

Run in the Aimsun console AFTER a full Aimsun restart:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_comprehensive_3seeds.py").read())
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
    # Existing plan / DS / SCATS directions
    "CHAMP_PAXWIN_MODELPLAN",
    "CHAMP_PAXWIN_MODELPLAN_NODS",
    "CHAMP_PAXWIN_MODELPLAN_JUMP",
    "CHAMP_PAXWIN_SCATS_CYCLEFIX",
    "CHAMP_PAXWIN_SCATS_STATE",
    "CHAMP_PAXWIN_SCATS_STATE_SAFE",
    "CHAMP_PAXWIN_GAME",
    "CHAMP_DS_GAME_BAL",
    "CHAMP_DS_GAME_THRU",
    "CHAMP_DS_GAME_RELIEF",
    "CHAMP_MASTER_LINK_PRESSURE",
    "CHAMP_ADAPTIVE_AIMSUN",
    # Rolling cycle-level planners (SCATS seed + PBIL, one-cycle delay)
    "CHAMP_PAXWIN_CYCLE_PBIL",
    "CHAMP_PAXWIN_CYCLE_PBIL_FAST",
    "CHAMP_PAXWIN_CYCLE_SCATS",
    "CHAMP_PAXWIN_CYCLE_PBIL_MAIN",
    # Fixed commissioned plan + PBIL action chooser
    "CHAMP_FIXED_PBIL_GE",
    "CHAMP_FIXED_PBIL_GE_ER",
    "CHAMP_FIXED_PBIL_GE_ER_INS",
]
_OUT = _os.path.join(_HERE, "paxwin_comprehensive_3seeds.csv")

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
    print("\n" + "=" * 128)
    print("COMPREHENSIVE DIRECTION TEST, SEEDS 400/401/402")
    print("=" * 128)
    print("%-34s %6s %9s %10s %10s %9s %8s %8s"
          % ("arm", "seed", "objective", "delay_h", "main_h",
             "side_h", "queue", "natGrn"))
    for _r in _rows:
        print("%-34s %6s %9.2f %10.1f %10.1f %9.1f %9.1f %8.0f"
              % (str(_r.get("run_experiment", ""))[:34],
                 str(_r.get("seed", ""))[:6],
                 _f(_r, "stats_Objective_PaxPerDelayHr"),
                 _f(_r, "stats_TotalPassDelay_hrs"),
                 _f(_r, "stats_MainPassDelay_hrs"),
                 _f(_r, "stats_SidePassDelay_hrs"),
                 _f(_r, "stats_Net_MeanQueue_All"),
                 _f(_r, "stats_TSP_NaturalGreen")))

    # Direction summary: mean objective per arm vs the NO_TSP mean.
    _by = {}
    for _r in _rows:
        _a = str(_r.get("run_experiment", ""))
        try:
            _s = int(float(_r.get("seed", 0) or 0))
        except Exception:
            _s = 0
        _by.setdefault(_a, {})[_s] = _f(
            _r, "stats_Objective_PaxPerDelayHr")
    _base = _by.get("NO_TSP", {})
    _base_mean = (sum(_base.values()) / len(_base)) if _base else 0.0
    print("\n%-34s %10s %10s %9s" % ("arm", "mean_obj", "vs_NO_TSP", "n"))
    for _a in sorted(_by):
        _vals = list(_by[_a].values())
        if not _vals:
            continue
        _m = sum(_vals) / len(_vals)
        _rel = (100.0 * (_m - _base_mean) / _base_mean
                if _base_mean > 0.0 else 0.0)
        print("%-34s %10.2f %+9.1f%% %9d"
              % (_a[:34], _m, _rel, len(_vals)))
except Exception as _e:
    print("Comprehensive summary failed:", repr(_e))
