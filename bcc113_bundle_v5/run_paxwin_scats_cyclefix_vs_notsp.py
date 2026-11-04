"""run_paxwin_scats_cyclefix_vs_notsp.py -- isolate the cycle-inflation fix.

Executes the 5-seed NO_TSP / CHAMP_PAXWIN_SCATS_CYCLEFIX batch. The ONLY change
vs the champion is the startup cycle clamp (model cycle +/-15%); the SCATS
share rewrite and the startup offsets are both OFF.

Run in the Aimsun console with the KG model open, AFTER a FULL Aimsun restart:

    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\run_paxwin_scats_cyclefix_vs_notsp.py").read())

Writes paxwin_scats_cyclefix_v2_seed400_vs_notsp.csv / .png beside the bundle.
"""
import importlib
import os as _os
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

_os.environ["PAXWIN_ARM"] = "CHAMP_PAXWIN_SCATS_CYCLEFIX"
_os.environ["PAXWIN_OUT_CSV"] = _os.path.join(
    _HERE, "paxwin_scats_cyclefix_v2_seed400_vs_notsp.csv")
_os.environ["PAXWIN_WARMUP"] = "0"   # NO_TSP baseline + variant only
_os.environ["PAXWIN_SEEDS"] = "400"  # single-seed iteration

# Aimsun caches imported modules for the process lifetime. Reload
# champion_search first, otherwise a session that imported it before the
# CYCLEFIX arm was added still has the old ARMS list and the assertion fires.
if "champion_search" in _sys.modules:
    importlib.reload(_sys.modules["champion_search"])

_MOD = "run_paxwin_game_vs_notsp"
if _MOD in _sys.modules:
    importlib.reload(_sys.modules[_MOD])
else:
    import run_paxwin_game_vs_notsp  # noqa: F401  (runs the batch)

