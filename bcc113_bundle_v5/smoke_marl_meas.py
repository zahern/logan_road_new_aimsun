"""
smoke_marl_meas.py -- leak-test + measurement-feed smoke test (ONE seed).

Runs, in this order, on eval seed 300 ONLY, into its OWN csv
(champion_smoke_marls_<corr>.csv -- the live champion_kg.csv is untouched):

    NO_TSP -> DCTSP_MARL -> DCTSP_MARL_MEAS -> DCTSP_MARL_MEAS_Q
        -> CELLQLEARN -> CELLQLEARN_MEAS -> CELLQLEARN_MEAS_Q -> MILP_MPC

Why this order: NO_TSP sets no flags (sterile); DCTSP_MARL runs SECOND, so
nothing that could poison it (esp. DCTSP_ZIG's ZIG_ENABLE_*=False) has run.
MILP_MPC runs LAST: the honest backend gate (trivial HiGHS solve on the
console thread) skips it cleanly with zero cost if native init fails; if it
runs, compare its row per-seed against NO_TSP (identical = dead controller,
different = alive) and grep the log for [MILP_MPC] FATAL.
If MARL acts here but not in the full campaign, the campaign silence is a
cross-arm leak, not the arm. CELLQLEARN_MEAS / CELLQLEARN_MEAS_Q are
script-local clones of CELLQLEARN + the measurement feeds (NOT added to the
campaign ARMS or LEARNING_ARMS -- eval-only smoke, no training).

How to run (after a FULL Aimsun restart so the new engine is live):
    1. Open the KG model in Aimsun.
    2. Aimsun Python console, run:
         exec(open('C:/Users/ahernz/github_for_aimsun/bcc113_bundle_v5/smoke_marl_meas.py').read())
    3. ~7 arms x ~7-10 min. Watch the per-run summary table at the end.

What to report back: the final table below, plus any
"[FLAGS] exp=DCTSP_MARL ..." line showing SEQ=False (leak) vs all-True.
"""
import copy as _copy
import csv as _csv
import glob as _glob
import os as _os
import sys as _sys

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

import champion_search as _cs

NAMES = ["NO_TSP", "DCTSP_MARL", "DCTSP_MARL_MEAS", "DCTSP_MARL_MEAS_Q",
         "CELLQLEARN"]
_BY_NAME = {a["name"]: a for a in _cs.ARMS}

_arms = []
for _n in NAMES:
    if _n not in _BY_NAME:
        print(f"[SMOKE] WARNING: arm {_n} not in ARMS -- skipped")
        continue
    _arms.append(_copy.deepcopy(_BY_NAME[_n]))

# Script-local CELLQLEARN measurement clones (NOT campaign arms).
_base = _copy.deepcopy(_BY_NAME["CELLQLEARN"])
_meas = _copy.deepcopy(_base)
_meas["name"] = "CELLQLEARN_MEAS"
_meas["reward_overrides"] = dict(_meas.get("reward_overrides", {}))
_meas["reward_overrides"]["MEASURED_STATE_FEED"] = True
_arms.append(_meas)
_meas_q = _copy.deepcopy(_meas)
_meas_q["name"] = "CELLQLEARN_MEAS_Q"
_meas_q["reward_overrides"] = dict(_meas_q.get("reward_overrides", {}))
_meas_q["reward_overrides"]["MEASURED_QUEUE_FEED"] = True
_arms.append(_meas_q)

# BXT-decider dispatch tokens for the clones (same decider as the base).
_cs._EXPECTED_ACTIVE_MODE["CELLQLEARN_MEAS"] = "BXT"
_cs._EXPECTED_ACTIVE_MODE["CELLQLEARN_MEAS_Q"] = "BXT"
# MILP_MPC last: verify CONTROL_MODE dispatch; liveness is judged per-seed
# vs NO_TSP (identical metrics = dead controller) + [MILP_MPC] FATAL grep.
if "MILP_MPC" in _BY_NAME:
    _arms.append(_copy.deepcopy(_BY_NAME["MILP_MPC"]))
    _cs._EXPECTED_ACTIVE_MODE["MILP_MPC"] = "@MILP_MPC"
else:
    print("[SMOKE] WARNING: MILP_MPC not in ARMS -- skipped")

# ONE seed only; learners run eval-only (no training -- smoke test).
_cs.EVAL_SEEDS = [300]
_cs.TRAIN_SEEDS = []

_csv_path = _os.path.join(_cs._ROOT, f"champion_smoke_marls_{_cs.CORRIDOR}.csv")
print("=" * 70)
print(f"[SMOKE] corridor={_cs.CORRIDOR} arms={[a['name'] for a in _arms]}")
print(f"[SMOKE] seeds={_cs.EVAL_SEEDS} train={_cs.TRAIN_SEEDS} -> {_csv_path}")
print("=" * 70)

_cs.main(arms=_arms, results_csv=_csv_path, resume=False)

# ── Summary table ────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("[SMOKE] per-arm action summary")
print("=" * 70)
try:
    with open(_csv_path, newline="", encoding="utf-8-sig") as _fh:
        _rows = list(_csv.DictReader(_fh))
except Exception as _e:
    print(f"[SMOKE] could not read {_csv_path}: {_e!r}")
    _rows = []

for _r in _rows:
    def _I(_k):
        try:
            return int(float(_r.get(_k) or 0))
        except Exception:
            return 0

    def _F(_k):
        try:
            return float(_r.get(_k) or "nan")
        except Exception:
            return float("nan")

    print(f"  {_r.get('run_experiment', '?'):20s} seed={_r.get('run_seed', '?'):>4s} "
          f"obj={_F('stats_Objective_PaxPerDelayHr'):9.1f} "
          f"det={_I('stats_TSP_Detections'):5d} ext={_I('stats_TSP_Extensions'):4d} "
          f"ins={_I('stats_TSP_Insertions'):4d} gr={_I('stats_TSP_GreenRealloc'):3d} "
          f"er={_I('stats_TSP_EarlyRed'):3d} noact={_I('stats_TSP_Detected_NoAction'):5d}")

# ── [FLAGS] audit lines from the newest Aimsun log ────────────────────
print("\n[SMOKE] [FLAGS] audit lines (decision-gate state per run):")
try:
    _logs = sorted(_glob.glob(_os.path.join(_cs.CORR_DIR, "logs",
                                            "Aimsun_TSP_Log_*.txt")),
                   key=_os.path.getmtime)
    if _logs:
        _txt = open(_logs[-1], encoding="utf-8", errors="replace").read()
        _found = [ln for ln in _txt.splitlines() if "[FLAGS] exp=" in ln]
        # one line per experiment (last occurrence wins)
        _seen = {}
        for _ln in _found:
            try:
                _seen[_ln.split("exp=")[1].split()[0]] = _ln
            except Exception:
                pass
        for _exp, _ln in _seen.items():
            print("  " + _ln[:300])
        if not _seen:
            print("  (no [FLAGS] lines -- engine predates the audit; RESTART AIMSUN)")
    else:
        print("  (no Aimsun log found)")
except Exception as _e:
    print(f"  (log scan failed: {_e!r})")

print("\n[SMOKE] done. Report the table + [FLAGS] lines.")
