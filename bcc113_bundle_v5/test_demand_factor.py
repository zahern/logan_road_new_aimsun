#!/usr/bin/env python3
"""
Simplest test: Just change schedule item factors.
Run inside Aimsun Python console.
"""

import sys

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

# Collect all schedule items that have matrices
schedule_items = []

for d in demands:
    name = d.getName()
    sched = d.getSchedule()
    if not sched:
        continue
    
    for i, si in enumerate(sched):
        item = si.getTrafficDemandItem()
        if not item:
            continue
        
        factor = si.getFactor()
        iname = item.getName() if hasattr(item, 'getName') else "?"
        
        if hasattr(item, 'getNumOrigins'):
            try:
                n_orig = item.getNumOrigins()
                n_dest = item.getNumDestinations()
                n_slices = item.getNumTimeSlices()
                n_vtypes = item.getNumVehicleTypes()
                print("Demand: " + d.getName() + " | Item: " + iname + " | factor=" + str(factor) + " | Matrix: " + str(n_orig) + "x" + str(n_dest) + "x" + str(n_slices) + "x" + str(n_vtypes))
                schedule_items.append((d, si, item, factor))
            except Exception as e:
                print("  Error reading matrix: " + str(e))

print("\n" + "="*60)
print("SCALING TEST - Changing schedule factors")
print("="*60)

if not schedule_items:
    print("No schedule items with matrices found!")
    sys.exit(1)

# Show current factors
print("\n--- CURRENT FACTORS ---")
for d, si, item, factor in schedule_items:
    print("  " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " | factor=" + str(factor))

# Test 1: Double all factors (2.0x)
print("\n--- Applying 2.0x (set factor to 200) ---")
for d, si, item, factor in schedule_items:
    new_factor = 200  # 2.0x = 200%
    si.setFactor(new_factor)
    print("  Set " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " factor=200")

print("\n--- Verifying factors after 2.0x ---")
for d, si, item, factor in schedule_items:
    new_f = si.getFactor()
    print("  " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " | factor=" + str(new_f))

# Test 2: Reset to 1.0x (100)
print("\n--- Resetting to 1.0x (set factor to 100) ---")
for d, si, item, factor in schedule_items:
    si.setFactor(100)
    print("  Set " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " factor=100")

print("\n--- Verifying factors after reset ---")
for d, si, item, factor in schedule_items:
    new_f = si.getFactor()
    print("  " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " | factor=" + str(new_f))

# Test 3: Apply 1.6x (160)
print("\n--- Applying 1.6x (set factor to 160) ---")
for d, si, item, factor in schedule_items:
    si.setFactor(160)
    print("  Set " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " factor=160")

print("\n--- Verifying 1.6x ---")
for d, si, item, factor in schedule_items:
    new_f = si.getFactor()
    print("  " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " | factor=" + str(new_f))

# Test 4: Apply 0.6x (60)
print("\n--- Applying 0.6x (set factor to 60) ---")
for d, si, item, factor in schedule_items:
    si.setFactor(60)
    print("  Set " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " factor=60")

print("\n--- Verifying 0.6x ---")
for d, si, item, factor in schedule_items:
    new_f = si.getFactor()
    print("  " + d.getName() + " | " + si.getTrafficDemandItem().getName() + " | factor=" + str(new_f))

# Final reset
print("\n--- Final reset to 100 ---")
for d, si, item, factor in schedule_items:
    si.setFactor(100)

print("\nDone! Check if demand scaling works by running a quick simulation.")