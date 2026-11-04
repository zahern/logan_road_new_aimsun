"""
run_scats_pure.py -- curated sweep: the arms that WORK, plus tuning off the winner.

The 2026-10-22 31-arm sweep separated signal-tuning mechanisms cleanly:
  * WINNER: CHAMP_PAXDS_SPLIT (pax-relative DS + DS-equalising split, 2 s/cycle,
    +/-15% band, commissioned cycle/offsets/actuation untouched) = 136.3 vs
    NO_TSP 129.4 (+5.3%).
  * Everything that changed the CYCLE / master cycle / sequence / persistent
    flex collapsed (51-77), and the MP family (no split adaptation) sat at 52-55.
Those are dropped from this roster (definitions kept in champion_search).
See RETIRED below.

With the KG model open and AFTER A FULL Aimsun RESTART (engine.py +
specialized_modes.py are module-cached):

    import run_scats_pure

Writes a corridor-specific CSV next to champion_search.py:
  kg              -> test_5seed_kg.csv
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

# ── ROSTER -- winners + tuning off the winner (+ paired NO_TSP baseline) ──────
# NO_TSP is REQUIRED for a meaningful result (same seed, same demand, same build)
# and is run TWICE (warm-up + clean scored run, see ARMS below).
#
# RESULTS FROM THE 31-ARM SWEEP (2026-10-22, seed 300, NO_TSP = 129.4):
#   CHAMP_PAXDS_SPLIT      136.3   <- WINNER (kept + tuned below)
#   CHAMP_PAXDS_Q2         132.6
#   CHAMP_SCATS_EMU_SPLIT  129.4    (neutral control)
#   CHAMP_PBIL_GAME        126.3
#   CHAMP_PBIL_PRESS_H8    124.9
#   CHAMP_PBIL_PAX         122.8
#   CHAMP_PBIL_PRESS_PAX   122.5
#   CHAMP_PBIL             120.8
#   CHAMP_PBIL_PRESS        121.2
#
# RETIRED from this roster (still defined; restore by adding the name back):
#   cycle-changing / all-in  : EMU_CYCLE 61.9, EMU_FULL 51.6, PAXDS_CYCLE 121.6,
#                              PAXDS_FULL 51.4, PAXDS_NOPOGKF 51.4
#   persistent flex          : DSGATE_AGR 66.8, PAXDS_FLEX 76.3
#   MP family (no split)     : MP_SCATS 54.6, MP_NASH 54.1, MP_GAME 52.3
#   below NO_TSP / inert     : NASH 112.7, DSGATE 120.7, DSGATE_REL 120.7,
#                              DSGATE_PAX 107.9, ST_DSGATE 103.5, PAXDS_NOQ 104.9,
#                              PAXDS_REL 125.1, PAXDS_SELFGATE (byte-identical
#                              to the winner: no TSP actions to price)
#   needs verification       : PAXDS_POG (POG sampler/master-offset gate fixed
#                              after that sweep; re-test it in isolation first)
ROSTER = [
    # ── references ──
    "CHAMP_PBIL",                # plain split learner (120.8)
    "CHAMP_SCATS_EMU_SPLIT",     # SCATS strategic splits only (neutral control)
    "CHAMP_PAXDS_SPLIT",         # WINNER: pax DS + DS-equalising split
    "CHAMP_PAXDS_Q2",            # runner-up: more sensitive queue term
    "CHAMP_PBIL_GAME",           # PBIL + generalised-Nash bus TSP
    "CHAMP_PBIL_PAX",            # PBIL + pax DS
    "CHAMP_PBIL_PRESS",          # PBIL + predictive pressure (H=4)
    "CHAMP_PBIL_PRESS_PAX",      # predictive pressure + pax DS
    "CHAMP_PBIL_PRESS_H8",       # predictive pressure, 8-cycle horizon

    # ── TUNING OFF THE WINNER (CHAMP_PAXDS_SPLIT) -- one knob each ──
    "CHAMP_PAXWIN_M1",           # split move 1 s/cycle
    "CHAMP_PAXWIN_M4",           # split move 4 s/cycle
    "CHAMP_PAXWIN_B08",          # tighter +/-8% band
    "CHAMP_PAXWIN_B25",          # wider +/-25% band
    "CHAMP_PAXWIN_P2",           # pax cap 2.0 (weaker passenger weight)
    "CHAMP_PAXWIN_P6",           # pax cap 6.0 (stronger)
    "CHAMP_PAXWIN_PROP",         # proportional allocation
    "CHAMP_PAXWIN_BUS",          # winner + JIT extend + early recall
    "CHAMP_PAXWIN_PRESS",        # winner + predictive pressure (H=8)
    "CHAMP_PAXWIN_GAME",         # winner + Nash bus TSP
    "CHAMP_PAXWIN_DSGATE",       # winner + DS-gated CellQLearn TSP
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
# DESIGN SEED sweep: re-run the curated winners + the winner-tuning matrix on
# seed 300 (fast attribution). The 5-seed A/B for the game arm lives in
# run_paxwin_game_vs_notsp.py (RULE 3: never compare across seeds).
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
print("WINNERS + WINNER-TUNING vs NO_TSP -- corridor=%s" % _cs.CORRIDOR)
print("  %d arms x %d scored seeds %s" % (len(ARMS), len(_cs.EVAL_SEEDS),
                                          _cs.EVAL_SEEDS))
print("  -> %s" % OUT_CSV)
print("arms:", ", ".join(sorted(ROSTER)))
print("=" * 70)

_cs.main(arms=ARMS, results_csv=OUT_CSV, resume=False)
print("DONE ->", OUT_CSV)
