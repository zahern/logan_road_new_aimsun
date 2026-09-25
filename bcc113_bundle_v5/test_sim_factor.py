#!/usr/bin/env python3
"""
Test: Change factor and run a quick simulation to verify demand changes.
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

print("Found " + str(len(objs)) + " traffic demand objects")

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
        
        if hasattr(item, 'multiply'):  # GKODMatrix has multiply method
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

# Test 1: Set to 200 (2.0x)
print("\n--- Setting factor to '200' (2.0x) ---")
target_si.setFactor("200")
print("New factor: " + str(target_si.getFactor()))

# Get a fresh replication
from PyANGKernel import GKSystem
model = GKSystem.getSystem().getActiveModel()
rep_type = model.getType("GKReplication")
reps = model.getCatalog().getObjectsByType(rep_type)
rep = list(reps.values())[0] if isinstance(reps, dict) else reps[0]

# Set seed
target_si.setFactor("200")
rep.setRandomSeed(300)

# Run a quick simulation (just 100 seconds)
print("\n--- Running simulation with 2.0x demand ---")
start = time.time()
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
    waited += 0.5

elapsed = time.time() - start
print("Simulation ran for " + str(int(elapsed)) + " seconds")

# Now reset factor to 100
target_si.setFactor("100")
print("\nReset factor to 100")

# Get fresh replication
reps = model.getCatalog().getObjectsByType(rep_type)
rep = list(reps.values())[0] if isinstance(reps, dict) else reps[0]
rep.setRandomSeed(300)

# Run with normal demand
print("\n--- Running simulation with 1.0x demand ---")
start = time.time()
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
    waited += 0.5

elapsed = time.time() - start
print("Simulation ran for " + str(int(elapsed)) + " seconds")

print("\nDone! Check if flow/cars differed between runs.")