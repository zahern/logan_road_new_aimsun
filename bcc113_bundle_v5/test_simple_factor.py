#!/usr/bin/env python3
"""
Quick test: Just try to change factor on first schedule item found.
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
    sched = d.getSchedule()
    if not sched:
        continue
    
    for i, si in enumerate(sched):
        item = si.getTrafficDemandItem()
        if not item:
            continue
            
        print("Demand: " + d.getName())
        print("  Schedule item " + str(i) + ": factor=" + str(si.getFactor()))
        print("  Item type: " + str(type(item)))
        
        if hasattr(item, 'getNumOrigins'):
            print("  HAS getNumOrigins")
            try:
                n = item.getNumOrigins()
                print("    getNumOrigins() = " + str(n))
            except Exception as e:
                print("    Error calling getNumOrigins: " + str(e))
        else:
            print("  NO getNumOrigins attribute")
        
        # Try to set factor as string
        try:
            old_f = si.getFactor()
            print("  Current factor: " + str(old_f))
            si.setFactor("200")
            new_f = si.getFactor()
            print("  Changed factor from " + str(old_f) + " to " + str(new_f))
            # Reset
            si.setFactor(str(old_f))
        except Exception as e:
            print("  Error setting factor: " + str(e))
        
        print("---")
        sys.exit(0)

print("No schedule items found!")