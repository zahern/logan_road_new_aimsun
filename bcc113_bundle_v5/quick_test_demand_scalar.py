"""
quick_test_demand_scalar.py -- verify the PHASE-3 demand scaler actually scales.

Phase 3 sweeps TOTAL (car/truck) OD demand via set_demand_scalar (0.6..1.6)
-- NOT the bus-frequency scaler of Phase 2.  The defect report (2026-09-01)
found levels 0.4 apart produced identical simulations on KG (x1.0 == x1.4,
x1.2 == x1.6, in 45/45 cells) because set_demand_scalar silently matched zero
GKTrafficDemand objects (KG demand names = Logan Rd names).

This is the quick single-seed test to confirm the demand axis is live:
does total network flow / distinct cars actually respond to the scalar?

Design: champion spec (Phase-1 winner), ONE seed (300), iterate
DEMAND_SCALARS = [1.0, 0.6, 0.8, 1.2, 1.4, 1.6]
(1.0 first => the run restores demand to its base factor before scaling).

Prints a table + PASS/FAIL verdict (x1.6 total flow should be ~1.5x x1.0):

    scalar | Net_TotalFlowVeh | N_DistinctCars | TotalPassDelay_hrs | avg_car_delay_s
    0.6    |        ...        |      ...       |       ...          |      ...
    1.6    |  ~1.6x of 1.0     <- the test

HOW TO RUN (inside Aimsun, corridor model open):
    python quick_test_demand_scalar.py

Result -> quick_test_demand_scalar_<corridor>.csv
IMPORTANT: car demand is restored to 1.0x at the end (same finally-restore
phase3_sensitivity uses); BUS scaler is forced 0.0 for every run so Phase-3
never inherits a leftover PT scaler.
"""

import os as _os, sys as _sys, time as _time, importlib.util as _ilu

# Import GKSystem for fresh replication queries
try:
    from PyANGKernel import GKSystem
except ImportError:
    GKSystem = None

# Try to import AKIODDemandSetDemandODPair for direct OD demand scaling
try:
    from PyANGKernel import AKIODDemandSetDemandODPair
    _HAS_AKIOD_SET = True
except ImportError:
    _HAS_AKIOD_SET = False
    AKIODDemandSetDemandODPair = None

# Try to import AKIODDemandGetNumSlicesOD, AKIODDemandGetNumSlicesOD, etc.
try:
    from PyANGKernel import (
        AKIODDemandGetNumSlicesOD,
        AKIODDemandGetDemandODPair,
        AKIODDemandGetNumSlicesOD,
        AKIVehGetNbVehTypes
    )
except ImportError:
    pass

# Import GKSystem for fresh replication queries
try:
    from PyANGKernel import GKSystem
except ImportError:
    GKSystem = None

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

# ── 2. Test design: champion spec, 1 seed, all demand scalars ────────────────
# 1.0 FIRST: it anchors the base/total flow so the verdict can compare ratios.
# Include 1.6 for proper ratio test (x1.6 flow should be ~1.6x x1.0)
DEMAND_SCALARS = [1.0, 0.6, 0.8, 1.2, 1.4, 1.6]
TEST_SEED = 300
CHAMP_NAME = "DCTSP_MARL"          # KG Phase-1 winner
RESULTS_CSV = _os.path.join(_HERE, f"quick_test_demand_scalar_{CORRIDOR}.csv")

_arms = [a for a in _cs.ARMS if a["name"] == CHAMP_NAME]
if not _arms:
    raise RuntimeError(f"Champion arm '{CHAMP_NAME}' not found in champion_search ARMS")


_QT_BASE_DEMANDS = {}   # shared baseline cache across the sweep (see _run_one)
_QT_BASE_OD_DEMANDS = {}  # shared baseline cache for OD demand scaling


def _scale_od_demand_direct(scalar, base_od_demands):
    """
    Scale OD demand directly using AKIODDemandSetDemandODPair API.
    This bypasses the GKTrafficDemand schedule factor and replication caching.
    """
    if not _HAS_AKIOD_SET:
        log(f"  WARNING: AKIODDemandSetDemandODPair not available in PyANGKernel")
        return 0
    
    model = GKSystem.getSystem().getActiveModel()
    
    # Find the active demand (car demand)
    demand_type = model.getType("GKTrafficDemand")
    objs = model.getCatalog().getObjectsByType(demand_type)
    if not objs:
        return 0
    
    demand = None
    for d in (objs.values() if isinstance(objs, dict) else objs):
        try:
            _vn = d.getVehicle().getName().lower() if d.getVehicle() else ""
            if "car" in _vn:
                demand = d
                break
        except Exception:
            pass
    
    if demand is None:
        return 0
    
    if base_od_demands is None:
        base_od_demands = {}
    
    n_scaled = 0
    
    # Iterate through schedules and OD matrices
    for sched_item in (demand.getSchedule() or []):
        matrix = sched_item.getTrafficDemandItem()
        if matrix is None:
            continue
        
        # Get OD pairs from the matrix
        try:
            num_origins = matrix.getNumOrigins()
            num_destinations = matrix.getNumDestinations()
            num_slices = matrix.getNumTimeSlices()
            num_vehicle_types = matrix.getNumVehicleTypes()
        except Exception:
            continue
        
        for origin_idx in range(num_origins):
            origin_id = matrix.getOriginId(origin_idx)
            for dest_idx in range(num_destinations):
                dest_id = matrix.getDestinationId(dest_idx)
                for slice_idx in range(num_slices):
                    for veh_type_pos in range(1, num_vehicle_types + 1):
                        try:
                            current_demand = matrix.getDemand(origin_idx, dest_idx, slice_idx, veh_type_pos)
                            if current_demand <= 0:
                                continue
                            
                            # Use a stable key for this OD pair
                            key = f"{origin_id}->{dest_id}::slice={slice_idx}::veh={veh_type_pos}"
                            
                            if key not in base_od_demands:
                                base_od_demands[key] = float(current_demand)
                            
                            new_demand = int(round(base_od_demands[key] * float(scalar)))
                            
                            # Try multiple methods to set the demand
                            result = -1
                            
                            # Method 1: AKIODDemandSetDemandODPair (global API)
                            if _HAS_AKIOD_SET:
                                try:
                                    result = AKIODDemandSetDemandODPair(
                                        origin_id, dest_id, veh_type_pos, slice_idx, new_demand
                                    )
                                except Exception:
                                    result = -1
                            
                            # Method 2: matrix.setDemand (GKODMatrix method)
                            if result < 0:
                                try:
                                    result = matrix.setDemand(origin_idx, dest_idx, slice_idx, veh_type_pos, new_demand)
                                except Exception:
                                    result = -1
                            
                            # Method 3: matrix.setDemandODPair (alternative GKODMatrix method)
                            if result < 0:
                                try:
                                    result = matrix.setDemandODPair(origin_id, dest_id, veh_type_pos, slice_idx, new_demand)
                                except Exception:
                                    result = -1
                            
                            if result >= 0:
                                n_scaled += 1
                        except Exception:
                            continue
    
    if n_scaled > 0:
        log(f"  Direct OD demand scalar {scalar:g}x: scaled {n_scaled} OD pair(s)")
    else:
        log(f"  WARNING: Direct OD demand scalar {scalar:g}x scaled 0 OD pairs")
    return n_scaled


def _report_active_demand(rep, scalar):
    """Log the GKTrafficDemand the replication's experiment/scenario ACTUALLY uses,
    with its schedule-item factors, to kg/logs/demand_scale_debug.txt. This reveals
    whether the demand the sim reads is the one set_demand_scalar scaled (factor
    should show the scaled value, e.g. 160 at x1.6) -- if it shows 100/unchanged,
    the active demand is a different object and must be targeted directly."""
    _lines = [f"ACTIVE-DEMAND check @ scalar={scalar:g}"]
    try:
        _exp = rep.getExperiment() if hasattr(rep, 'getExperiment') else None
        _lines.append(f"  experiment={_exp.getName() if _exp else '?'}")
        _scen = None
        for _m in ('getScenario', 'getScenarioObject'):
            try:
                _scen = getattr(_exp, _m)() if _exp and hasattr(_exp, _m) else _scen
                if _scen is not None:
                    break
            except Exception:
                pass
        _lines.append(f"  scenario={_scen.getName() if _scen else '?'}")
        _dem = None
        for _m in ('getDemand', 'getTrafficDemand'):
            try:
                _dem = getattr(_scen, _m)() if _scen and hasattr(_scen, _m) else _dem
                if _dem is not None:
                    break
            except Exception:
                pass
        if _dem is not None:
            try:
                _did = _dem.getId()
            except Exception:
                _did = '?'
            _lines.append(f"  ACTIVE_DEMAND name={_dem.getName()} id={_did}")
            try:
                for _si in list(_dem.getSchedule() or [])[:10]:
                    _it = _si.getTrafficDemandItem()
                    _nm = _it.getName() if _it else '?'
                    _lines.append(f"    item={_nm} factor={_si.getFactor()}")
            except Exception as _se:
                _lines.append(f"    schedule read failed: {_se}")
        else:
            _lines.append("  ACTIVE_DEMAND=None (scenario.getDemand() not found)")
    except Exception as _e:
        _lines.append(f"  report error: {_e}")
    _msg = "\n".join(_lines)
    log("[RUNNER] " + _msg.replace("\n", "\n[RUNNER] "))
    try:
        _dbg = _os.path.join(CORR_DIR, 'logs', 'demand_scale_debug.txt')
        _os.makedirs(_os.path.dirname(_dbg), exist_ok=True)
        with open(_dbg, 'a', encoding='utf-8') as _f:
            _f.write(_msg + "\n")
    except Exception:
        pass


def _run_one(label, scalar, CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR):
    """Set demand scalar, run one replication, collect metrics."""
    arm = _arms[0]
    strategy = arm["strategy"]
    coordinated = arm.get("coordinated", False)
    coord_algo = arm.get("coordination_algo", "KALMAN")
    rov = dict(arm.get("reward_overrides", {}) or {})
    rov["Z4_CONSTRAINT_MODE"] = True
    rov.setdefault("Z4_TOLERANCE_VEH_S", 300.0)
    _global_reward = bool(rov.get("GLOBAL_REWARD_MODE", False))
    _numeric = {k: v for k, v in rov.items() if k != "GLOBAL_REWARD_MODE"}
    # Phase-3 is a CAR-demand sweep: the PT scaler is FORCED OFF (0.0) for
    # every run so a leftover bus scalar cannot contaminate the demand axis.
    _numeric["BUS_FREQ_INJECT_SCALAR"] = 0.0
    bus_pred = str(rov.get("BUS_PREDICTOR_TYPE", "ADAPTIVE_KALMAN")).upper()

    try:
        _bd.set_bus_freq_inject_scalar(0.0, CONTROLLER_PATH)
    except Exception:
        pass
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

    # ── The Phase-3 lever: scale CAR/truck OD demand, base-cached ------------
    # base_demands is SHARED across the sweep (module-level _QT_BASE_DEMANDS) so
    # the baseline is captured ONCE from the unscaled model; a fresh {} per run
    # would compound now that setFactor is committed and persists between runs.
    base_demands = _QT_BASE_DEMANDS
    # Scale OD demand DIRECTLY using AKIODDemandSetDemandODPair API
    # This MUST be done BEFORE getting the replication, so the OD matrices
    # are modified before the replication reads them.
    _scale_od_demand_direct(scalar, _QT_BASE_OD_DEMANDS)
    # Also apply the traditional demand scalar for compatibility
    base_demands = _QT_BASE_DEMANDS
    # Get a FRESH replication for each run. The replication caches demand at
    # creation time, so we must get a fresh reference for each scalar run.
    # get_first_replication() returns a cached proxy; we force a fresh query
    # by accessing the catalog directly to bypass Python-level caching.
    rep = _get_fresh_replication()
    _br.set_seed(rep, TEST_SEED)
    try:
        _br.set_demand_scalar(scalar, base_demands, rep=rep)
    except Exception as e:
        log(f"FATAL demand scalar {scalar}: {e}")
        return None
    # Report the demand the ACTIVE experiment/scenario uses + its factor AFTER
    # scaling -- the item factors should now show the scaled value (e.g. 160 @1.6).
    try:
        _report_active_demand(rep, scalar)
    except Exception as _rade:
        log(f"  active-demand report failed: {_rade}")
    m = _cs._run_and_collect(
        _br, rep, label, strategy, TEST_SEED, scalar,
        coordinated, coord_algo, _global_reward, _numeric,
        bus_pred, CONTROLLER_PATH, RUN_CONFIG_PATH, PROJECT_DIR, RESULTS_CSV, log)
    if m is not None:
        m["demand_scalar"] = scalar
        m["sweep_base_arm"] = CHAMP_NAME
        try:
            _br.append_master_csv(RESULTS_CSV, m)
        except Exception as _ac_err:
            log(f"  append_master_csv failed: {_ac_err}")
    return m


def _get_fresh_replication():
    """Get a fresh replication proxy by forcing a fresh catalog query.
    This bypasses Python-level proxy caching that causes demand caching."""
    model = GKSystem.getSystem().getActiveModel()
    rep_type = model.getType("GKReplication")
    reps = model.getCatalog().getObjectsByType(rep_type)
    if not reps:
        raise RuntimeError("No replications found.")
    # Force a fresh proxy by creating a new list each time
    reps_list = list(reps.values()) if isinstance(reps, dict) else list(reps)
    return reps_list[0]


def main():
    CONTROLLER_PATH = _br.CONTROLLER_PATH
    RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
    PROJECT_DIR = _br.PROJECT_DIR

    log("=" * 70)
    log(f"QUICK DEMAND-SCALAR TEST (Phase 3 axis) -- corridor={CORRIDOR}")
    log(f"  champion={CHAMP_NAME} | seed={TEST_SEED} | scalars={DEMAND_SCALARS}")
    log(f"  sweeps TOTAL car/truck OD demand; bus frequency fixed at 1.0x")
    log(f"  -> {RESULTS_CSV}")
    log("=" * 70)

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

    rows = []
    run_num = 0
    try:
        for scalar in DEMAND_SCALARS:
            label = f"{CHAMP_NAME}_Dx{scalar:g}"
            run_num += 1
            log(f"[{run_num}/{len(DEMAND_SCALARS)}] --- {label} ---")
            m = _run_one(label, scalar, CONTROLLER_PATH, RUN_CONFIG_PATH,
                         PROJECT_DIR)
            if m is None:
                log(f"  {label}: FAILED (no metrics)")
                continue
            flow = m.get("stats_Net_TotalFlowVeh")
            cars = m.get("stats_N_DistinctCars")
            paxh = m.get("stats_TotalPassDelay_hrs")
            cardly = m.get("stats_AvgCarPassDelay_s")
            log(f"  total_flow={flow} cars={cars} "
                f"paxh={round(float(paxh), 2)} car_delay={round(float(cardly), 2)}")
            rows.append(dict(scalar=scalar, flow=flow, cars=cars,
                             paxh=paxh, cardly=cardly))
    finally:
        # Restore baseline demand (phase-3 finally-restore equivalent) and
        # re-enable logging; never leave the model at a swept level.
        try:
            _br.set_demand_scalar(1.0, {})
        except Exception:
            pass
        try:
            _bd.set_bus_freq_inject_scalar(0.0, CONTROLLER_PATH)
        except Exception:
            pass
        try:
            _br._set_logging(CONTROLLER_PATH, enabled=True)
        except Exception:
            pass

    # ── Verdict ────────────────────────────────────────────────────────────
    log("=" * 70)
    log(f"{'scalar':>7} | {'totalFlow':>9} | {'cars':>6} | {'paxh':>10} | {'carDly':>7}")
    log("-" * 55)
    for r in rows:
        # CSV-sourced metric values arrive as strings; coerce before formatting.
        try:
            _sc = float(r.get("scalar") or 0.0)
        except (TypeError, ValueError):
            _sc = 0.0
        try:
            _fl = float(r.get("flow") or 0.0)
        except (TypeError, ValueError):
            _fl = 0.0
        try:
            _ca = float(r.get("cars") or 0.0)
        except (TypeError, ValueError):
            _ca = 0.0
        try:
            _ph = float(r.get("paxh") or 0.0)
        except (TypeError, ValueError):
            _ph = 0.0
        try:
            _cd = float(r.get("cardly") or 0.0)
        except (TypeError, ValueError):
            _cd = 0.0
        log(f"{_sc:>7.2f} | {_fl:>9.0f} | {int(_ca):>6} | {_ph:>10.2f} | {_cd:>7.2f}")
    log("=" * 70)
    try:
        r1 = next(r for r in rows if abs(float(r.get("scalar", 0) or 0) - 1.0) < 1e-9)
        # Use max scalar available for comparison
        max_scalar = max(float(r.get("scalar", 0) or 0) for r in rows)
        r_max = next(r for r in rows if abs(float(r.get("scalar", 0) or 0) - max_scalar) < 1e-9)
        f1 = float(r1.get("flow") or 0)
        fmax = float(r_max.get("flow") or 0)
        expected_ratio = max_scalar / 1.0
        if f1 > 0 and fmax / f1 > 0.8 * expected_ratio:
            log(f"PASS: x{max_scalar:.1f} total flow = {fmax:.0f} vs x1.0 {f1:.0f} "
                f"({fmax / f1:.2f}x, expected ~{expected_ratio:.1f}x) -- demand scaler is live")
        else:
            log(f"FAIL: x{max_scalar:.1f} total flow = {fmax:.0f} vs x1.0 {f1:.0f} "
                f"({(fmax / f1) if f1 else float('nan'):.2f}x, expected ~{expected_ratio:.1f}x) -- demand did "
                f"NOT respond; check GKTrafficDemand naming (KG fix: "
                f"TARGET_DEMAND_NAMES=None) and the [DEMAND FLOW] init log")
    except StopIteration:
        log("VERDICT: no x1.0/x{max_scalar:.1f} rows to compare (runs failed or missing)")


if __name__ == "__main__":
    main()
