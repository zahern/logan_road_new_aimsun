"""
run_scats_demandshift.py -- the OFF-DESIGN demand test.

The model's commissioned plan IS the tuned SCATS plan for the ~1.0x AM-peak hour,
so on that design demand a real-time controller can at best MATCH it (re-deriving a
tuned plan from crude detection only adds noise). Adaptive control earns its keep
when demand moves AWAY from what the fixed plan was tuned for: at higher demand the
fixed plan can't manage the queues it was never designed for, but an adaptive
controller can lengthen cycles and rebalance splits toward the saturated approaches.

This runs the key arms across a UNIFORM demand sweep (set_demand_scalar scales all
18 GKTrafficDemand objects). Read the result as a DELTA vs NO_TSP AT EACH SCALAR:
  * ~1.0x  -> adaptive should ~TIE NO_TSP (nothing to win on the design plan)
  * >1.0x  -> adaptive should BEAT NO_TSP (queue management the fixed plan can't do)
If an adaptive arm beats NO_TSP at 1.2-1.3x, that's the real, defensible win.

(A DIRECTIONAL side-street surge would be a stronger test but needs per-OD-matrix
scaling in the Aimsun GUI; this uniform over-saturation sweep is the off-design
condition the batch machinery can drive reliably.)

Run with the KG model open, AFTER A FULL Aimsun RESTART:
    import run_scats_demandshift
Writes test_demandshift_kg.csv (has a run_demand_scalar column -- pivot on it).
"""
import os as _os
import sys as _sys

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
        _d = _os.path.abspath(str(
            GKSystem.getSystem().getActiveModel()
            .getDocumentDirectory().absolutePath()))
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

# ── ROSTER: the baseline + the two redesigned adaptive arms + the INITPLAN
# reference (machinery measuring, writing nothing -> must track NO_TSP; proves the
# control loop itself is not corrupting the plan). Keep it small -- each arm runs
# once PER demand scalar, so N arms x M scalars x K seeds simulations.
ROSTER = {
    "NO_TSP",                 # fixed commissioned plan (the tuned SCATS plan)
    "CHAMP_INITPLAN",         # reference: measures, writes nothing (should = NO_TSP)
    "CHAMP_SCATS_FAITHFUL",   # gentle nudge of commissioned (per-movement DS)
    "CHAMP_SCATS_ADAPTIVE",   # Webster seed + real-time cycle (per-movement DS)
}
# Add CHAMP_MAXPRESSURE / CHAMP_MP_NASH here too if you want them in the sweep.

ARMS = [a for a in _cs.ARMS if a["name"] in ROSTER]
_missing = ROSTER - {a["name"] for a in ARMS}
assert not _missing, (
    "these ROSTER arms are not defined in champion_search.ARMS: " + str(_missing))
_cs.PARKED_ARMS = set(_cs.PARKED_ARMS) - ROSTER

# SAFETY: make the demand scalar hit ALL KG GKTrafficDemand matrices (the default
# TARGET_DEMAND_NAMES filter is named for Logan and would match zero KG matrices,
# silently scaling nothing). None = match all -> the sweep actually changes demand.
try:
    _cs._br.TARGET_DEMAND_NAMES = None
except Exception:
    pass

EXPECT_CORRIDOR = "kg"
if EXPECT_CORRIDOR and _cs.CORRIDOR != EXPECT_CORRIDOR:
    raise SystemExit(
        "Wrong corridor open: found %r, expected %r -- open the %s Aimsun model "
        "and re-run." % (_cs.CORRIDOR, EXPECT_CORRIDOR, EXPECT_CORRIDOR))

# ── Seeds / demand SWEEP ──────────────────────────────────────────────────────
# One seed keeps it fast; the SAME seed is reused at every scalar so the only
# thing changing is the demand level (RULE 3: compare vs NO_TSP at the SAME seed
# AND the SAME scalar). The DELTA vs NO_TSP is what matters at each level.
_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []
_cs.SCORED_SEEDS = list(_cs.EVAL_SEEDS)
_cs.USE_TOPUP_SEEDS = False
# Design demand + two moderate over-saturation levels. If 1.3x gridlocks EVERY
# arm (no winner), pull it down to 1.15/1.2; if nothing is stressed at 1.2, push
# up. The win shows up where NO_TSP degrades but the adaptive arm holds.
_cs.DEMAND_SCALARS = [1.0, 1.2, 1.3]

_OUT_NAME = {
    "kg": "test_demandshift_kg.csv",
    "logan_road_new": "test_demandshift_logan.csv",
}.get(_cs.CORRIDOR, "test_demandshift_%s.csv" % _cs.CORRIDOR)
OUT_CSV = _os.path.join(_cs._ROOT, _OUT_NAME)

print("=" * 72)
print("OFF-DESIGN DEMAND SWEEP -- adaptive vs fixed as demand leaves the tuned "
      "plan. corridor=%s" % _cs.CORRIDOR)
print("  arms   : %s" % ", ".join(sorted(ROSTER)))
print("  seed   : %s" % _cs.EVAL_SEEDS)
print("  scalars: %s  (%d runs total)"
      % (_cs.DEMAND_SCALARS, len(ARMS) * len(_cs.DEMAND_SCALARS) * len(_cs.EVAL_SEEDS)))
print("  -> %s   (pivot on run_demand_scalar; read DELTA vs NO_TSP per scalar)" % OUT_CSV)
print("=" * 72)

_cs.main(arms=ARMS, results_csv=OUT_CSV, resume=False)
print("DONE ->", OUT_CSV)
