"""
champion_marl_meas_quick.py -- A/B test: DCTSP_MARL vs DCTSP_MARL_MEAS (one seed).

DCTSP_MARL_MEAS is MARL with MEASURED_STATE_FEED=True: approach density
adopted from time-averaged k, detector flows capped at verified section
totals (subset <= whole). Same weights otherwise -- any difference is the
measurement feed. Includes the same per-arm measurement verification as the
MILP_MPC quick test: a solver/decision win only counts if its meters pass.

Run from the Aimsun console with the corridor model open:
    exec(open(r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5\\champion_marl_meas_quick.py").read())

Output -> champion_marl_meas_quick_<corridor>.csv (cleared at start).
"""

import os as _os
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

# ── Cache-buster ──────────────────────────────────────────────────────────
# Aimsun keeps ONE Python interpreter alive across console-script runs, so a
# plain `import champion_search` returns the copy cached the FIRST time a
# champion script ran this session -- and champion_search exec-loads
# batch_runner only at its own import time, so BOTH freeze. Later edits to
# either file then never load (proven 2026-09-07: the dialog-hang fix in
# batch_runner sat on disk while the stale runner kept wedging after arm #1).
# Purge the cached runner chain so it re-reads from disk on every run. The
# in-sim engine (shared_tsp_engine.engine) is loaded by the controller at
# AAPILoad and is NOT covered here -- that one still needs a full restart.
for _mn in ("champion_search", "_br_champ"):
    _sys.modules.pop(_mn, None)

import champion_search as _cs

_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []

SUBSET = ["DCTSP_MARL", "DCTSP_MARL_MEAS", "DCTSP_MARL_MEAS_Q",
          "DCTSP_MARL_RL", "DCTSP_MARL_RL_MEAS"]

_arms = [a for a in _cs.ARMS if a.get("name") in SUBSET]
_missing = set(SUBSET) - {a.get("name") for a in _arms}
if _missing:
    raise RuntimeError(f"MARL_MEAS quick test: arms missing from ARMS: {_missing}")

_results_csv = _os.path.join(_cs._ROOT, f"champion_marl_meas_quick_{_cs.CORRIDOR}.csv")
try:
    if _os.path.isfile(_results_csv):
        _os.remove(_results_csv)
except Exception:
    pass

if __name__ == "__main__":
    _log = _cs._br.log
    _log("=" * 70)
    _log(f"MARL_MEAS QUICK TEST -- corridor={_cs.CORRIDOR} | {len(SUBSET)} arms x "
         f"seed 300 | measured-flow/density/queue-feed A/B matrix "
         f"(MARL / MEAS / MEAS_Q / RL / RL_MEAS)")
    _log("=" * 70)
    _cs.main(arms=_arms, results_csv=_results_csv)
    _log("=" * 70)
    _log(f"SOLVES DONE -> {_results_csv}")

    _log("=" * 70)
    _log("MEASUREMENT VERIFICATION (both arms, same run folders)")
    _log("=" * 70)
    import glob as _glob
    import importlib.util as _ilu

    def _load(_name):
        _p = _os.path.join(_HERE, _name)
        _spec = _ilu.spec_from_file_location(
            "_mrlq_" + _name.replace(".", "_"), _p)
        _m = _ilu.module_from_spec(_spec)
        _sys.modules[_spec.name] = _m
        _spec.loader.exec_module(_m)
        return _m

    _cts = _load("check_timeseries.py")
    _aud = _load("audit_intersections.py")
    _resdir = _os.path.join(_cs._br.PROJECT_DIR, "results")
    _summary = {}
    for _exp in SUBSET:
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
    _log("DONE -- compare the two objective/bus-delay rows AND the two "
         "measurement verdicts. A MEAS win on objective with clean meters = "
         "the feed helps; a win with dirty meters = distrust it.")
    _log("=" * 70)
