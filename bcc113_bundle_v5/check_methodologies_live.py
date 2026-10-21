"""
check_methodologies_live.py -- LIGHTWEIGHT in-Aimsun smoke that runs ONE arm per
methodology for a single seed and reports PER-MODE ACTION COUNTS, so you can see at
a glance which deciders actually FIRE vs sit silently at all-NO_ACTION (the
"CELLQLEARN == NO_TSP byte-identical / learner inert" class of problem).

It picks ONE representative arm per distinct `method` in champion_search.ARMS (so
every methodology is exercised once, not all 28 arms), runs seed 300 only, then
reads the result CSV and prints, per arm:
    extensions | early-reds | phase-skips | detected-but-NO_ACTION | verdict
Verdict: ALIVE (fired >0 actions) / INERT (0 actions despite detections) /
BASELINE (NO_TSP) / NO-DETECT (no buses detected -- inconclusive).

This is the LIVE companion to inspect_methodologies.py (which statically checks the
wiring). Static says "it will dispatch"; this says "it actually acted".

RUN inside Aimsun (corridor model open):
    check_methodologies_live.py
-> check_methodologies_live_<corridor>.csv  + console/report

SHORT WINDOW: this runs whatever replication is selected for its full duration. For
a genuinely short smoke, point it at a short replication via the override below, or
shorten the replication's duration in the Aimsun GUI. One seed x ~12 methodologies
is already far lighter than the full 45-run sweep.
"""

import os as _os
import sys as _sys_ml
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
    raise RuntimeError("check_methodologies_live.py: cannot find champion_search.py; "
                       "run from Aimsun with the bundle model open.")


_HERE = _find_bundle_dir()
if _HERE not in _sys_ml.path:
    _sys_ml.path.insert(0, _HERE)
for _mn in ("champion_search", "_br_champ"):
    _sys_ml.modules.pop(_mn, None)
_cs_path = _os.path.join(_HERE, "champion_search.py")
_spec = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec)
_sys_ml.modules["champion_search"] = _cs
_spec.loader.exec_module(_cs)

# ── Replication override (same model has many replications). Uncomment to force
# the one you run with Play in the GUI if the auto-pick is refused: ─────────────
# _cs._br.REPLICATION_NAME = "Replication 1 560 - TSP1"
# _cs._br.REPLICATION_ID = 11129240

# ── one seed, lightweight ───────────────────────────────────────────────────────
SEEDS = [300]
_cs.EVAL_SEEDS = list(SEEDS)
_cs.SCORED_SEEDS = list(SEEDS)
_cs.USE_TOPUP_SEEDS = False

# mode-toggle -> decider tag (from engine _mode_registry); used so arms that share
# a `method` label but dispatch to DIFFERENT deciders are each covered once.
_MODE_TO_DECIDER = {
    "DCTSP_ZIG_MODE": "ZIG", "MP_ECTM_MODE": "MP_ECTM", "MP_ECTM_DP_MODE": "MP_ECTM_DP",
    "BXT_MODE": "BXT", "BXT_CORRIDOR_MODE": "CELLQ_CORRIDOR",
    "ZIGDOG_MODE": "ZIGDOG", "ZIGDOG_Q_MODE": "ZIGDOG_Q", "CPDQL_MODE": "CPDQL",
    "CELLQLEARN_DP_MODE": "CELLQLEARN_DP", "BARGAIN_SPM_MODE": "BARGAIN",
    "MAXPRESSURE_FIX_MODE": "MAXPRESSURE_FIX", "MAXPRESSURE_FLEX_MODE": "MAXPRESSURE_FLEX",
    "HYBRID_MP_MODE": "HYBRID_MP", "NASH_GATE_MODE": "NASH_GATE",
    "NASH_BARGAIN_MODE": "NASH_BARGAIN", "MILP_TSP_MODE": "MILP_TSP",
    "CENTRALIZED_MODE": "CENTRALISED",
}

def _decider_key(arm):
    ov = arm.get("reward_overrides", {}) or {}
    for flag, tag in _MODE_TO_DECIDER.items():
        if ov.get(flag) is True:
            return tag
    if str(arm.get("strategy")) == "NORMAL":
        return "NORMAL"
    return "reward-TSP"   # run_reward_tsp / Pareto path (e.g. DCTSP_MARL)

# ── pick ONE arm per distinct DECIDER, NO_TSP first ─────────────────────────────
def _select_one_per_method(all_arms):
    seen = set(); picked = []
    for a in all_arms:
        if a.get("name") == "NO_TSP":
            picked.append(a); seen.add(_decider_key(a)); break
    for a in all_arms:
        if str(a.get("strategy")) == "MILP_MPC":
            continue  # needs a solver backend; champion_search auto-skips it
        k = _decider_key(a)
        if k in seen:
            continue
        seen.add(k); picked.append(a)
    return picked


_arms = _select_one_per_method(list(_cs.ARMS))
_results_csv = _os.path.join(_cs._ROOT, f"check_methodologies_live_{_cs.CORRIDOR}.csv")


def _results_dirs():
    """Where SimulationStats writes <run>/simulation_results.csv."""
    out = []
    for d in (_os.path.join(_HERE, _cs.CORRIDOR, "results"),
              _os.path.join(_HERE, "results"),
              _os.path.join(getattr(_cs, "PROJECT_DIR", "") or "", "results")):
        if d and _os.path.isdir(d) and d not in out:
            out.append(d)
    return out

def _latest_results_row(arm_name):
    """Newest simulation_results.csv for this arm (reads the REAL per-run stats
    from kg/results/, not the champion CSV which the launcher leaves blank when
    completion-detection misses)."""
    import csv, glob
    best = None; best_t = -1.0
    for base in _results_dirs():
        for f in glob.glob(_os.path.join(base, arm_name + "_seed*", "simulation_results.csv")):
            try:
                t = _os.path.getmtime(f)
            except Exception:
                continue
            if t > best_t:
                best_t = t; best = f
    if not best:
        return None, None
    try:
        rows = list(csv.DictReader(open(best, encoding="utf-8", errors="replace")))
        return (rows[-1] if rows else None), best
    except Exception:
        return None, best

def _report():
    def g(r, *cands):
        for c in cands:
            if r and c in r:
                try: return float(r[c])
                except Exception: return 0.0
        return 0.0
    lines = []
    lines.append("=" * 90)
    lines.append("[LIVE-CHECK] per-methodology action counts (reads kg/results/*/simulation_results.csv)")
    lines.append("=" * 90)
    lines.append("  %-22s %5s %4s %4s %4s %6s %8s  %-9s" %
                 ("arm", "seed", "EXT", "ER", "SKIP", "NOACT", "obj", "verdict"))
    n_alive = n_inert = n_missing = 0
    for a in _arms:
        name = a.get("name", "?")
        r, path = _latest_results_row(name)
        if r is None:
            lines.append("  %-22s  (no simulation_results.csv found)" % name)
            n_missing += 1
            continue
        import re as _re2
        _sm = _re2.search(r"_seed(\d+)_", path or "")
        seed = _sm.group(1) if _sm else r.get("Seed", r.get("seed", "?"))
        ext = g(r, "TSP_Extensions"); er = g(r, "TSP_EarlyRed")
        skip = g(r, "TSP_PhaseSkip"); noact = g(r, "TSP_Detected_NoAction")
        obj = g(r, "Objective_PaxPerDelayHr")
        acts = ext + er + skip
        if name == "NO_TSP":
            verdict = "BASELINE"
        elif acts > 0:
            verdict = "ALIVE"; n_alive += 1
        elif noact > 0:
            verdict = "INERT!"; n_inert += 1       # detected buses but never acted
        else:
            verdict = "no-detect"                   # inconclusive (no detections)
        lines.append("  %-22s %5s %4.0f %4.0f %4.0f %6.0f %8.1f  %-9s" %
                     (name, seed, ext, er, skip, noact, obj, verdict))
    lines.append("-" * 90)
    lines.append("  ALIVE=%d  INERT=%d  MISSING=%d  (INERT = buses detected but 0 "
                 "actions -> dead/mis-wired decider)" % (n_alive, n_inert, n_missing))
    lines.append("  (verdicts read from kg/results/; the champion CSV may show "
                 "run_success=False due to completion-detection miss -- the per-run "
                 "folders hold the real data)")
    for ln in lines:
        _cs._br.log(ln)
    try:
        with open(_os.path.join(_HERE, "check_methodologies_live_report.txt"),
                  "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 84)
    _log(f"LIVE METHODOLOGY CHECK -- corridor={_cs.CORRIDOR} | seed={SEEDS} | "
         f"{len(_arms)} methodologies")
    _log(f"  arms: {[a['name'] for a in _arms]}")
    _log("  running one seed each; then printing per-mode action counts.")
    _log("=" * 84)
    _cs.main(arms=_arms, results_csv=_results_csv)
    _report()
