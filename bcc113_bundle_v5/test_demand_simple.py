#!/usr/bin/env python3
"""
Simplest possible test: Scale ALL traffic demand by a factor.
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

print(f"Found {len(objs)} traffic demand objects")

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

        # Try to get OD matrix details
        if hasattr(item, 'getNumOrigins'):
            try:
                n_orig = item.getNumOrigins()
                n_dest = item.getNumDestinations()
                n_slices = item.getNumTimeSlices()
                n_vtypes = item.getNumVehicleTypes()
                print("      OD Matrix: " + str(n_orig) + " origins x " + str(n_dest) + " dests x " + str(n_slices) + " slices x " + str(n_vtypes) + " veh types")

                # Show first few OD demands
                for oi in range(min(2, n_orig)):
                    oid = item.getOriginId(oi)
                    for di in range(min(2, n_dest)):
                        did = item.getDestinationId(di)
                        for si in range(min(1, n_slices)):
                            for vt in range(1, n_vtypes + 1):
                                try:
                                    dmd = item.getDemand(oi, di, si, vt)
                                    if dmd > 0:
                                        print("      " + str(oid) + "->" + str(did) + " slice=" + str(si) + " veh=" + str(vt) + ": " + str(dmd))
                                except:
                                    pass
            except Exception as e:
                print("      Error reading OD matrix: " + str(e))

# Now test scaling
print("\n" + "=" * 60)
print("SCALING TEST")
print("=" * 60)

# Find first demand with schedule and matrix
target_demand = None
target_matrix = None
target_si = None

for d in demands:
    sched = d.getSchedule()
    if not sched:
        continue
    for si in sched:
        item = si.getTrafficDemandItem()
        if item and hasattr(item, 'getNumOrigins'):
            target_demand = d
            target_matrix = item
            target_si = si
            break
    if target_demand:
        break

if not target_demand:
    print("No suitable demand found!")
    sys.exit(1)

print("\nUsing demand: " + target_demand.getName())
print("Matrix: " + target_matrix.getName())

# Show current demand
print("\n--- BEFORE scaling ---")
try:
    n_orig = target_matrix.getNumOrigins()
    n_dest = target_matrix.getNumDestinations()
    n_slices = target_matrix.getNumTimeSlices()
    n_vtypes = target_matrix.getNumVehicleTypes()

    for oi in range(min(3, n_orig)):
        oid = target_matrix.getOriginId(oi)
        for di in range(min(3, n_dest)):
            did = target_matrix.getDestinationId(di)
            for si in range(min(1, n_slices)):
                for vt in range(1, n_vtypes + 1):
                    try:
                        dmd = target_matrix.getDemand(oi, di, si, vt)
                        if dmd > 0:
                            print("  " + str(oid) + "->" + str(did) + " slice=" + str(si) + " veh=" + str(vt) + ": " + str(dmd))
                    except:
                        pass
except Exception as e:
    print("Error reading demand: " + str(e))

# Get base demands
base_demands = {}
try:
    for oi in range(target_matrix.getNumOrigins()):
        oid = target_matrix.getOriginId(oi)
        for di in range(target_matrix.getNumDestinations()):
            did = target_matrix.getDestinationId(di)
            for si in range(target_matrix.getNumTimeSlices()):
                for vt in range(1, target_matrix.getNumVehicleTypes() + 1):
                    dmd = target_matrix.getDemand(oi, di, si, vt)
                    if dmd > 0:
                        key = str(oid) + "->" + str(did) + "::slice=" + str(si) + "::veh=" + str(vt)
                        base_demands[key] = float(target_matrix.getDemand(oi, di, si, vt))
except:
    pass

# Test scaling
print("\n--- Applying 2.0x scalar ---")
scaled = 0
for key, base_val in base_demands.items():
    parts = key.split("::")
    oid = parts[0].split("->")[0]
    did = parts[0].split("->")[1]
    si = int(parts[1].split("=")[1])
    vt = int(parts[2].split("=")[1])

    new_val = int(round(base_demands[key] * 2.0))

    # Try multiple methods
    result = -1
    try:
        from PyANGKernel import AKIODDemandSetDemandODPair
        result = AKIODDemandSetDemandODPair(oid, did, vt, si, int(round(base_demands[key] * 2.0)))
    except:
        pass

    if result < 0:
        try:
            result = target_matrix.setDemand(oid, did, si, vt, int(round(base_demands[key] * 2.0)))
        except:
            pass

    if result >= 0:
        scaled += 1
        if scaled <= 5:
            print("  Scaled: " + str(oid) + "->" + str(did) + " slice=" + str(si) + " veh=" + str(vt))

print("Scaled " + str(scaled) + " OD pairs with 2.0x")

# Read back
print("\n--- AFTER 2.0x scaling ---")
try:
    for oi in range(min(3, target_matrix.getNumOrigins())):
        oid = target_matrix.getOriginId(oi)
        for di in range(min(3, target_matrix.getNumDestinations())):
            did = target_matrix.getDestinationId(di)
            for si in range(min(1, target_matrix.getNumTimeSlices())):
                for vt in range(1, target_matrix.getNumVehicleTypes() + 1):
                    try:
                        dmd = target_matrix.getDemand(oi, di, si, vt)
                        if dmd > 0:
                            print("  " + str(oid) + "->" + str(did) + " slice=" + str(si) + " veh=" + str(vt) + ": " + str(dmd))
                    except:
                        pass
except Exception as e:
    print("Error: " + str(e))

# Apply 0.5x
print("\n--- Applying 0.5x (should return to 1.0) ---")
for key in list(base_demands.keys()):
    parts = key.split("::")
    oid = parts[0].split("->")[0]
    did = parts[0].split("->")[1]
    si = int(parts[1].split("=")[1])
    vt = int(parts[2].split("=")[1])

    new_val = int(round(base_demands[key] * 0.5))
    try:
        from PyANGKernel import AKIODDemandSetDemandODPair
        AKIODDemandSetDemandODPair(oid, did, vt, si, new_val)
    except:
        try:
            target_matrix.setDemand(oid, did, si, vt, new_val)
        except:
            pass

print("\n--- AFTER 0.5x scaling (should be back to 1.0) ---")
try:
    for oi in range(min(3, target_matrix.getNumOrigins())):
        oid = target_matrix.getOriginId(oi)
        for di in range(min(3, target_matrix.getNumDestinations())):
            did = target_matrix.getDestinationId(di)
            for si in range(min(1, target_matrix.getNumTimeSlices())):
                for vt in range(1, target_matrix.getNumVehicleTypes() + 1):
                    try:
                        dmd = target_matrix.getDemand(oi, di, si, vt)
                        if dmd > 0:
                            print("  " + str(oid) + "->" + str(did) + " slice=" + str(si) + " veh=" + str(vt) + ": " + str(dmd))
                    except:
                        pass
except Exception as e:
    print("Error: " + str(e))

print("\nDone!")