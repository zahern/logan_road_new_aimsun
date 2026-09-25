#!/usr/bin/env python3
"""
Create a simple experiment that runs demand scaling and saves results to CSV/Excel.
Uses the batch_runner infrastructure so results auto-save to CSV.
"""

import sys
import os
import time

try:
    from PyANGKernel import GKSystem
except ImportError:
    print("ERROR: Run inside Aimsun Python console!")
    sys.exit(1)

# Get the project root - try multiple ways
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = os.getcwd()

# Add project paths
sys.path.insert(0, os.path.join(_HERE, "kg"))
sys.path.insert(0, os.path.join(_HERE, "logan_road_new"))

import kg.batch_runner as _br

print("Loading batch_runner from: " + _br.__file__)

# Setup
model = GKSystem.getSystem().getActiveModel()
if not model:
    print("No active model!")
    sys.exit(1)

CORRIDOR = "kg"
CORR_DIR = os.path.join(_HERE, "kg")
CONTROLLER_PATH = os.path.join(CORR_DIR, "intersection_controller.py")
RUN_CONFIG_PATH = os.path.join(CORR_DIR, "run_config.py")
PROJECT_DIR = CORR_DIR

# Use the champion DCTSP_MARL strategy
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
RESULTS_CSV = os.path.join(_HERE, "test_demand_scalars_kg.csv")

# Patch controller
_br.set_control_mode("GLOBAL_REWARD", CONTROLLER_PATH, None)
_br.set_coordinated(CONTROLLER_PATH, True)
_br.set_coordination_algo(CONTROLLER_PATH, "KALMAN")
rov = {
    "GLOBAL_REWARD_MODE": True, "REWARD_ALPHA": 1.0,
    "REWARD_BETA": 1.0, "REWARD_GAMMA": 1.0,
    "DCTSP_GREEN_REALLOC_MODE": True,
    "GREEN_REALLOC_RECOVER_FRACTION": 1.0,
    "DCTSP_W_H": 0.50, "DCTSP_CAR_WEIGHT": 1.00,
    "DECIDER_COST_VETO_RATIO": 3.0,
}
_numeric = {k: v for k, v in rov.items() if k != "GLOBAL_REWARD_MODE"}
_br.set_reward_weights(CONTROLLER_PATH, _numeric)

print("="*70)
print("DEMAND SCALAR TEST - Results will save to " + RESULTS_CSV)
print("Scalars: " + str(DEMAND_SCALARS))
print("="*70)

base_demands = {}
base_od_demands = {}

for scalar in DEMAND_SCALARS:
    label = "DCTSP_MARL_Dx{:g}".format(scalar)
    print("\n--- Running " + label + " ---")
    
    # Scale OD demand directly FIRST
    try:
        n_od = _br.set_od_demand_scalar(scalar, base_od_demands, rep=None)
        print("  OD demand scaled: " + str(n_od) + " pairs")
    except Exception as e:
        print("  OD demand scaling failed: " + str(e))
    
    # Apply traditional demand scalar
    rep = _br.get_first_replication()
    _br.set_seed(rep, 300)
    _br.set_demand_scalar(scalar, base_demands, rep=rep)
    
    # Write run config
    _br.write_run_config(
        "DCTSP_MARL", "GLOBAL_REWARD", 300, scalar,
        True, "KALMAN", RUN_CONFIG_PATH,
        global_reward_mode=True, reward_cfg=rov,
        bus_predictor="ADAPTIVE_KALMAN",
        results_csv_name=os.path.basename(RESULTS_CSV))
    
    # Run replication
    rep = _br.get_first_replication()
    _br.set_seed(rep, 300)
    
    try:
        _br.run_replication(rep)
    except Exception as e:
        print("  EXCEPTION: " + str(e))
        continue
    
    # Collect metrics
    try:
        m = _br.collect_run_metrics(
            PROJECT_DIR, "GLOBAL_REWARD", 300, scalar,
            "DCTSP_MARL", True, 0.0, True,
            bus_predictor="ADAPTIVE_KALMAN")
        
        if m and m.get("run_success"):
            m["demand_scalar"] = scalar
            _br.append_master_csv(RESULTS_CSV, m)
            flow = m.get("stats_Net_TotalFlowVeh", 0)
            cars = m.get("stats_N_DistinctCars", 0)
            delay = m.get("stats_TotalPassDelay_hrs", 0)
            print("  Flow: " + str(flow) + " | Cars: " + str(cars) + " | Delay: " + str(delay))
        else:
            print("  FAILED: " + str(m.get("run_success")) if m else "None")
    except Exception as e:
        print("  Metrics error: " + str(e))

print("\n" + "="*70)
print("DONE! Results saved to: " + RESULTS_CSV)
print("Open in Excel to see demand scalar response")