"""run_paxwin_scats_state_vs_notsp.py -- one-file A/B launcher for Aimsun.

Executes the 5-seed NO_TSP / CHAMP_PAXWIN_SCATS_STATE batch (v2: SCATS cycle
clamped to model +/-15%, split share-change guard, startup offsets OFF) without
editing any constants. No warm-up run. Writes paxwin_scats_state_v4_seed400_vs_notsp.csv.

Run in the Aimsun console with the KG model open, AFTER a FULL Aimsun restart:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_paxwin_scats_state_vs_notsp.py").read())

Writes paxwin_scats_state_v4_seed400_vs_notsp.csv / .png beside the bundle.
"""
import importlib
import os as _os
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

_os.environ["PAXWIN_ARM"] = "CHAMP_PAXWIN_SCATS_STATE"
_os.environ["PAXWIN_OUT_CSV"] = _os.path.join(
    _HERE, "paxwin_scats_state_v4_seed400_vs_notsp.csv")
_os.environ["PAXWIN_WARMUP"] = "0"   # NO_TSP baseline + variant only
_os.environ["PAXWIN_SEEDS"] = "400"  # single-seed iteration

if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])

_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401  (runs the batch)

