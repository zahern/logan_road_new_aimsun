"""
run_scats_pure.py -- focused test of ONE arm: CHAMP_SCATS_PURE_PAX vs NO_TSP.

This is run_scats_compare.py trimmed to a single experimental arm, so the
pure-SCATS (bus-pax-weighted saturation, NO TSP action family) behaviour can be
inspected on its own without the other 23 arms in the CSV.

Edit ROSTER / seeds below to taste, then, with the KG model open and AFTER A FULL
Aimsun RESTART (engine.py + specialized_modes.py are module-cached):

    import run_scats_pure

Writes a corridor-specific CSV next to champion_search.py:
  kg              -> test_scats_pure_kg.csv
  logan_road_new  -> test_scats_pure_logan.csv
"""
import os as _os
import sys as _sys

# ── Bootstrap: find the bundle root even when pasted into the console ─────────
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

# ── ROSTER -- the arm under test (+ its paired NO_TSP baseline) ───────────────
# NO_TSP is REQUIRED for a meaningful result (same-seed, same-demand, same-build
# comparison -- RULE 3) and is run TWICE (see ARMS below).
# FOCUSED ROSTER (2026-10-21): lean into what performed best on the 1-seed run and
# combine the winning mechanisms. The three best arms all HOLD the commissioned
# cycle + offsets and differ only in add-ons; the losers (SCATS_FAITHFUL/ADAPTIVE/
# POG adapt the cycle -> break coordination; MAXPRESSURE/MP_NASH deadlock) are
# PARKED (just dropped from this roster -- their defs stay in champion_search).
# ROSTER (2026-10-21): the goal is to BEAT NO_TSP. The PURE_SCATS re-timing arms
# can't on the design hour (best, PBIL, = 748 vs 638). The arms that DID beat it
# (2026-10-16: -4% delay, +1.9% served) were the DS-GATE family -- they KEEP the
# commissioned plan and fire DS-GATED bus TSP (veto a priority action when the
# conflicting approach is too saturated), so they add transit benefit WITHOUT
# re-timing / breaking coordination. Un-parked + swept here. CHAMP_INITPLAN dropped
# (byte-identical to NO_TSP -- no information). PBIL + NASH kept as references.
# SINGLE-SEED SEARCH ROSTER (2026-10-21): find an arm that beats NO_TSP, then
# re-validate the winner on 5 seeds. Core idea = faithful gradual SCATS solver +
# bus-TSP flavours fired only when DS/net-benefit/JIT gates pass.
ROSTER = [
    # ── references ──
    "CHAMP_PBIL",                # best PURE_SCATS split arm (748)
    "NASH_BARGAIN",              # plan untouched + discrete bus TSP (837)
    "CHAMP_SCATS_DSGATE",        # proven DS-gate winner (CELLQLEARN, DS_MAX=1.70)
    "CHAMP_SCATS_DSGATE_REL",    # DS-gate, adaptive scale-free ceiling
    "CHAMP_ST_DSGATE",           # SCATS solver + DS-gated GE/INS (BXT)
    # ── MAXPRESSURE emulating SCATS (pressure-proportional splits, banded) ──
    "CHAMP_MP_SCATS",            # MP FIX: split commissioned cycle ~ pressure,
                                 # green phases only, +/-25% commissioned band
    # ── MP-SCATS + GAME-THEORY TSP OVERRIDE ──
    "CHAMP_MP_NASH_SCATS",       # MP-SCATS splits + NASH bargaining bus TSP override
    "CHAMP_MP_GAME_SCATS",       # MP-SCATS splits + THROUGHPUT game (maximise system
                                 # net-passenger reward) + bus TSP override
]

_ARM_BY_NAME = {a["name"]: a for a in _cs.ARMS}
_missing = set(ROSTER) - set(_ARM_BY_NAME)
assert not _missing, "these ROSTER arms are not defined in champion_search.ARMS: " + str(_missing)

# NO_TSP is run TWICE: the first run absorbs the network warm-up / model-load
# transient (the "first run is not a full run" issue), the second is the clean
# scored baseline. A distinct experiment name keeps the two result rows apart.
_NOTSP = _ARM_BY_NAME["NO_TSP"]
_NOTSP_WARMUP = dict(_NOTSP, name="NO_TSP_WARMUP")
ARMS = [_NOTSP_WARMUP, _NOTSP] + [_ARM_BY_NAME[n] for n in ROSTER]

# Un-park roster arms (main() skips PARKED_ARMS).
_cs.PARKED_ARMS = set(_cs.PARKED_ARMS) - set(
    ["NO_TSP", "NO_TSP_WARMUP"] + list(ROSTER))

# ── Corridor guard (this run targets KG) ──────────────────────────────────────
EXPECT_CORRIDOR = "kg"
if EXPECT_CORRIDOR and _cs.CORRIDOR != EXPECT_CORRIDOR:
    raise SystemExit(
        "Wrong corridor open: found %r, expected %r -- open the %s Aimsun model "
        "and re-run." % (_cs.CORRIDOR, EXPECT_CORRIDOR, EXPECT_CORRIDOR))

# ── Seeds / demand ────────────────────────────────────────────────────────────
# SINGLE SEED (2026-10-21): fast iteration to FIND an arm that beats NO_TSP, then
# re-validate the winner on the 5-seed set (RULE 3) before trusting it. The
# NO_TSP_WARMUP throwaway still runs ONCE first to warm the passage counters, so
# the scored seed is clean. Seed 300 = the design seed.
_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []
_cs.SCORED_SEEDS = list(_cs.EVAL_SEEDS)
_cs.USE_TOPUP_SEEDS = False
_cs.DEMAND_SCALARS = [1.0]

# ── Output CSV: corridor-specific ─────────────────────────────────────────────
_OUT_NAME = {
    "kg": "test_5seed_kg.csv",
    "logan_road_new": "test_scats_pure_logan.csv",
}.get(_cs.CORRIDOR, "test_scats_pure_%s.csv" % _cs.CORRIDOR)
OUT_CSV = _os.path.join(_cs._ROOT, _OUT_NAME)

print("=" * 70)
print("PURE-SCATS / PURE-SCOOT (bus-free, NO TSP actions) vs NO_TSP -- corridor=%s"
      % _cs.CORRIDOR)
print("  %d arms x %d scored seeds %s" % (len(ARMS), len(_cs.EVAL_SEEDS),
                                          _cs.EVAL_SEEDS))
print("  -> %s" % OUT_CSV)
print("arms:", ", ".join(sorted(ROSTER)))
print("=" * 70)

_cs.main(arms=ARMS, results_csv=OUT_CSV, resume=False)
print("DONE ->", OUT_CSV)
