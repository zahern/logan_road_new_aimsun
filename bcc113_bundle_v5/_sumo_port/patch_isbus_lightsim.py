"""patch_isbus_lightsim.py -- same defect as plan_select_env._is_bus.

The KG bus vType is <vType id="bus" length="12.0" ... guiShape="bus"/> with NO
vClass attribute, so SUMO reports the default class "passenger" and
lightsim_pax_env._is_bus() (which tests getVehicleClass == "bus") never matches.
Every bus was therefore weighted as a car: bus_occ=40 collapsed to car_occ=1.2 in
both the observation's bus channel and the reward. That silently made the whole
pax-weighted DQN thread vehicle-weighted, while bench_pax (which reads the vType
id from tripinfo) still scored it as pax -- training and evaluation disagreed.

Idempotent: re-running prints ALREADY_PATCHED_OR_MISSING and changes nothing.
"""
import os
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lightsim_pax_env.py")
if not os.path.exists(p):
    p = "lightsim_pax_env.py"

s = open(p, encoding="utf-8").read()
old = """    def _is_bus(self, vid):
        try:
            return self.conn.vehicle.getVehicleClass(vid) == "bus"
        except Exception:
            return False"""
new = """    def _is_bus(self, vid):
        # Match the vType as well as the class: KG's bus vType declares no vClass,
        # so SUMO reports "passenger" and a class-only test misses every bus.
        try:
            if "bus" in str(self.conn.vehicle.getTypeID(vid)).lower():
                return True
        except Exception:
            pass
        try:
            return self.conn.vehicle.getVehicleClass(vid) == "bus"
        except Exception:
            return False"""

if old not in s:
    print("ALREADY_PATCHED_OR_MISSING")
    sys.exit(0)
assert s.count(old) == 1, "expected exactly one _is_bus block"
open(p, "w", encoding="utf-8").write(s.replace(old, new))
print("PATCHED_LIGHTSIM_IS_BUS")
