#!/usr/bin/env python3
"""
Simple verification: Run two sims and print clear numbers.
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
demands = list(objs.values()) if isinstance(objs, dict) else list(objs)

# Find first demand with matrix
target_si = None
for d in demands:
    sched = d.getSchedule()
    if not sched: continue
    for si in sched:
        item = si.getTrafficDemandItem()
        if item and hasattr(item, 'multiply'):
            target_si = si
            target_demand = d
            break
    if target_si: break

if not target_si:
    print("No demand with matrix found!")
    sys.exit(1)

orig = target_si.getFactor()
print("Original factor: " + str(orig))

# =========== RUN 1: 2.0x ===========
target_si.setFactor("200")
print("\n=== RUN 1: Factor = 200 (2.0x) ===")

model = GKSystem.getSystem().getActiveModel()
rep_type = model.getType("GKReplication")
reps = model.getCatalog().getObjectsByType(rep_type)
rep = list(reps.values())[0] if isinstance(reps, dict) else reps[0]
rep.setRandomSeed(300)

GKSystem.getSystem().executeAction("execute", rep, [], "")
time.sleep(2)
waited = 0
status = -1
while waited < 30:
    try:
        status = rep.getSimulationStatus()
    except Exception:
        status = -1
    if status != 1:
        break
    time.sleep(0.5)
    waited += 0.5

# Try to get flow stats
try:
    veh = rep.getTotalNumberOfVehicles()
    print("RUN 1 (2.0x) - Total vehicles: " + str(veh))
except:
    print("RUN 1 - Could not get vehicle count")

# =========== RUN 2: 1.0x ===========
target_si.setFactor("100")
print("\n=== RUN 2: Factor = 100 (1.0x) ===")

reps = model.getCatalog().getObjectsByType(model.getType("GKReplication"))
rep = list(reps.values())[0] if isinstance(reps, dict) else reps[0]
rep.setRandomSeed(300)

GKSystem.getSystem().executeAction("execute", rep, [], "")
time.sleep(2)
waited = 0
status = -1
while waited < 30:
    try:
        status = rep.getSimulationStatus()
    except Exception:
        status = -1
    if status != 1:
        break
    time.sleep(0.5)
    waited += 0.5

try:
    veh = rep.getTotalNumberOfVehicles()
    print("RUN 2 (1.0x) - Total vehicles: " + str(veh))
except:
    print("RUN 2 - Could not get vehicle count")

# Restore
target_si.setFactor(str(orig))
print("\nDone. If RUN 1 > RUN 2, factor works!")