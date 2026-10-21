"""
run_core_pipeline.py -- the CORE pipeline: ONE canonical arm per DISTINCT decider
algorithm (no flag-variants, no ablations), scored against NO_TSP across the eval
seeds, with the cheat-proof AvgPassDelay_inclVQ metric written per run.

Each arm below is a DIFFERENT decider function (see inspect_methodologies.py / the
strategy audit). Variants that only toggle flags on the SAME decider
(CELLQLEARN_GATED/_FORCED/_SAFE, CELLQ_VDET_*/_BUSSPLIT, MAXPRESSURE_LB,
ZIGDOG_QP_*/ZIGCTM, NASH_UTILITARIAN/_REAL/_CAL, the *_BUSx*/_Dx*/_TIMES/_SWAPS
sweeps) are deliberately EXCLUDED -- run those separately when tuning a chosen core.

CORE ARMS (decider in brackets):
  NO_TSP               [fixed-time baseline]
  DCTSP_ZIG            [dctsp_zig            -- shockwave-optimal bus-triggered]
  ZIGDOG               [dctsp_zigdog         -- receding-horizon arrivals-on-green]
  ZIGDOG_Q             [dctsp_zigdog_q       -- Q-learning over ZIGDOG's actions]
  CELLQLEARN           [dctsp_bxt            -- CTM multiagent Q-learning (BXT)]
  CELLQ_LEARN_UNCOORD  [dctsp_cellqlearn_corridor -- corridor-demand CTM learner]
  CELLQ_CTM_COUPLED    [dctsp_cellqlearn_corridor -- + CTM corridor coupling (A/B)]
  CELLQ_CTM_REWARD     [dctsp_cellqlearn_corridor -- + multicell CTM reward cost (A/B)]
  DCTSP_MP_ECTM        [dctsp_mp_ectm        -- CTM MaxPressure / CTMGS]
  DCTSP_BARGAIN_SPM    [dctsp_bargain        -- SPM bargaining]
  NASH_BARGAIN         [dctsp_nash_bargain   -- Nash product game, analytic cross cost]
  NASH_CTM             [dctsp_nash_bargain   -- Nash + multi-cell CTM cross cost (A/B)]
  MAXPRESSURE_FIX      [dctsp_maxpressure_fix  -- fixed-cycle MaxPressure]
  MAXPRESSURE_FLEX     [dctsp_maxpressure_flex -- flexible MaxPressure]
  DCTSP_MARL_RL        [dctsp_cpdql          -- CPDQL deep-ish RL]
  CENTRALISED          [dctsp_centralised    -- centralised decider]
  DCTSP_MARL           [reward-TSP           -- MARL reward-weighting heuristic]
  MILP_MPC             [reward-TSP           -- model-predictive (needs a solver)]

RUN inside Aimsun (corridor model open):
    run_core_pipeline.py
-> run_core_pipeline_<corridor>.csv

If the auto-picked replication is refused, set it below (see header of
run_full_pipeline.py for the override lines).
"""

import os as _os
import sys as _sys_cp
import importlib.util as _ilu


def _find_bundle_dir():
    _c = []
    try:
        _c.append(_os.path.dirname(_os.path.abspath(__file__)))
    except (NameError, TypeError):
        pass
    if not _c or not _os.path.isfile(_os.path.join(_c[0], "champion_search.py")):
        try:
            from PyANGKernel import GKSystem
            _md = (GKSystem.getSystem().getActiveModel()
                   .getDocumentDirectory().absolutePath())
            _c.extend((_md, _os.path.dirname(_md), _os.path.dirname(_os.path.dirname(_md))))
        except Exception:
            pass
    for _x in _c:
        _x = _os.path.abspath(_x)
        if _os.path.isfile(_os.path.join(_x, "champion_search.py")):
            return _x
    raise RuntimeError("run_core_pipeline.py: cannot find champion_search.py; "
                       "run from Aimsun with the bundle model open.")


_HERE = _find_bundle_dir()
if _HERE not in _sys_cp.path:
    _sys_cp.path.insert(0, _HERE)
for _mn in ("champion_search", "_br_champ"):
    _sys_cp.modules.pop(_mn, None)
_cs_path = _os.path.join(_HERE, "champion_search.py")
_spec = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec)
_sys_cp.modules["champion_search"] = _cs
_spec.loader.exec_module(_cs)

# ── Replication override (leave auto-pick ON) ──────────────────────────────────
# NOTE: the 75206/75207/75210 in result-folder names are NOT replication ids
# (REPLICATION_ID=75206 => "not found"). Auto-pick DOES find a runnable replication
# (it loaded + ran). The real problem is the sim terminating at ~1.6s (see below),
# which is a model DURATION issue, not the pick. Only set REPLICATION_NAME to the
# exact name you Play in the GUI if auto-pick refuses outright.
# _cs._br.REPLICATION_NAME = "Replication 1 560 - TSP1"

# ── Seeds: the five champion eval seeds (paired NO_TSP per seed). Learners also
# train on champion_search.TRAIN_SEEDS automatically. Trim to [300,400] for a
# faster smoke. ────────────────────────────────────────────────────────────────
SEEDS = [300, 400, 500, 600, 700]
_cs.EVAL_SEEDS = list(SEEDS)
_cs.SCORED_SEEDS = list(SEEDS)
_cs.USE_TOPUP_SEEDS = False

# ── CORE set: one canonical arm per distinct decider ───────────────────────────
# ORDER (2026-10-06): HIGH-VALUE arms front-loaded so they BANK results before the
# slow/fragile learners. ZIGDOG_Q froze Aimsun mid-run (t=802, needed a manual
# restart) and derailed the whole batch twice -- with the arms we care about sitting
# at the end, we lost them both times. NO_TSP stays first (it's the comparison
# baseline every arm is scored against); then the KG winner + the paired A/Bs
# (kept adjacent); the lower-priority and crash-prone arms run LAST so a late
# failure costs a throwaway arm, not the ones that matter.
CORE = [
    "NO_TSP",                 # baseline -- MUST stay first (scored against by all)
    # ── high-value, front-loaded ──
    "DCTSP_MP_ECTM",          # KG winner; non-learner (fast)
    "CELLQ_LEARN_UNCOORD",    # CELLQ A/B baseline
    "CELLQ_CTM_COUPLED",      # + CTM corridor coupling
    "CELLQ_CTM_REWARD",       # + multicell CTM reward cost
    "NASH_BARGAIN",           # NASH A/B baseline
    "NASH_CTM",               # + CTM cross cost
    "CELLQLEARN",             # other CELLQ learner
    # ── remaining arms (lower priority) ──
    "DCTSP_ZIG",
    "DCTSP_BARGAIN_SPM",
    "MAXPRESSURE_FIX",
    "MAXPRESSURE_FLEX",
    "DCTSP_MARL_RL",
    "DCTSP_MARL",
    "ZIGDOG",
    "ZIGDOG_Q",               # froze Aimsun at t=802 -- run LAST
    "CENTRALISED",            # parked (inert)
    "MILP_MPC",               # parked (inert)
]

_by_name = {a["name"]: a for a in _cs.ARMS}
_arms = [_by_name[n] for n in CORE if n in _by_name]
_missing = [n for n in CORE if n not in _by_name]
_results_csv = _os.path.join(_cs._ROOT, f"run_core_pipeline_{_cs.CORRIDOR}.csv")

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 72)
    _log(f"CORE PIPELINE -- corridor={_cs.CORRIDOR} | {len(_arms)} core arms "
         f"x {len(SEEDS)} eval seeds")
    _log(f"  arms: {[a['name'] for a in _arms]}")
    if _missing:
        _log(f"  WARNING not found in champion_search.ARMS -> {_missing}")
    _log(f"  results -> {_results_csv}")
    _log("  score on AvgPassDelay_inclVQ_s (cheat-proof) + Objective_PaxPerDelayHr.")
    _log("=" * 72)
    _cs.main(arms=_arms, results_csv=_results_csv)
