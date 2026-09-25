#!/usr/bin/env python3
"""
Debug: Check what type the schedule items are and their actual methods.
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

for d in demands:
    name = d.getName()
    did = d.getId()
    try:
        vn = d.getVehicle().getName().lower() if d.getVehicle() else ""
    except:
        vn = ""

    print("\nDemand: " + name + " (ID=" + str(did) + ") Vehicle=" + vn)

    sched = d.getSchedule()
    if not sched:
        print("  No schedule")
        continue

    print("  Schedule items: " + str(len(sched)))

    for i, si in enumerate(sched):
        item = si.getTrafficDemandItem()
        if not item:
            continue

        factor = si.getFactor()
        iname = item.getName() if hasattr(item, 'getName') else "?"

        print("  [" + str(i) + "] " + iname + " factor=" + str(factor))
        print("    Type: " + str(type(item)))
        
        # Print ALL methods
        methods = [m for m in dir(item) if not m.startswith('_')]
        print("    ALL methods: " + str(methods))
        
        # Try to get factor and set factor
        print("    Current factor: " + str(si.getFactor()))
        print("    setFactor method exists: " + str(hasattr(si, 'setFactor')))
        
        # Try setting factor
        try:
            old_f = si.getFactor()
            si.setFactor(200)
            new_f = si.getFactor()
            print("    Changed factor from " + str(old_f) + " to " + str(new_f))
            # Reset
            si.setFactor(old_f)
        except Exception as e:
            print("    Error setting factor: " + str(e))

print("\nDone!")