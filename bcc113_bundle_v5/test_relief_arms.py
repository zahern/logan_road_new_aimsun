"""
Quick head-to-head test: all new arms vs NO_TSP on Logan.
Run in Aimsun console AFTER FULL RESTART (module caching).

Usage (inside Aimsun):
    import test_relief_arms
    test_relief_arms.run()
"""
import os as _os
import sys as _sys

# Bootstrap so it works from console paste
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

# ── Subset: NO_TSP + all new arms (2 seeds only for speed) ──────────────
ARM_NAMES = {
    "NO_TSP",
    # A/B controls. NOTE (2026-10-14): CHAMP_CELLQ_STARVE_GATE and
    # CHAMP_CELLQ_STARVE_COST_OFF were DROPPED -- they are byte-identical to
    # CHAMP_CELLQ_NOGATE on KG (the net-benefit / starvation-cost gates are inert
    # here; proven in test_relief_vs_notsp + gate-inert analysis). NOGATE is kept
    # as the single learner baseline. Re-add them only for a SATURATED corridor
    # (Logan) where the gates can actually bind.
    "CHAMP_CELLQ_NOGATE",
    # Relief arms (cost + benefit)
    "CHAMP_CELLQ_MP_RELIEF",
    "CHAMP_CTM_MULTI_RELIEF",
    "CHAMP_MARL_RELIEF",
    "CHAMP_NASH_RELIEF",
    # Proactive arms (timetable-driven)
    "CHAMP_CELLQ_PROACTIVE",
    "CHAMP_MARL_PROACTIVE",
    "CHAMP_NASH_PROACTIVE",
    # Pure-state saturation relief (fused timetable + real-time ETA)
    "CHAMP_CELLQ_PURE_STATE",
    "CHAMP_MARL_PURE_STATE",
    "CHAMP_NASH_PURE_STATE",
    # Proactive variants
    "CHAMP_MARL_PROACTIVE",
    "CHAMP_NASH_PROACTIVE",
    # Pure-state saturation relief variants
    "CHAMP_MARL_PURE_STATE",
    "CHAMP_NASH_PURE_STATE",
    # CTM + relief
    "CHAMP_CTM_MULTI_RELIEF",
    # Live-cost / require-bus fixes (2026-10-13)
    "CHAMP_CELLQ_LIVECOST",
    "CHAMP_CELLQ_REQBUS",
    "CHAMP_CELLQ_LIVECOST_REQBUS",
    "CHAMP_NASH_LIVECOST_REQBUS",
    "CHAMP_MARL_LIVECOST_REQBUS",
    # Clean state-based / no-prearm
    "CHAMP_CELLQ_CLEAN",
    "CHAMP_CELLQ_NOPREARM",
    # SCATS degree-of-saturation arms (2026-10-14): test the SCATS mechanism
    # (balance measured per-approach DS) directly vs the analytic-delay ledger.
    "CHAMP_SCATS_DSGATE",     # DS-balance gate only (analytic gates off)
    "CHAMP_SCATS_DSPLAN",     # SCATS splits: retime the base plan toward equal DS
    "CHAMP_SCATS_FULL",       # DS gate + DS plan adapt
    "CHAMP_SCATS_DSSTATE",    # DS bin in the learner state (+ DS gate)
    "CHAMP_SCATS_SELFGATE",   # SCATS cost in the reward, NO external gate at all
    "CHAMP_THRU",             # reward = net people-through (no delay ledger)
    "CHAMP_THRU_BLEND",       # throughput + a little delay ledger
    "CHAMP_MULTIHEAD",        # two learned heads: priority + network throughput
    "CHAMP_MP_TRANSIT",       # transit-weighted MaxPressure (SCATS-like balancer)
}
ARMS = [a for a in _cs.ARMS if a["name"] in ARM_NAMES]
assert {a["name"] for a in ARMS} == ARM_NAMES, "missing: " + str(ARM_NAMES - {a["name"] for a in ARMS})

# Two eval seeds (fast). Aimsun runs every seed in ONE process, so a single
# train seed populates the learner Q-table in memory and the eval seeds then
# warm-start from it -- same design as the HPC sweep's train->eval split.
# WITHOUT a train seed the CELLQ arms cold-start (empty Q-table) and are not
# comparable to NO_TSP. MARL/NASH arms are analytic and ignore this.
_cs.EVAL_SEEDS = [300, 400]
_cs.TRAIN_SEEDS = [800]       # train first; eval seeds then warm-start
_cs.SCORED_SEEDS = list(_cs.EVAL_SEEDS)  # _cs.USE_TOPUP_SEEDS is False
_cs.USE_TOPUP_SEEDS = False
_cs.DEMAND_SCALARS = [1.0]

OUT_CSV = _os.path.join(_cs._ROOT, "test_relief_vs_notsp.csv")
print("=" * 70)
print("RELIEF ARMS vs NO_TSP  --  seeds 300,400  ->  %s" % OUT_CSV)
print("=" * 70)

_cs.main(arms=ARMS, results_csv=OUT_CSV, resume=False)
print("DONE ->", OUT_CSV)