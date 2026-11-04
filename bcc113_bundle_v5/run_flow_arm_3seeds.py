"""run_flow_arm_3seeds.py -- Flow-policy arm on the fixed plan, 3 seeds.

Requires a portable policy at kg/flow_policy.json (copy
kg/flow_policy.example.json to start). The policy is not trained by Aimsun;
it is the bridge for a Flow/SUMO/RLlib policy distilled to the JSON contract
in shared_tsp_engine/flow_policy.py. Without the file the arm falls back to
PBIL and logs [FLOW POLICY] no policy file.

Run in the Aimsun console after a full restart:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_flow_arm_3seeds.py").read())
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

_ARMS = ["CHAMP_FIXED_FLOW_RL"]
_OUT = _os.path.join(_HERE, "paxwin_flow_arm_3seeds.csv")

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
    print("FLOW-POLICY ARM, SEEDS 400/401/402")
    print("=" * 96)
    print("%-30s %6s %9s %10s %8s" % ("arm", "seed", "objective",
                                      "delay_h", "natGrn"))
    for _r in _rows:
        print("%-30s %6s %9.2f %10.1f %8.0f"
              % (str(_r.get("run_experiment", ""))[:30],
                 str(_r.get("run_seed", ""))[:6],
                 _f(_r, "stats_Objective_PaxPerDelayHr"),
                 _f(_r, "stats_TotalPassDelay_hrs"),
                 _f(_r, "stats_TSP_NaturalGreen")))
except Exception as _e:
    print("Flow-arm summary failed:", repr(_e))
