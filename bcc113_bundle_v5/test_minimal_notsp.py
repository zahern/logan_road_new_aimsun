"""
Minimal NO_TSP test - run in Aimsun console AFTER FULL RESTART
"""
import os as _os
import sys as _sys

# Bootstrap
_HERE = None
try:
    _HERE = _os.path.dirname(_os.path.abspath(__file__))
except Exception:
    _HERE = None
if not _HERE or not _os.path.isfile(_os.path.join(_HERE, "champion_search.py")):
    _HERE = _os.path.abspath(_os.getcwd())
if not _os.path.isfile(_os.path.join(_HERE or "", "champion_search.py")):
    try:
        from PyANGKernel import GKSystem
        _d = _os.path.abspath(str(GKSystem.getSystem().getActiveModel().getDocumentDirectory().absolutePath()))
        for _ in range(6):
            if _os.path.isfile(_os.path.join(_d, "champion_search.py")):
                _HERE = _d
                break
            _d = _os.path.dirname(_d)
    except Exception:
        pass
if _HERE and _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

import champion_search as _cs
import os as _os

# Minimal: just NO_TSP, 1 seed
_cs.ARMS = [a for a in _cs.ARMS if a["name"] == "NO_TSP"]
_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []
_cs.SCORED_SEEDS = [300]
_cs.USE_TOPUP_SEEDS = False
_cs.DEMAND_SCALARS = [1.0]

OUT_CSV = _os.path.join(_cs._ROOT, "test_minimal_notsp.csv")
print("Running minimal NO_TSP test...")
_cs.main(arms=_cs.ARMS, results_csv=_os.path.join(_cs._ROOT, "test_minimal_notsp.csv"), resume=False)
print("DONE")