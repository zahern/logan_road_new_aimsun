"""
run_scats_compare.py -- focused SCATS + GUARDS comparison vs NO_TSP.

Same shape as test_scats.py (a roster of arms x seeds, written to its own CSV)
but with two differences:

  1. It PICKS UP the other arms: the new objective-aligned guard arms
     (CHAMP_NETGATE / CHAMP_NETGATE_LOOSE) and the whole-signal RESTRUCTURE
     arms, on top of the SCATS DS-gate family and the bargain/CTM family.
  2. It UN-PARKS any roster arm. Several of these are in champion_search's
     PARKED_ARMS (the byte-identical cull), and main() skips parked arms -- so
     without this the run would be silently truncated to ~12 arms.

Edit ROSTER below to taste, then, with the KG model open and AFTER A FULL
Aimsun RESTART (module caching):

    import run_scats_compare

It writes a corridor-specific CSV next to champion_search.py:
  kg              -> test_scats_all_vs_nkgotsp.csv
  logan_road_new  -> test_scats_all_vs_notsp.csv
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

# ── ROSTER -- every arm you want in this comparison ───────────────────────────
ROSTER = {
    "NO_TSP",                       # baseline (same-seed comparison, required)

    # (a) NEW objective-aligned guards (2026-10-17) -- the reason for this run
    "CHAMP_NETGATE",                # NET_PAX_DELAY_GATE + MAIN_CORRIDOR_FLOOR, ratio 1.0
    "CHAMP_NETGATE_LOOSE",          # same, ratio 1.5 (looser break-even)

    # (b) NEW whole-signal restructure
    "CHAMP_SCATS_RESTRUCTURE",      # reorder + regroup, plan regime
    "CHAMP_SCATS_RESTRUCTURE_EXT",  # + GroupBasedController (External regime)

    # (b2) PURE SCATS: continuous SCATS re-timing, NO TSP action families, and
    #      bus-passenger-weighted saturation (DS_PAX_WEIGHTED) as the only bus
    #      effect. See champion_search.ARMS for the full flag set.
    "CHAMP_SCATS_PURE_PAX",

    # (b3) PURE SCOOT-RS: the TRL-SCOOT law -- regional critical-DS cycle,
    #      flow-proportional splits, green-wave offsets; NO TSP. Bus-free.
    "CHAMP_SCOOT_RS",

    # (c) SCATS DS-gate family (ceiling / adaptive variants)
    "CHAMP_SCATS_DSGATE",
    "CHAMP_SCATS_DSGATE_TIGHT",
    "CHAMP_SCATS_DSGATE_LOOSE",
    "CHAMP_SCATS_DSGATE_REL",
    "CHAMP_SCATS_DSGATE_REL_TIGHT",
    "CHAMP_SCATS_DSGATE_THRU",
    "CHAMP_SCATS_DSGATE_RESTRUCTURE",
    "CHAMP_SCATS_DSSTATE",
    "CHAMP_SCATS_DSPLAN",
    "CHAMP_SCATS_FULL",
    "CHAMP_SCATS_SELFGATE_THRU",

    # (d) other families for context
    "CHAMP_MULTIHEAD",
    "NASH_BARGAIN",
    "NASH_BARGAIN_THRU",
    "NASH_CTM",
    "DCTSP_BARGAIN_SPM",
    "CELLQ_CTM_COUPLED",
    "CHAMP_CTM_MULTI_RELIEF",
    "CHAMP_THRU",
}

ARMS = [a for a in _cs.ARMS if a["name"] in ROSTER]
_missing = ROSTER - {a["name"] for a in ARMS}
assert not _missing, "these ROSTER arms are not defined in champion_search.ARMS: " + str(_missing)

# Un-park every roster arm (main() skips PARKED_ARMS, which would silently
# drop the byte-identical-culled arms from this focused comparison).
_cs.PARKED_ARMS = set(_cs.PARKED_ARMS) - ROSTER

# ── Corridor guard (this run targets KG) ──────────────────────────────────────
# Set EXPECT_CORRIDOR=None to run whichever corridor model is open.
EXPECT_CORRIDOR = "kg"
if EXPECT_CORRIDOR and _cs.CORRIDOR != EXPECT_CORRIDOR:
    raise SystemExit(
        "Wrong corridor open: found %r, expected %r -- open the %s Aimsun model "
        "and re-run." % (_cs.CORRIDOR, EXPECT_CORRIDOR, EXPECT_CORRIDOR))

# ── Seeds / demand ────────────────────────────────────────────────────────────
# Scored seeds (every arm runs these; ranking uses ONLY these). Trimmed to 3
# eval x 2 train to cut runtime hard; still a paired per-seed comparison vs
# NO_TSP. Learner arms pre-train on TRAIN_SEEDS (Q accumulates, frozen at eval)
# then are scored on EVAL_SEEDS -- EVAL and TRAIN must stay DISJOINT.
# NOTE: KG NO_TSP seed 200 is dropped (run-order cold-start artifact: PaxEq ~93k
# vs ~185k on every other seed), so its paired ratios were meaningless.
# 100 runs = 24 arms x 3 eval + 14 learners x (3 eval + 2 train).
_cs.EVAL_SEEDS = [300, 500, 700]
_cs.TRAIN_SEEDS = [1100, 1200]
_cs.SCORED_SEEDS = list(_cs.EVAL_SEEDS)
_cs.USE_TOPUP_SEEDS = False
_cs.DEMAND_SCALARS = [1.0]

# ── Output CSV: corridor-specific so a KG run cannot clobber the Logan file ───
_OUT_NAME = {
    "kg": "test_scats_all_vs_nkgotsp.csv",
    "logan_road_new": "test_scats_all_vs_notsp.csv",
}.get(_cs.CORRIDOR, "test_scats_all_vs_%s.csv" % _cs.CORRIDOR)
OUT_CSV = _os.path.join(_cs._ROOT, _OUT_NAME)

print("=" * 70)
print("SCATS + GUARDS vs NO_TSP -- corridor=%s" % _cs.CORRIDOR)
print("  %d arms x %d scored seeds %s (+%d train seeds)"
      % (len(ARMS), len(_cs.EVAL_SEEDS), _cs.EVAL_SEEDS, len(_cs.TRAIN_SEEDS)))
print("  -> %s" % OUT_CSV)
print("arms:", ", ".join(sorted(ROSTER)))
print("=" * 70)

_cs.main(arms=ARMS, results_csv=OUT_CSV, resume=False)
print("DONE ->", OUT_CSV)
