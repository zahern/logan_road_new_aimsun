#!/usr/bin/env python3
"""
Test: Verify factor actually changes simulation results.
"""

import sys
import time

try:
    from PyANGKernel import GKSystem
except ImportError:
    print("ERROR: Run inside Aimsun Python console!")
    sys.exit(1)

model = GKSystem.getSystem().getActiveModel()
if not model:
    print("No active model!")
    sys.exit(1)

demand_type = model.getType("GKTrafficDemand")
objs = model.getCatalog().getObjectsByType(demand_type)

if not objs:
    print("No GKTrafficDemand objects found!")
    sys.exit(1)

demands = list(objs.values()) if isinstance(objs, dict) else list(objs)

# Find first demand with schedule that has matrix
target_si = None
target_demand = None

for d in demands:
    sched = d.getSchedule()
    if not sched:
        continue
    for i, si in enumerate(sched):
        item = si.getTrafficDemandItem()
        if not item:
            continue
        if hasattr(item, 'multiply'):  # GKODMatrix
            target_si = si
            target_demand = d
            print("Found demand with matrix: " + d.getName())
            break
    if target_si:
        break

if not target_si:
    print("No suitable demand found!")
    sys.exit(1)

print("Using demand: " + target_demand.getName())
print("Original factor: " + str(target_si.getFactor()))

# Save original factor
orig_factor = target_si.getFactor()

# Test 1: Factor 200 (2.0x)
print("\n=== Test 1: Factor = '200' (2.0x) ===")
target_si.setFactor("200")
print("Set factor to: " + str(target_si.getFactor()))

# Get fresh replication
model = GKSystem.getSystem().getActiveModel()
rep_type = model.getType("GKReplication")
reps = model.getCatalog().getObjectsByType(rep_type)
rep = list(reps.values())[0] if isinstance(reps, dict) else reps[0]
rep.setRandomSeed(300)

print("Running simulation with 2.0x demand...")
GKSystem.getSystem().executeAction("execute", rep, [], "")
time.sleep(2.0)

waited = 0.0
while waited < 30.0:
    try:
        status = rep.getSimulationStatus()
    except:
        status = -1
    if status != 1:
        break
    time.sleep(0.5)

# Get results from the replication
try:
    total_veh = rep.getTotalNumberOfVehicles()
    print("Total vehicles in network: " + str(total_veh))
except:
    pass

print("Test 1 done. Waiting 2 seconds...")
time.sleep(2)

# Test 2: Reset to 100 (1.0x)
print("\n=== Test 2: Factor = '100' (1.0x) ===")
target_si.setFactor("100")
print("Set factor to: " + str(target_si.getFactor()))

# Fresh replication
rep_type = model.getType("GKReplication")
reps = model.getCatalog().getObjectsByType(rep_type)
rep = list(reps.values())[0] if isinstance(reps, dict) else reps[0]
rep.setRandomSeed(300)

print("Running simulation with 1.0x demand...")
GKSystem.getSystem().executeAction("execute", rep, [], "")
time.sleep(2.0)

waited = 0.0
while waited < 30.0:
    try:
        status = rep.getSimulationStatus()
    except:
        status = -1
    if status != 1:
        break
    time.sleep(0.5)

try:
    total_veh = rep.getTotalNumberOfVehicles()
    print("Total vehicles in network: " + str(total_veh))
except:
    pass

# Restore original
target_si.setFactor(str(orig_factor))
print("\nRestored original factor: " + str(target_si.getFactor()))
print("\nDone!")