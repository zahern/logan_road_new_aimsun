"""
champion_milp_mpc_quick.py -- Quick test: NO_TSP vs MILP_MPC (one seed).

Exercises the REAL rolling-horizon MPC controller (not the MILP_TSP greedy
decider): HiGHS backend in-process (OR-Tools cannot load inside Aimsun --
DLL collision), verified-measurement Q_init feed, per-tick replan.

Run from the Aimsun console with the corridor model open:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\champion_milp_mpc_quick.py").read())

Output -> champion_milp_mpc_quick_<corridor>.csv (cleared at start).

Watch for:
  * NO "SKIP MILP_MPC" line (means a solver backend resolved).
  * "[MILP_MPC] initialized solver=highs_scipy_milp" in the TSP log.
  * Per-tick "solver=highs_scipy_milp status=4|2 ..." lines (4=optimal,
    2=time-limit incumbent -- both usable; the controller reuses the prior
    plan rather than stalling when a solve fails outright).
"""

import os as _os
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

# Cache-buster: Aimsun's persistent interpreter caches `champion_search` (and
# the batch_runner it exec-loads) from the first champion run this session, so
# edits to either never load. Purge the chain so it re-reads from disk. The
# in-sim engine still needs a full Aimsun restart. (See champion_marl_meas_quick.)
for _mn in ("champion_search", "_br_champ"):
    _sys.modules.pop(_mn, None)

import champion_search as _cs

_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []

SUBSET = ["NO_TSP", "MILP_MPC"]

_arms = [a for a in _cs.ARMS if a.get("name") in SUBSET]
_missing = set(SUBSET) - {a.get("name") for a in _arms}
if _missing:
    raise RuntimeError(f"MILP_MPC quick test: arms missing from ARMS: {_missing}")

_results_csv = _os.path.join(_cs._ROOT, f"champion_milp_mpc_quick_{_cs.CORRIDOR}.csv")
try:
    if _os.path.isfile(_results_csv):
        _os.remove(_results_csv)
except Exception:
    pass

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"MILP_MPC QUICK TEST -- corridor={_cs.CORRIDOR} | 2 arms x seed 300 | "
         f"NO_TSP vs MILP_MPC (HiGHS backend + measured Q_init feed)")
    _log("=" * 70)
    try:
        _be = _cs._milp_backend()
    except Exception:
        _be = None
    _log(f"MILP backend resolved in this interpreter: {_be}")
    if _be is None:
        raise RuntimeError("No MILP backend importable (need scipy>=1.9 in the "
                           "Aimsun-visible interpreter).")
    _cs.main(arms=_arms, results_csv=_results_csv)
    _log("=" * 70)
    _log(f"SOLVES DONE -> {_results_csv}")

    # ── Measurement verification for BOTH arms ──────────────────────────
    # Same run folders, new flow/density/queue stack: timeseries checks
    # (k_avg vs snap, conservation, queue calibration) + intersection audit
    # (delays, TSP ladder, bounds, type positions, truncation). A solver that
    # "wins" on objective but fails measurement is not a win.
    _log("=" * 70)
    _log("MEASUREMENT VERIFICATION (both arms, same run folders)")
    _log("=" * 70)
    import glob as _glob
    import importlib.util as _ilu

    def _load(_name):
        _p = _os.path.join(_HERE, _name)
        _spec = _ilu.spec_from_file_location(
            "_mpcq_" + _name.replace(".", "_"), _p)
        _m = _ilu.module_from_spec(_spec)
        _sys.modules[_spec.name] = _m
        _spec.loader.exec_module(_m)
        return _m

    _cts = _load("check_timeseries.py")
    _aud = _load("audit_intersections.py")
    _resdir = _os.path.join(_cs._br.PROJECT_DIR, "results")
    _summary = {}
    for _exp in ("NO_TSP", "MILP_MPC"):
        _cands = sorted(
            _glob.glob(_os.path.join(_resdir, f"{_exp}_seed300_*")),
            key=lambda _p: _os.path.getmtime(_p))
        if not _cands:
            _log(f"  {_exp}: no run folder found -- skipping measurement check")
            _summary[_exp] = None
            continue
        _folder = _cands[-1]
        _log(f"  --- {_exp}: {_os.path.basename(_folder)} ---")
        try:
            _rc1 = _cts.main(_folder)
        except Exception as _e:
            _log(f"  {_exp} timeseries check raised: {_e!r}")
            _rc1 = 1
        try:
            _f, _w, _i = _aud.audit_folder(_folder)
            for _x in _i[:6]:
                _log(f"    info: {_x}")
            for _x in _w[:6]:
                _log(f"    WARN: {_x}")
            for _x in _f[:8]:
                _log(f"    FAIL: {_x}")
            _rc2 = 0 if not _f else 1
        except Exception as _e:
            _log(f"  {_exp} intersection audit raised: {_e!r}")
            _rc2 = 1
        _summary[_exp] = (_rc1, _rc2)
    _log("=" * 70)
    _log("MEASUREMENT SUMMARY: " + "; ".join(
        (f"{_e}=timeseries:{'PASS' if _v[0] == 0 else 'FAIL'},"
         f"audit:{'PASS' if _v[1] == 0 else 'FAIL'}")
        if _v is not None else f"{_e}=run-folder-missing"
        for _e, _v in _summary.items()))
    _log("=" * 70)
    _log("DONE -- compare the two objective rows AND the two measurement "
         "verdicts; check the TSP log for solver=highs_scipy_milp status lines.")
    _log("=" * 70)
