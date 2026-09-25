#!/usr/bin/env python3
"""
Debug: Find out what type the traffic demand items are and what methods they have.
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

# Check each demand
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

        # Print ALL methods/attributes of the item
        print("      Type: " + str(type(item)))
        methods = [m for m in dir(item) if not m.startswith('_')]
        print("      Methods: " + str([m for m in methods if 'origin' in m.lower() or 'dest' in m.lower() or 'demand' in m.lower() or 'matrix' in m.lower() or 'num' in m.lower() or 'slice' in m.lower() or 'vehicle' in m.lower() or 'type' in m.lower() or 'origin' in m.lower() or 'dest' in m.lower()]))

        # Try specific methods
        for method in ['getNumOrigins', 'getNumDestinations', 'getNumTimeSlices', 'getNumVehicleTypes', 
                       'getOriginId', 'getDestinationId', 'getDemand', 'setDemand', 'getDemandODPair', 'setDemandODPair',
                       'getOrigin', 'getDestination', 'getNumO', 'getNumD', 'getNumS', 'getNumV']:
            if hasattr(item, method):
                print("      HAS: " + method)

print("\nDone!")