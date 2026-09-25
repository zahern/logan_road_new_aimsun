#!/usr/bin/env python3
"""
Robust demand scalar test - runs all scalars, handles errors, saves to CSV.
"""

import sys
import os
import traceback

try:
    from PyANGKernel import GKSystem
except ImportError:
    print("ERROR: Run inside Aimsun Python console!")
    sys.exit(1)

_HERE = r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5"
sys.path.insert(0, _HERE)

import champion_search as _cs
_br = _cs._br

print("Using batch_runner from: " + _br.__file__)

CORRIDOR = _cs.CORRIDOR
CONTROLLER_PATH = _br.CONTROLLER_PATH
RUN_CONFIG_PATH = _br.RUN_CONFIG_PATH
PROJECT_DIR = _br.PROJECT_DIR

ARM = {
    "name": "DCTSP_MARL",
    "strategy": "GLOBAL_REWARD",
    "coordinated": True,
    "coordination_algo": "KALMAN",
    "reward_overrides": {
        "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0,
        "REWARD_BETA": 1.0, "REWARD_GAMMA": 1.0,
        "DCTSP_GREEN_REALLOC_MODE": True,
        "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
        "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
        "DECIDER_COST_VETO_RATIO": 3.0},
}

DEMAND_SCALARS = [1.0, 0.6, 0.8, 1.2, 1.4, 1.6]
TEST_SEED = 300
RESULTS_CSV = os.path.join(r"C:\Users\ahernz\github_for_aimsun\bcc113_bundle_v5", "test_demand_scalars_" + _cs.CORRIDOR + ".csv")

# Patch controller
_br.set_control_mode("GLOBAL_REWARD", _br.CONTROLLER_PATH, None)
_br.set_coordinated(_br.CONTROLLER_PATH, True)
_br.set_coordination_algo(_br.CONTROLLER_PATH, "KALMAN")
rov = {
    "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0,
    "REWARD_BETA": 1.0, "REWARD_GAMMA": 1.0,
    "DCTSP_GREEN_REALLOC_MODE": True,
    "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
    "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
    "DECIDER_COST_VETO_RATIO": 3.0,
}
_numeric = {k: v for k, v in rov.items() if k != "GLOBAL_REWARD_MODE"}
_br.set_reward_weights(_br.CONTROLLER_PATH, _numeric)

print("="*70)
print("DEMAND SCALAR TEST - corridor=" + _cs.CORRIDOR)
print("Scalars: " + str(DEMAND_SCALARS))
print("Output: " + os.path.abspath(RESULTS_CSV))
print("="*70)

base_demands = {}
base_od_demands = {}

for idx, scalar in enumerate(DEMAND_SCALARS):
    label = "DCTSP_MARL_Dx{:g}".format(scalar)
    print("\n--- [{}/{}] Running {} ---".format(idx+1, len(DEMAND_SCALARS), label))
    
    # 1. Scale OD demand directly FIRST
    try:
        n_od = _br.set_od_demand_scalar(scalar, base_od_demands, rep=None)
        print("  OD demand scaled: {} pairs".format(n_od))
    except Exception as e:
        print("  OD demand scaling failed: {}".format(e))
        traceback.print_exc()
    
    # Apply traditional demand scalar
    rep = _br.get_first_replication()
    _br.set_seed(rep, 300)
    try:
        _br.set_demand_scalar(scalar, base_demands, rep=rep)
    except Exception as e:
        print("  Demand scalar failed: {}".format(e))
        traceback.print_exc()
        continue
    
    # Write run config
    _br.write_run_config(
        "DCTSP_MARL", "GLOBAL_REWARD", 300, scalar,
        True, "KALMAN", _br.RUN_CONFIG_PATH,
        global_reward_mode=True, reward_cfg=rov,
        bus_predictor="ADAPTIVE_KALMAN",
        results_csv_name=os.path.basename("test_demand_scalars_kg.csv"))
    
    # Get fresh replication for this run
    rep = _br.get_first_replication()
    _br.set_seed(rep, 300)
    
    # Run replication
    try:
        _br.run_replication(rep)
    except Exception as e:
        print("  EXCEPTION during run: {}".format(e))
        traceback.print_exc()
        continue
    
    # Collect metrics
    try:
        m = _br.collect_run_metrics(
            _br.PROJECT_DIR, "GLOBAL_REWARD", 300, scalar,
            "DCTSP_MARL", True, 0.0, True,
            bus_predictor="ADAPTIVE_KALMAN")
        
        if m and m.get("run_success"):
            m["demand_scalar"] = scalar
            _br.append_master_csv(RESULTS_CSV, m)
            flow = m.get("stats_Net_TotalFlowVeh", 0)
            cars = m.get("stats_N_DistinctCars", 0)
            delay = m.get("stats_TotalPassDelay_hrs", 0)
            obj = m.get("stats_Objective_PaxPerDelayHr", 0)
            print("  Flow: {} | Cars: {} | Delay: {} | Obj: {}".format(flow, cars, delay, obj))
        else:
            print("  FAILED: {}".format(m.get("run_success") if m else None))
    except Exception as e:
        print("  Metrics error: {}".format(e))
        traceback.print_exc()

    # Small delay between runs
    import time
    time.sleep(2)

print("\n" + "="*70)
print("DONE! Results saved to: " + os.path.abspath(RESULTS_CSV))
print("Open in Excel to see demand scalar response")