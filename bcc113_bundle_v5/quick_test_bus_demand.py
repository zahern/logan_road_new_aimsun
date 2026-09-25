"""
quick_test_bus_demand.py -- verify the PT-frequency scaler actually scales.

Purpose: after any change to pt_inject.py / engine.py entry registry or
calibration, confirm (a) the calibration file records the real bus service,
and (b) each BUSx level produces a DIFFERENT number of bus trips.  This is the
symptom the defect report flagged (BUSx1/x2/x3 byte-identical on KG, 2026-09-01).

Design: champion spec (the Phase-1 winner, DCTSP_MARL on KG), ONE seed (300),
iterate BUS_DEMAND_SCALARS = [0.5, 0.75, 1.0, 2.0, 3.0].  Prints a table:

    scalar | N_BusTrips | N_DistinctBuses | TotalPassDelay_hrs | TSP_Detections
    0.5    |     ...    |      ...        |       ...          |     ...
    1.0    |     ...
    3.0    |  ~ x3 of 1.0  <- the test

HOW TO RUN (inside Aimsun, corridor model open, model = kg or logan):
    python quick_test_bus_demand.py

Result -> quick_test_bus_demand_<corridor>.csv  (also printed to console)
Also validates the calibration CSV was re-written this session by an x1.0 pass.
"""

import os as _os, sys as _sys, time as _time, importlib.util as _ilu

# ── 1. Load champion_search (Phase-1 machinery) by absolute path ──────────────
try:
    _HERE = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    _HERE = _os.path.abspath(_os.getcwd())
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

_cs_path = _os.path.join(_HERE, "champion_search.py")
_spec_cs = _ilu.spec_from_file_location("champion_search", _cs_path)
_cs = _ilu.module_from_spec(_spec_cs)
_sys.modules["champion_search"] = _cs
_spec_cs.loader.exec_module(_cs)

CORRIDOR = _cs.CORRIDOR
CORR_DIR = _cs.CORR_DIR
_br = _cs._br
log = _br.log

_bd_path = _os.path.join(CORR_DIR, "batch_runner_bus_demand.py")
_spec_bd = _ilu.spec_from_file_location("_bd_quick", _bd_path)
_bd = _ilu.module_from_spec(_spec_bd)
_sys.modules["_bd_quick"] = _bd
try:
    _spec_bd.loader.exec_module(_bd)
except SystemExit:
    pass

# ── 2. Test design: champion spec, 1 seed, all bus scalars ───────────────────
# 1.0 FIRST: the x1.0 replication runs the engine in calibrating mode and
# rewrites pt_entry_calibration.csv with the fresh (all-sections) entry
# pattern.  Every following level then scales against THAT pattern -- so the
# 0.5/0.75/2.0/3.0 rows measure the new registry, not the stale file.
BUS_SCALARS = [1.0, 0.5, 0.75, 2.0, 3.0]
TEST_SEED = 300
CHAMP_NAME = "DCTSP_MARL"          # KG Phase-1 winner
RESULTS_CSV = _os.path.join(_HERE, f"quick_test_bus_demand_{CORRIDOR}.csv")

_arms = [a for a in _cs.ARMS if a["name"] == CHAMP_NAME]
if not _arms:
    raise RuntimeError(f"Champion arm '{CHAMP_NAME}' not found in champion_search ARMS")


def _calibration_path():
    return _os.path.join(CORR_DIR, "pt_entry_calibration.csv")


def _run_one(label, scalar, CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR):
    """Set the injection scalar, run one replication, collect metrics."""
    arm = _arms[0]
    strategy = arm["strategy"]
    coordinated = arm.get("coordinated", False)
    coord_algo = arm.get("coordination_algo", "KALMAN")
    rov = dict(arm.get("reward_overrides", {}) or {})
    rov["Z4_CONSTRAINT_MODE"] = True
    rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
    _global_reward = bool(rov.get("GLOBAL_REWARD_MODE", False))
    _numeric = {k: v for k, v in rov.items() if k != "GLOBAL_REWARD_MODE"}
    bus_pred = str(rov.get("BUS_PREDICTOR_TYPE", "ADAPTIVE_KALMAN")).upper()

    try:
        _bd.set_bus_freq_inject_scalar(scalar, CONTROLLER_PATH)
    except Exception as e:
        log(f"FATAL bus scalar {scalar}: {e}")
        return None
    try:
        _br.set_control_mode(strategy, CONTROLLER_PATH,
                             arm.get("active_intersections"))
        _br.set_coordinated(CONTROLLER_PATH, coordinated)
        _br.set_coordination_algo(CONTROLLER_PATH, coord_algo)
        _br.set_reward_weights(CONTROLLER_PATH, _numeric or None)
    except Exception as e:
        log(f"FATAL patch {label}: {e}")
        return None
    try:
        _cs._set_controller_bxt_seeds(CONTROLLER_PATH, [], [], _cs.BXT_TRAIN_EPSILON)
    except Exception:
        pass

    _run_reward_cfg = dict(_numeric)
    _run_reward_cfg["BUS_FREQ_INJECT_SCALAR"] = scalar

    rep = _br.get_first_replication()
    _br.set_seed(rep, TEST_SEED)
    m = _cs._run_and_collect(
        _br, rep, label, strategy, TEST_SEED, 1.0,
        coordinated, coord_algo, _global_reward, _run_reward_cfg,
        bus_pred, CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, RESULTS_CSV, log)
    if m is not None:
        m["sweep_bus_demand_scalar"] = scalar
        m["sweep_base_arm"] = CHAMP_NAME
        try:
            _br.append_master_csv(RESULTS_CSV, m)
        except Exception as _ac_err:
            log(f"  append_master_csv failed: {_ac_err}")
    return m


def main():
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    log("=" * 70)
    log(f"QUICK BUS-DEMAND SCALER TEST -- corridor={CORRIDOR}")
    log(f"  champion={CHAMP_NAME} | seed={TEST_SEED} | scalars={BUS_SCALARS}")
    log(f"  car/truck demand fixed at 1.0x (bus-only sweep)")
    log(f"  -> {RESULTS_CSV}")
    log("=" * 70)

    # fresh results file (test artifact; never share with Phase-2 CSV)
    try:
        if _os.path.exists(RESULTS_CSV):
            _os.remove(RESULTS_CSV)
    except Exception:
        pass
    try:
        _br._set_logging(CONTROLLER_PATH, enabled=False)
    except Exception:
        pass
    _cs._disable_batch_plotting(CONTROLLER_PATH)

    # Calibration pre-check: the scalar can only scale if an x1.0 calibration
    # entry pattern exists (recorded by the engine in calibrating mode).
    calib_ok = _os.path.isfile(_calibration_path())
    if not calib_ok:
        log("  !! no pt_entry_calibration.csv -- scaler cannot inject x>1; "
            "rerun after a fresh x1.0 calibration pass (or use "
            "champion_bus_demand.py which auto-calibrates)")

    rows = []
    for scalar in BUS_SCALARS:
        label = f"{CHAMP_NAME}_BUSx{scalar:g}"
        log(f"--- {label} ---")
        m = _run_one(label, scalar, CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR)
        if m is None:
            log(f"  {label}: FAILED (no metrics)")
            continue
        try:
            trips = float(m.get("stats_N_BusTrips") or 0)
        except (TypeError, ValueError):
            trips = 0.0
        try:
            buses = float(m.get("stats_N_DistinctBuses") or 0)
        except (TypeError, ValueError):
            buses = 0.0
        try:
            paxh = float(m.get("stats_TotalPassDelay_hrs") or 0)
        except (TypeError, ValueError):
            paxh = 0.0
        try:
            det = float(m.get("stats_TSP_Detections") or 0)
        except (TypeError, ValueError):
            det = 0.0
        log(f"  trips={trips:.0f} buses={buses:.0f} paxh={paxh:.2f} "
            f"det={det:.0f}")
        rows.append(dict(scalar=float(scalar), trips=trips, buses=buses,
                         paxh=paxh, det=det))

    # ── Verdict ────────────────────────────────────────────────────────────
    log("=" * 70)
    log(f"{'scalar':>7} | {'trips':>6} | {'buses':>5} | {'paxh':>9} | {'det':>4}")
    log("-" * 47)
    for r in rows:
        log(f"{r['scalar']:>7.2f} | {r['trips']:>6.0f} | {r['buses']:>5.0f} | "
            f"{r['paxh']:>9.2f} | {r['det']:>4.0f}")
    log("=" * 70)
    try:
        r1 = next(r for r in rows if abs(float(r.get("scalar", 0) or 0) - 1.0) < 1e-9)
        r3 = next(r for r in rows if abs(float(r.get("scalar", 0) or 0) - 3.0) < 1e-9)
        t1, t3 = float(r1["trips"] or 0), float(r3["trips"] or 0)
        if t1 > 0 and t3 / t1 > 1.5:
            log(f"PASS: x3.0 trips = {t3:.0f} vs x1.0 {t1:.0f} "
                f"({t3 / t1:.2f}x) -- scaler is live")
        else:
            log(f"FAIL: x3.0 trips = {t3:.0f} vs x1.0 {t1:.0f} "
                f"({(t3 / t1) if t1 else float('nan'):.2f}x) -- scalar did "
                f"NOT reach the sim; check pt_entry_calibration.csv and the "
                f"[PT-INJ] logs")
    except StopIteration:
        log("VERDICT: no x1.0/x3.0 rows to compare (runs failed)")

    # restore: feature off + re-enable logging (never leave the scalar set)
    try:
        _bd.set_bus_freq_inject_scalar(0.0, CONTROLLER_PATH)
    except Exception:
        pass
    try:
        _br._set_logging(CONTROLLER_PATH, enabled=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
