"""
Validate the per-seed path/route REUSE (REUSE_PATHS_PER_SEED) does NOT change the
simulation -- so a reused sweep is trustworthy.

Method: run NO_TSP at ONE seed three times in this Aimsun session:
  1. baseline  -- reuse OFF (full trip-gen + SRC)
  2. prime     -- reuse ON, first run of the seed (stores the route forest)
  3. reuse     -- reuse ON, second run of the seed (restores + disables SRC)
NO_TSP takes no TSP actions, so runs 1 and 3 must be identical EXCEPT for the
reuse mechanism. If delay AND served-pax match within tolerance, reuse is safe to
enable for the real sweep; if they diverge, the route-fixing is changing behaviour
and REUSE_PATHS_PER_SEED must stay OFF.

Run in Aimsun console AFTER A FULL RESTART:
    import validate_path_reuse
"""
import os as _os
import sys as _sys
import csv as _csv

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

# Resolve the batch_runner this corridor uses (kg or logan) via champion_search.
_br = getattr(_cs, "_br", None)
if _br is None:
    import importlib as _il
    _br = _il.import_module("batch_runner")

SEED = 300
TOL_PCT = 1.0   # delay / served must match within this % to pass

_cs.EVAL_SEEDS = [SEED]
_cs.TRAIN_SEEDS = []            # NO_TSP is not a learner -> no train needed
_cs.SCORED_SEEDS = [SEED]
_cs.USE_TOPUP_SEEDS = False
_cs.DEMAND_SCALARS = [1.0]

_ARMS = [a for a in _cs.ARMS if a["name"] == "NO_TSP"]
assert _ARMS, "NO_TSP arm not found"


def _kpi(csv_path):
    try:
        rows = list(_csv.DictReader(open(csv_path)))
    except Exception:
        return None
    if not rows:
        return None
    r = rows[-1]
    def _g(*names):
        for n in names:
            if n in r and r[n] not in (None, ""):
                try:
                    return float(r[n])
                except Exception:
                    pass
        return None
    return (_g("stats_TotalPassDelay_hrs", "TotalPassDelay_hrs"),
            _g("stats_PaxEquivPassages", "PaxEquivPassages"))


def _run(tag, reuse_on):
    _br.REUSE_PATHS_PER_SEED = bool(reuse_on)
    out = _os.path.join(_cs._ROOT, f"validate_reuse_{tag}.csv")
    print("=" * 70)
    print(f"[VALIDATE] {tag}: NO_TSP seed={SEED} REUSE_PATHS_PER_SEED={reuse_on} -> {out}")
    print("=" * 70)
    _cs.main(arms=_ARMS, results_csv=out, resume=False)
    return _kpi(out)


# 1) baseline (reuse off). 2) prime (reuse on, stores). 3) reuse (reuse on, restores).
_base = _run("baseline", False)
_prime = _run("prime", True)     # primes the seed's stored forest
# Confirm the prime actually stuck (module not reloaded between runs) -- otherwise
# the "reuse" run would silently re-prime and give a FALSE pass.
_primed_ok = SEED in (getattr(_br, "_PATH_FOREST_CACHE", {}) or {})
if not _primed_ok:
    print(f"[VALIDATE] WARNING: seed {SEED} not in _br._PATH_FOREST_CACHE after "
          f"prime -- the forest was not captured (module reload, or getPathsForest "
          f"returned None), so the reuse run cannot reuse. Verdict will be "
          f"INCONCLUSIVE; check the [PATH-REUSE] log lines.")
_reuse = _run("reuse", True)     # should now restore + skip SRC

print("\n" + "=" * 70)
print("[VALIDATE] RESULT  (delay_hrs, served_pax)")
print(f"  baseline (reuse OFF): {_base}")
print(f"  reuse    (reuse ON) : {_reuse}")
if not _primed_ok:
    print("  VERDICT: INCONCLUSIVE -- prime did not persist (see WARNING above); "
          "reuse was not actually exercised.")
elif not _base or not _reuse or _base[0] is None or _reuse[0] is None:
    print("  VERDICT: INCONCLUSIVE -- missing KPIs (check the runs completed)")
else:
    _dd = abs(_reuse[0] - _base[0]) / max(_base[0], 1e-9) * 100.0
    _ds = abs(_reuse[1] - _base[1]) / max(_base[1], 1e-9) * 100.0
    print(f"  delay diff={_dd:.2f}%  served diff={_ds:.2f}%  (tol {TOL_PCT}%)")
    if _dd <= TOL_PCT and _ds <= TOL_PCT:
        print("  VERDICT: PASS -- reuse preserves the sim; safe to enable "
              "REUSE_PATHS_PER_SEED for the sweep.")
    else:
        print("  VERDICT: FAIL -- reuse CHANGES the sim; keep REUSE_PATHS_PER_SEED "
              "OFF (route-fixing alters behaviour).")
print("=" * 70)
