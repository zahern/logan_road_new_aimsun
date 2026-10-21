"""
Focused SCATS test: lean roster of the DS-gate winners + tuning variants vs NO_TSP.

Background (2026-10-16 first results, see scats-arms-first-results memory): the
SCATS DS-GATE arms were the only ones to BEAT NO_TSP cleanly on KG (lower delay
AND >= served); MP_TRANSIT starved worst (dropped); DS-PLAN / SCATS_FULL retiming
starved saturated Logan (excluded here). This test leans into the DS gate and
varies HOW it acts (ceiling tight/loose, gate+throughput, DS-in-state, multi-head)
so we can tune it. Small: 7 arms x 2 eval seeds (+1 train seed for the learners).

Run in Aimsun console AFTER A FULL RESTART (module caching):
    import test_scats
"""
import os as _os
import sys as _sys

# Bootstrap so it works from a console paste (mirrors test_relief_arms).
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

# ── Lean SCATS roster ─────────────────────────────────────────────────────────
# Keep NO_TSP (baseline) + the DS-gate family (the KG clean-winner) and the two
# other winners (DS-in-state, multi-head). DS-PLAN / SCATS_FULL / MP_TRANSIT are
# DELIBERATELY excluded: they starved (Logan retiming / transit-weight gridlock).
ARM_NAMES = {
    "NO_TSP",                      # baseline (required, same-seed comparison)
    # Ceilings calibrated to the MEASURED corridor DS (mean 1.80, max 2.00,
    # clamp 2.0). The old 0.85/0.90/0.95 were all below every observed DS, so the
    # three variants vetoed identically and the A/B was degenerate.
    "CHAMP_SCATS_DSGATE",          # lead: DS-balance gate, ceiling 1.70
    "CHAMP_SCATS_DSGATE_TIGHT",    # ceiling 1.40 -> gate bites sooner (acts less)
    "CHAMP_SCATS_DSGATE_LOOSE",    # ceiling 2.00 -> only at the clamp (acts more)
    # ADAPTIVE ceiling: no hand-picked DS number. The gate reads the junction's OWN
    # min..max DS spread each tick and vetoes when the conflicting approach sits in
    # the worse DS_REL_MARGIN fraction of it -- scale-free and self-tuning, so it
    # needs no re-calibration per corridor or demand level.
    "CHAMP_SCATS_DSGATE_REL",      # adaptive ceiling, margin 0.5
    "CHAMP_SCATS_DSGATE_REL_TIGHT",  # adaptive ceiling, margin 0.25 (stricter)
    "CHAMP_SCATS_DSGATE_THRU",     # DS gate + net-throughput reward (objective agrees)
    "CHAMP_SCATS_DSSTATE",         # DS-regime bin in the learner state (+ gate)
    # 2026-10-17: the ONLY SCATS mechanisms that actually ACT (rather than veto).
    # DS_PLAN_ADAPT retimes the base plan toward equal DS at rest -- without these
    # two arms the SCATS family could only ever remove actions, never change the
    # plan, so `plan_adapt_moves=0` in every previous run.
    "CHAMP_SCATS_DSPLAN",          # DS plan adapter only (retimes the plan)
    "CHAMP_SCATS_FULL",            # DS gate + DS plan adapter together
    "CHAMP_MULTIHEAD",             # priority head + net-throughput head
    # 2026-10-16: the convex SCATS self-gating cost + net-throughput objective,
    # previously written but never wired (`selfgate_cost applied=0` every run).
    # Now both live, gated behind DS_COST_IN_REWARD / THROUGHPUT_REWARD, with
    # SELF_GATE_RELIEF suppressing the external vetoes so the action is judged on
    # its own ledger. Its `[DS_TERMS]` should now show a non-zero
    # `selfgate_cost applied` / `sum=...paxs`.
    "CHAMP_SCATS_SELFGATE_THRU",   # self-gating cost + throughput, no external gate
    # 2026-10-16: the bargaining / CTM / Nash family (already in test_relief_arms).
    # NASH_BARGAIN = the real Nash game (coordination_algo NASH): plays the
    # net-surplus bargain p_T=0 / p_C=1, i.e. reduce TOTAL passenger delay most.
    # DCTSP_BARGAIN_SPM = the bargaining HEURISTIC (BARGAIN_SPM_MODE): trades signal
    # time against total system delay with a hard net-benefit veto.
    "NASH_BARGAIN",               # Nash structure: net-surplus bargain
    "DCTSP_BARGAIN_SPM",          # bargain between signal time and total delay
    # CTM cost models: single-cell analytic vs faithful multi-cell Daganzo.
    "CELLQ_CTM_COUPLED",          # single-cell CTM cross cost (uncoordinated)
    "NASH_CTM",                   # multi-cell CTM cross cost inside the Nash bargain
    "CHAMP_CTM_MULTI_RELIEF",     # multi-cell CTM reward + state + relief (learned)
    "CHAMP_THRU",                 # reward = net people put THROUGH (no delay ledger)
    # NASH_BARGAIN_THRU: the THROUGHPUT twin of NASH_BARGAIN -- identical Nash
    # structure but the bargaining surplus is net passengers DISCHARGED per cycle
    # (_net_pax_throughput_delta) instead of net delay saved, i.e. it bargains
    # signal time against how many people it can PUSH THROUGH.
    "NASH_BARGAIN_THRU",         # Nash bargain on throughput, not delay
}
ARMS = [a for a in _cs.ARMS if a["name"] in ARM_NAMES]
assert {a["name"] for a in ARMS} == ARM_NAMES, \
    "missing: " + str(ARM_NAMES - {a["name"] for a in ARMS})

# Five eval seeds + two train seeds (learners warm-start from the train seeds in
# the same process; without them the CELLQ arms cold-start and are not comparable).
_cs.EVAL_SEEDS = [200, 300, 400, 500, 600]
_cs.TRAIN_SEEDS = [700, 800]
_cs.SCORED_SEEDS = list(_cs.EVAL_SEEDS)
_cs.USE_TOPUP_SEEDS = False
_cs.DEMAND_SCALARS = [1.0]

OUT_CSV = _os.path.join(_cs._ROOT, "test_scats_vs_notsp.csv")
print("=" * 70)
print("SCATS FOCUS  --  %d arms x seeds 300,400  ->  %s"
      % (len(ARM_NAMES), OUT_CSV))
print("arms:", ", ".join(sorted(ARM_NAMES)))
print("=" * 70)

_cs.main(arms=ARMS, results_csv=OUT_CSV, resume=False)
print("DONE ->", OUT_CSV)
