"""
phase3_logan_resume.py -- BCC113 Logan Road Phase 3: run the 139 outstanding runs.

Reads LR_Phase3_MISSING_runs_for_Zeke.csv (order,tactic,frequency,
demand_scalar,seed,reason) and executes each row in order against the Logan
Road model. Same mechanics as phase3_sensitivity.py (tactic/freq patching,
console-side OD multiply with persistent anti-compounding od_state, sanity
gates), plus the two fixes the 10-SEP audit asked for:

  1. SIM-DURATION GUARD: a run is accepted only if stats_SimDuration_hrs >=
     0.98 * EXPECTED_SIM_HRS (1.5 h). The truncated
     DCTSP_MARL_SWAPS_X2_FREQUENT seed-400 x1.0 run (1.113 h) passed every
     old check; this guard rejects it. Rejected runs re-execute up to
     MAX_ATTEMPTS times, then are recorded with run_success=False so no
     ranker can use them.
  2. demand_scalar is stamped on every master-CSV row (no run-order inference).

BASE is fixed to DCTSP_MARL (Logan mirror) to match the 131 completed runs --
not re-picked from any champion CSV -- so old and new rows are comparable.

HOW TO RUN (inside Aimsun, LOGAN model open):
    python phase3_logan_resume.py
        -> all 139 rows in CSV order
    python phase3_logan_resume.py --quick
        -> first 2 rows only (smoke test)
    python phase3_logan_resume.py --from-order 50
        -> start at order #50 (1-based, after an interruption)
    python phase3_logan_resume.py --cell BOTH/X1_BASELINE
        -> only that tactic/freq cell (repeatable; highest-value cell first)
    python phase3_logan_resume.py --missing-csv "path/to.csv"
        -> explicit missing-runs file (default: the Zeke CSV in bundle root)

Results -> phase3_sensitivity_logan_RESUME.csv (sens_tactic / sens_freq /
demand_scalar columns, same schema as phase3_sensitivity.py output, plus
run_success). Per-run folders land wherever SimulationStats writes them
(merge with Final_results_LR on completion).
"""

import os as _os, sys as _sys, time as _time, glob as _glob, importlib.util as _ilu

_ROOT = _os.path.dirname(_os.path.abspath(__file__))

# ── Corridor guard: this file is Logan-only ──────────────────────────────
def _detect_corridor():
    cands = []
    for c in ("kg", "logan_road_new"):
        d = _os.path.join(_ROOT, c)
        locks = _glob.glob(_os.path.join(d, "*.ang.lck")) + \
                _glob.glob(_os.path.join(d, "*.sang.lck"))
        if locks:
            cands.append((c, d, max(_os.path.getmtime(p) for p in locks)))
    if cands:
        cands.sort(key=lambda t: -t[2]); return cands[0][0], cands[0][1]
    raise RuntimeError("Open a corridor model in Aimsun first "
                       "(no *.ang.lck found under kg/ or logan_road_new/).")


CORRIDOR, CORR_DIR = _detect_corridor()
if CORRIDOR != "logan_road_new" and "--force-corridor" not in _sys.argv:
    raise RuntimeError(
        f"phase3_logan_resume.py is Logan-only but the open model resolves to "
        f"'{CORRIDOR}'. Open the Logan Road model (or pass --force-corridor).")

# ── Batch-runner infrastructure (Logan runner) ───────────────────────────
_br_path = _os.path.join(CORR_DIR, "batch_runner.py")
_spec = _ilu.spec_from_file_location("_br_p3lr", _br_path)
_br = _ilu.module_from_spec(_spec); _sys.modules["_br_p3lr"] = _br
try:
    _spec.loader.exec_module(_br)
except SystemExit:
    pass

# ── Design (mirrors phase3_sensitivity.py; BASE fixed for comparability) ─
BASE = {
    "name": "DCTSP_MARL", "strategy": "GLOBAL_REWARD",
    "coordinated": True, "coordination_algo": "KALMAN",
    "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0,
        "REWARD_BETA": 1.0, "REWARD_GAMMA": 1.0,
        "DCTSP_GREEN_REALLOC_MODE": True,
        "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
        "DECIDER_COST_VETO_RATIO": 3.5,
        "DCTSP_CONGESTION_GATE": True,
        "DCTSP_CONGESTION_GATE_FRACTION": 0.70,
        "BXT_MODE": False, "DCTSP_ZIG_MODE": False,
        "MP_ECTM_MODE": False, "BARGAIN_SPM_MODE": False,
        "CENTRALIZED_MODE": False},
}

TACTICS = {
    "TIMES": {"ZIG_ENABLE_GE": True,  "ZIG_ENABLE_INS": True,
              "ZIG_ENABLE_GR": True,  "ZIG_ENABLE_SEQ": False},
    "SWAPS": {"ZIG_ENABLE_GE": False, "ZIG_ENABLE_INS": False,
              "ZIG_ENABLE_GR": False, "ZIG_ENABLE_SEQ": True},
    "BOTH":  {"ZIG_ENABLE_GE": True,  "ZIG_ENABLE_INS": True,
              "ZIG_ENABLE_GR": True,  "ZIG_ENABLE_SEQ": True},
}

FREQS = {
    "X1_BASELINE": None,
    "X2_FREQUENT":  40,
    "X3_RARE":     120,
}

# Phase-3 sweeps CAR demand only; force the bus-frequency scalar OFF so the
# demand axis is unambiguously CAR-only (see phase3_sensitivity.py rationale).
BUS_FREQ_INJECT_SCALAR_PHASE3 = 0.0

# Sim-duration guard (10-SEP audit fix): Logan runs must simulate the full
# design horizon. Accepted iff sim_duration_hrs >= DUR_TOL * EXPECTED.
EXPECTED_SIM_HRS = 1.5
DUR_TOL = 0.98
MAX_ATTEMPTS = 3   # initial run + up to 2 re-executions, then record failed

DEFAULT_MISSING_CSV = _os.path.join(
    _ROOT, "LR_Phase3_MISSING_runs_for_Zeke 1.csv")
RESULTS_CSV = _os.path.join(_ROOT, "phase3_sensitivity_logan_RESUME.csv")


def _set_controller_const(controller_path, var, value):
    """Regex-patch a top-level module constant (copy of phase3_sensitivity's;
    values always written as proper Python literals)."""
    import re
    with open(controller_path, "r", encoding="utf-8", errors="replace") as f:
        txt = f.read()
    pat = re.compile(r"(?m)^(%s)(\s*:\s*[a-zA-Z_.\[\]]+)?\s*=.*$" % re.escape(var))
    if value is None:
        val = "None"
    elif isinstance(value, (bool, int, float)):
        val = repr(value)
    else:
        s = str(value).strip()
        if s.lower() in ("true", "false"):
            val = s.capitalize()
        else:
            try:
                val = repr(float(s)) if ("." in s or "e" in s.lower()) else repr(int(s))
            except ValueError:
                val = repr(value)
    if pat.search(txt):
        txt = pat.sub(lambda m: "%s%s = %s" % (m.group(1), m.group(2) or "", val),
                      txt, count=1)
    else:
        txt = txt.replace("\nCONTROL_MODE",
                          "\n%s = %s\nCONTROL_MODE" % (var, val), 1)
    with open(controller_path, "w", encoding="utf-8", newline="") as f:
        f.write(txt)


def _fnum(m, key):
    try:
        v = float(m.get(key))
        return v if v == v else None          # NaN -> None
    except Exception:
        return None


def _obj_ok(m):
    try:
        v = m.get("stats_Objective_PaxPerDelayHr", "")
        return v not in ("", None) and float(v) != 0.0
    except Exception:
        return False


def _duration_ok(m):
    """Sim-duration guard: reject runs stopped short of the design horizon
    (the truncated seed-400 x1.0 run this resume exists to replace)."""
    try:
        d = float(m.get("stats_SimDuration_hrs", ""))
        return d >= DUR_TOL * EXPECTED_SIM_HRS
    except Exception:
        return False


def _sanity_problems(m):
    p = []
    nc, nb = _fnum(m, 'stats_N_DistinctCars'), _fnum(m, 'stats_N_DistinctBuses')
    ac, ab = _fnum(m, 'stats_AvgCarPassDelay_s'), _fnum(m, 'stats_AvgBusPassDelay_s')
    dur = _fnum(m, 'stats_SimDuration_hrs')
    if nc is None or nc < 500:
        p.append(f"N_DistinctCars={nc} (<500 -- car counting collapsed)")
    if ac is None or not (0 < ac < 600):
        p.append(f"AvgCarPassDelay_s={ac} outside (0,600)")
    if nb is not None and nb < 5:
        p.append(f"N_DistinctBuses={nb} (<5)")
    if ab is not None and not (0 < ab < 600):
        p.append(f"AvgBusPassDelay_s={ab} outside (0,600)")
    if dur is not None and dur <= 0:
        p.append("SimDuration_hrs<=0")
    nt = _fnum(m, 'stats_N_BusTrips')
    if nt is not None and nb is not None and nb > 0 and nt / nb > 30.0:
        p.append(
            f"CARRY-OVER: N_BusTrips/N_DistinctBuses={nt / nb:.0f} (>30; real ~5-10) "
            f"-- stats did NOT reset between runs. FULLY restart Aimsun.")
    return p


_SIG_KEYS = ('stats_Objective_PaxPerDelayHr', 'stats_N_DistinctCars',
             'stats_N_DistinctBuses', 'stats_AvgCarPassDelay_s')


def _run_signature(m):
    try:
        s = tuple(round(_fnum(m, k) or 0.0, 3) for k in _SIG_KEYS)
        return s if any(s) else None
    except Exception:
        return None


def _run_and_collect(rep, name, strategy, seed, scalar, coordinated, coord_algo,
                     global_reward, reward_cfg, CONTROLLER_PATH, RUN_CONFIG_PATH,
                     PROJECT_DIR, log):
    """Execute one replication; accept only objective-OK *and* full-duration
    runs. Up to MAX_ATTEMPTS executions, then return the last metrics with
    run_success=False so rankers skip the row."""
    attempt = 0
    m = None
    while True:
        attempt += 1
        _br.set_seed(rep, seed)
        _br.write_run_config(name, strategy, seed, scalar, coordinated,
                             coord_algo, RUN_CONFIG_PATH,
                             global_reward_mode=global_reward,
                             reward_cfg=reward_cfg or None,
                             bus_predictor="ADAPTIVE_KALMAN",
                             results_csv_name=_os.path.basename(RESULTS_CSV))
        _br._purge_pyc(CONTROLLER_PATH)
        t0 = _time.time(); ok = True
        try:
            _br.run_replication(rep)
        except Exception as e:
            ok = False; log(f"  EXCEPTION: {e}")
        dt = _time.time() - t0
        for w in (0, 4, 8, 12):
            if w:
                _time.sleep(w)
            try:
                m = _br.collect_run_metrics(PROJECT_DIR, strategy, seed, scalar,
                                            name, coordinated, dt, ok,
                                            bus_predictor="ADAPTIVE_KALMAN")
            except Exception as e:
                log(f"  metrics FAIL: {e}"); m = None
            if m is not None and _obj_ok(m) and _duration_ok(m):
                m["run_success"] = True
                return m
            if w:
                log(f"  blank/short stats — re-collecting after {w}s")
        # Rejected: blank objective or truncated duration.
        _why = ("blank objective" if not (m is not None and _obj_ok(m))
                else f"truncated sim_duration_hrs={_fnum(m or {}, 'stats_SimDuration_hrs')} "
                     f"(< {DUR_TOL * EXPECTED_SIM_HRS:.3f} h)")
        if attempt >= MAX_ATTEMPTS:
            log(f"  REJECTED after {attempt} attempts ({_why}) -- recording failed row")
            if m is None:
                m = {}
            m["run_success"] = False
            return m
        log(f"  REJECTED attempt {attempt}/{MAX_ATTEMPTS} ({_why}) -- re-executing")


def _load_missing(path):
    import csv as _csv
    with open(path, newline='', encoding='utf-8-sig') as _fh:
        rows = list(_csv.DictReader(_fh))
    jobs = []
    for _r in rows:
        try:
            jobs.append({
                "order": int(_r.get("order", 0)),
                "tactic": (_r.get("tactic") or "").strip(),
                "freq": (_r.get("frequency") or "").strip(),
                "scalar": float(_r.get("demand_scalar")),
                "seed": int(_r.get("seed")),
                "reason": (_r.get("reason") or "").strip(),
            })
        except (TypeError, ValueError) as _e:
            raise RuntimeError(f"bad row in missing-runs CSV: {_r} ({_e})")
    for _j in jobs:
        if _j["tactic"] not in TACTICS:
            raise RuntimeError(f"unknown tactic {_j['tactic']} (row {_j['order']})")
        if _j["freq"] not in FREQS:
            raise RuntimeError(f"unknown frequency {_j['freq']} (row {_j['order']})")
    jobs.sort(key=lambda j: j["order"])
    return jobs


def main(missing_csv=None, quick=False, from_order=1, cells=None):
    log = _br.log
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    jobs = _load_missing(missing_csv or DEFAULT_MISSING_CSV)
    if quick:
        jobs = jobs[:2]
    jobs = [j for j in jobs if j["order"] >= from_order]
    if cells:
        _want = set(cells)
        jobs = [j for j in jobs if f"{j['tactic']}/{j['freq']}" in _want]
    if not jobs:
        log("nothing to run (filters excluded everything)"); return

    n_total = len(jobs)
    log("=" * 70)
    log(f"PHASE 3 LOGAN RESUME -- corridor={CORRIDOR} | base={BASE['name']}")
    log(f"  {n_total} run(s) from {_os.path.basename(missing_csv or DEFAULT_MISSING_CSV)} "
        f"(orders {jobs[0]['order']}-{jobs[-1]['order']})")
    log(f"  duration guard: sim_duration_hrs >= {DUR_TOL * EXPECTED_SIM_HRS:.3f} h "
        f"else re-execute (max {MAX_ATTEMPTS} attempts)")
    log(f"  -> {RESULTS_CSV}")
    log("=" * 70)

    try:
        _br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    for flag, val in (("MARK_DETECTION_POINTS", False),
                      ("OVERLAY_DETECTIONS_ON_MAP", False),
                      ("TRACK_BUS_POSITIONS", False),
                      ("STATUS_DASHBOARD_INTERVAL_S", 0.0)):
        try:
            _set_controller_const(CONTROLLER_PATH, flag, val)
        except Exception:
            pass

    od_state = {}  # persistent multiply state (ratio-based, never reset)
    run_num = 0
    _flagged = 0
    _failed = 0
    _seen_sigs = {}  # (demand, seed) -> [(tactic, freq, sig)] for dup checks
    _cur_cell = (None, None)
    _cur_scalar = object()  # force scaling on the first row
    try:
        rep = None
        for j in jobs:
            tactic, freq, scalar, seed = (j["tactic"], j["freq"],
                                         j["scalar"], j["seed"])
            # ── patch controller ONCE per (tactic, freq) cell ──
            if (tactic, freq) != _cur_cell:
                rov = dict(BASE["reward_overrides"])
                rov.update(TACTICS[tactic])
                rov["Z4_CONSTRAINT_MODE"] = True
                rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
                name = f"{BASE['name']}_{tactic}_{freq}"
                try:
                    _br.set_control_mode(BASE["strategy"], CONTROLLER_PATH)
                    _br.set_coordinated(CONTROLLER_PATH, BASE["coordinated"])
                    _br.set_coordination_algo(CONTROLLER_PATH,
                                              BASE["coordination_algo"])
                    _br.set_reward_weights(CONTROLLER_PATH, dict(rov))
                    _set_controller_const(CONTROLLER_PATH,
                                          "TSP_COOLDOWN_OVERRIDE_S",
                                          FREQS[freq])
                except Exception as e:
                    log(f"FATAL patch {name}: {e}"); continue
                _cur_cell = (tactic, freq)
                _cur_rov, _cur_name = rov, name

            # ── demand lever, once per scalar (ratio-based, verified) ──
            if scalar != _cur_scalar:
                try:
                    _br.scale_od_matrices_multiply(scalar, od_state)
                except Exception as e:
                    log(f"FATAL demand x{scalar:g}: {e}")
                    raise
                rep = _br.get_first_replication()
                _cur_scalar = scalar

            run_num += 1
            log(f"[{run_num}/{n_total}] (csv order {j['order']}) {CORRIDOR} | "
                f"{_cur_name} | d={scalar} | seed={seed} | {j['reason']}")
            _rov_run = dict(_cur_rov)
            _rov_run["BUS_FREQ_INJECT_SCALAR"] = float(BUS_FREQ_INJECT_SCALAR_PHASE3)
            m = _run_and_collect(
                rep, _cur_name, BASE["strategy"], seed, scalar,
                BASE["coordinated"], BASE["coordination_algo"],
                bool(_cur_rov.get("GLOBAL_REWARD_MODE")), _rov_run,
                CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, log)
            if m is not None:
                m["sens_base"] = BASE["name"]
                m["sens_tactic"] = tactic
                m["sens_freq"] = freq
                m["sens_cooldown_s"] = FREQS[freq]
                m["demand_scalar"] = scalar
                # Effective tactic switches as WRITTEN (post-hoc proof the
                # config reached the runner; engine side is in [FLAGS]).
                # NOTE: these gate the GENERIC pool only; a committing
                # decider base decides alone (see phase3_sensitivity.py).
                m["sens_ge_on"] = bool(_cur_rov.get("ZIG_ENABLE_GE", True))
                m["sens_ins_on"] = bool(_cur_rov.get("ZIG_ENABLE_INS", True))
                m["sens_gr_on"] = bool(_cur_rov.get("ZIG_ENABLE_GR", True))
                m["sens_seq_on"] = bool(_cur_rov.get("ZIG_ENABLE_SEQ", True))
                m.setdefault("run_success", True)
                _br.append_master_csv(RESULTS_CSV, m)
                if not m.get("run_success", True):
                    _failed += 1
                    log("  [SANITY] recorded as FAILED (run_success=False) -- "
                        "rankers must skip this row")
                    continue
                _problems = _sanity_problems(m)
                for _p in _problems:
                    log(f"  [SANITY] WARNING: {_p}")
                if _problems:
                    _flagged += 1
                _carry = [x for x in _problems if x.startswith("CARRY-OVER")]
                if _carry:
                    raise RuntimeError(
                        f"ABORTING sweep at run {run_num}/{n_total} "
                        f"-- stats CARRY-OVER: {_carry[0]}")
                _sig = _run_signature(m)
                if _sig is not None:
                    # Keyed duplicate check (see phase3_sensitivity.py): same
                    # (demand, seed) with byte-identical KPIs under a
                    # DIFFERENT tactic/freq means the sweep knob did nothing
                    # for that pair.
                    _prev = _seen_sigs.setdefault((scalar, seed), [])
                    for (_pt, _pf, _psig) in _prev:
                        if _psig == _sig and (_pt, _pf) != (tactic, freq):
                            log("  [SANITY] WARNING: byte-identical KPIs to "
                                f"{_pt}/{_pf} at d={scalar} seed={seed} -- "
                                f"sweep knob inert for this pair?")
                            _flagged += 1
                            break
                    _prev.append((tactic, freq, _sig))
    finally:
        try:
            _set_controller_const(CONTROLLER_PATH, "TSP_COOLDOWN_OVERRIDE_S", None)
        except Exception:
            pass
        try:
            _br.scale_od_matrices_multiply(1.0, od_state)
        except Exception as _re:
            try:
                log(f"WARNING: OD restore to 1.0x failed: {_re} -- reload the "
                    f"model before the next sweep for pristine demand.")
            except Exception:
                pass
        try:
            _br._set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    log("=" * 70)
    log(f"DONE ({CORRIDOR}) -> {RESULTS_CSV}")
    if _failed:
        log(f"FAILED ROWS: {_failed} recorded with run_success=False (re-run "
            f"those orders manually)")
    if _flagged:
        log(f"SANITY SUMMARY: {_flagged}/{run_num} run(s) FLAGGED -- review the "
            f"[SANITY] WARNING lines above before ranking")
    elif not _failed:
        log(f"SANITY SUMMARY: all {run_num} runs healthy")
    log("=" * 70)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="smoke test: first 2 missing rows only")
    ap.add_argument("--from-order", type=int, default=1,
                    help="start at CSV order # (1-based, default 1)")
    ap.add_argument("--cell", action="append", default=None,
                    help="only run a tactic/freq cell, e.g. --cell BOTH/X1_BASELINE "
                         "(repeatable)")
    ap.add_argument("--missing-csv", default=None,
                    help="explicit missing-runs CSV path")
    ap.add_argument("--force-corridor", action="store_true",
                    help="bypass the Logan-only guard (not recommended)")
    a = ap.parse_args()
    main(missing_csv=a.missing_csv, quick=a.quick,
         from_order=a.from_order, cells=a.cell)
