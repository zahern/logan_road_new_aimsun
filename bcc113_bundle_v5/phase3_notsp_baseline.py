"""
phase3_notsp_baseline.py -- Phase 3 NO_TSP (no-priority) demand baseline.

Phase-3 sensitivity is only interpretable against the fixed-time baseline at
the SAME demand: champion-vs-NO_TSP per demand level. This script runs exactly
that piece -- NO_TSP x demand scalars x seeds -- and appends it to the
existing phase3_sensitivity_<corridor>.csv without touching champion rows.

STANDALONE: deliberately imports nothing from phase3_sensitivity.py. Every
helper it needs (corridor detection, controller patching, run collection,
sanity gates) is defined below, mirroring that file's NO_TSP block, so this
runs regardless of what state phase3_sensitivity.py is in. Baseline rows stay
byte-comparable: same controller patch (NORMAL / uncoordinated / KALMAN /
reset weights / cooldown None), same per-scalar console-side OD multiply,
same bus injection off, same sens_* = NONE columns, same resume keys
("NONE", "NONE", demand, seed).

HOW TO RUN (inside Aimsun, corridor model open):
    sys.path.insert(0, r"C:\\Users\\ahernz\\github_for_aimsun\\bcc113_bundle_v5")
    import phase3_notsp_baseline as nb; nb.main(resume=True)
    -> 6 demands x 5 seeds = 30 runs (minus rows already banked)

Start from a freshly reloaded model (pristine 1.0x demand): the OD lever
chains ratios from the CURRENT matrices.
"""

import os as _os, sys as _sys, time as _time, glob as _glob, importlib.util as _ilu

_ROOT = _os.path.dirname(_os.path.abspath(__file__))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)


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
    raise RuntimeError("Open the corridor model in Aimsun first "
                       "(no *.ang.lck found under kg/ or logan_road_new/).")


CORRIDOR, CORR_DIR = _detect_corridor()

_br_path = _os.path.join(CORR_DIR, "batch_runner.py")
_br_spec = _ilu.spec_from_file_location("_br_notsp", _br_path)
_br = _ilu.module_from_spec(_br_spec)
_sys.modules["_br_notsp"] = _br
try:
    _br_spec.loader.exec_module(_br)
except SystemExit:
    pass

NO_TSP_ARM = {"name": "NO_TSP", "strategy": "NORMAL",
              "coordinated": False, "coordination_algo": "KALMAN",
              "reward_overrides": {}}
BUS_OFF = 0.0  # bus-frequency injection forced off: CAR-demand sweep only
RESULTS_CSV = _os.path.join(_ROOT, f"phase3_sensitivity_{CORRIDOR}.csv")

DEMANDS_DEFAULT = [0.6, 0.8, 1.0, 1.2, 1.4, 1.6]
SEEDS_DEFAULT = [300, 400, 500, 600, 700]
RESUME_DEFAULT = True  # skip baseline rows already banked as successful


def _set_controller_const(controller_path, var, value):
    """Regex-patch a top-level module constant, writing real literals."""
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
        return v if v == v else None
    except Exception:
        return None


def _obj_ok(m):
    try:
        v = m.get("stats_Objective_PaxPerDelayHr", "")
        return v not in ("", None) and float(v) != 0.0
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
            f"-- stats did NOT reset between runs (N_BusTrips={nt:.0f}, "
            f"N_DistinctBuses={nb:.0f}). FULLY restart Aimsun before trusting "
            f"any row.")
    return p


def _run_and_collect(rep, name, strategy, seed, scalar, coordinated, coord_algo,
                      CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, log):
    while True:
        _br.set_seed(rep, seed)
        _br.write_run_config(name, strategy, seed, scalar, coordinated,
                             coord_algo, RUN_CONFIG_PATH,
                             global_reward_mode=False,
                             reward_cfg={"BUS_FREQ_INJECT_SCALAR": BUS_OFF},
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
            if m is not None and _obj_ok(m):
                return m
            if w:
                log(f"  blank stats -- re-collecting after {w}s")


def _read_done_baseline_keys():
    """Successful ("NONE","NONE",demand,seed) keys already in RESULTS_CSV."""
    done = set()
    if not _os.path.isfile(RESULTS_CSV):
        return done
    import csv as _csv
    try:
        with open(RESULTS_CSV, newline='', encoding='utf-8-sig') as _fh:
            for _r in _csv.DictReader(_fh):
                if (str(_r.get("sens_tactic", "")) != "NONE"
                        or str(_r.get("sens_freq", "")) != "NONE"):
                    continue
                if str(_r.get("run_success", "")).strip().lower() not in (
                        "true", "1", "yes", ""):
                    continue
                try:
                    if float(_r.get("stats_Objective_PaxPerDelayHr", "")) == 0.0:
                        continue
                except Exception:
                    continue
                try:
                    if float(_r.get("stats_SimDuration_hrs", "")) < 0.98:
                        continue
                except Exception:
                    pass
                done.add((str(_r.get("demand_scalar", "")),
                          str(_r.get("run_seed", "")).split(".")[0]))
    except Exception as _e:
        print(f"[NOTSP] WARNING: could not read {RESULTS_CSV} ({_e}); "
              f"running everything")
    return done


def main(resume=False, demands=None, seeds=None):
    log = _br.log
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    demands = list(demands) if demands else list(DEMANDS_DEFAULT)
    seeds = list(seeds) if seeds else list(SEEDS_DEFAULT)
    _nt = NO_TSP_ARM

    done = _read_done_baseline_keys() if resume else set()
    if resume:
        log(f"[NOTSP] RESUME: {len(done)} baseline rows already banked -- "
            f"skipping those")

    jobs = [(s, sd) for s in demands for sd in seeds
            if (str(s), str(sd)) not in done]
    log("=" * 70)
    log(f"[NOTSP] NO_TSP demand baseline -- corridor={CORRIDOR} | "
        f"{len(demands)} demands x {len(seeds)} seeds = {len(jobs)} runs "
        f"({len(demands) * len(seeds) - len(jobs)} skipped)")
    log(f"  -> {RESULTS_CSV} (append; champion rows untouched)")
    log("=" * 70)
    if not jobs:
        log("[NOTSP] nothing to do -- baseline complete")
        return

    try:
        _br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    try:
        _br.set_control_mode(_nt["strategy"], CONTROLLER_PATH)
        _br.set_coordinated(CONTROLLER_PATH, _nt["coordinated"])
        _br.set_coordination_algo(CONTROLLER_PATH, _nt["coordination_algo"])
        _br.set_reward_weights(CONTROLLER_PATH, {})
        _set_controller_const(CONTROLLER_PATH,
                              "TSP_COOLDOWN_OVERRIDE_S", None)
    except Exception as e:
        log(f"[NOTSP] FATAL patch NO_TSP baseline: {e}")
        return

    od_state = {}  # persistent ratio-chain (never reset mid-sweep)
    run_num, flagged = 0, 0
    try:
        for scalar in demands:
            try:
                _br.scale_od_matrices_multiply(scalar, od_state)
            except Exception as e:
                log(f"[NOTSP] FATAL demand x{scalar:g}: {e}")
                raise
            rep = _br.get_first_replication()
            for seed in seeds:
                if (str(scalar), str(seed)) in done:
                    log(f"  SKIP done: NO_TSP | d={scalar} | seed={seed}")
                    continue
                run_num += 1
                log(f"[{run_num}/{len(jobs)}] {CORRIDOR} | NO_TSP | "
                    f"d={scalar} | seed={seed}")
                m = _run_and_collect(
                    rep, "NO_TSP", _nt["strategy"], seed, scalar,
                    _nt["coordinated"], _nt["coordination_algo"],
                    CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, log)
                if m is not None:
                    m["sens_base"] = "NO_TSP"
                    m["sens_tactic"] = "NONE"
                    m["sens_freq"] = "NONE"
                    m["sens_cooldown_s"] = None
                    m["demand_scalar"] = scalar
                    m["sens_ge_on"] = False
                    m["sens_ins_on"] = False
                    m["sens_gr_on"] = False
                    m["sens_seq_on"] = False
                    _br.append_master_csv(RESULTS_CSV, m)
                    problems = _sanity_problems(m)
                    for p in problems:
                        log(f"  [SANITY] WARNING: {p}")
                    if problems:
                        flagged += 1
                    carry = [x for x in problems
                             if x.startswith("CARRY-OVER")]
                    if carry:
                        raise RuntimeError(
                            f"ABORTING NO_TSP baseline at run "
                            f"{run_num}/{len(jobs)} -- stats CARRY-OVER: "
                            f"{carry[0]}")
    finally:
        try:
            _set_controller_const(CONTROLLER_PATH,
                                  "TSP_COOLDOWN_OVERRIDE_S", None)
        except Exception:
            pass
        try:
            _br.scale_od_matrices_multiply(1.0, od_state)
        except Exception as _re:
            try:
                log(f"WARNING: OD restore to 1.0x failed: {_re} -- reload "
                    f"the model before the next sweep for pristine demand.")
            except Exception:
                pass
        try:
            _br._set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    log("=" * 70)
    log(f"[NOTSP] DONE ({CORRIDOR}) -> {RESULTS_CSV}")
    log(f"[NOTSP] {run_num} runs, {flagged} flagged")
    log("=" * 70)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true",
                    help="skip baseline (demand, seed) rows already banked "
                         "as successful in the existing CSV")
    ap.add_argument("--demands", default=None,
                    help="comma list, e.g. 0.6,1.0,1.6 (default: full grid)")
    ap.add_argument("--seeds", default=None,
                    help="comma list, e.g. 300,400 (default: 300-700)")
    a = ap.parse_args()
    main(resume=(a.resume or RESUME_DEFAULT),
         demands=([float(x) for x in a.demands.split(",")]
                  if a.demands else None),
         seeds=([int(x) for x in a.seeds.split(",")]
                if a.seeds else None))
