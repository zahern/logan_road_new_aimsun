"""Pin VEH_TYPE_POS_CAR/_TRUCK/_BUS in both corridors' run_config.py.

Values are MEASURED, not guessed: every per-intersection result CSV in each
corridor records the controller's live resolution (CarTypePos/BusTypePos/
TruckTypePos, written from stats._car_pos/_bus_pos/_truck_pos), and across
2026-08-27 .. 2026-11-09 they are unanimous:

    Logan (car,bus,truck) = (1,3,2)   in 43,332 intersection-rows, 0 exceptions
    KG                    = (1,4,3)   in 14,256 intersection-rows, 0 exceptions

Why a POSITION pin and not VEH_TYPE_ID_BUS: the id must be an Aimsun GKVehicle
ANG object id (it goes through AKIVehGetVehTypeInternalPosition). The only such
id recorded in this repo is Logan's car (74453); no bus id exists on disk and the
model keeps its vehicle types in the binary .ang. A guessed id resolves to -1
(inert) or, worse, to another type's position. The pin needs no Aimsun and is
validated against AKIVehGetNbVehTypes() at runtime, so a model swap cannot
silently mislabel. An explicit VEH_TYPE_ID_BUS still wins when it is filled in.

Idempotent, EOL-aware.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = b'VEH_TYPE_POS_BUS'

TARGETS = (
    ('logan_road_new/run_config.py', 'Logan', 1, 2, 3),
    ('kg/run_config.py', 'KG', 1, 3, 4),
)

TEMPLATE = '''
# ---------------------------------------------------------------------------
# VEHICLE-TYPE POSITION PINS (2026-11-09)
# Pins the internal position of each vehicle type so resolution no longer
# depends on SWIG name decoding (returns reprs on this Aimsun build) or on the
# corridor folder basename that keys VEH_TYPE_POS_OVERRIDE.
# Source: {label} per-intersection result CSVs, unanimous across every run
# since 2026-08-27 -- (car,bus,truck)=({car},{bus},{truck}).
# Precedence in Simulation_Stats._resolve_type:
#     VEH_TYPE_ID_* (explicit ANG id) > VEH_TYPE_POS_* (these) > name > scan
# A pin larger than the model's vehicle-type count is ignored with a warning,
# so opening the wrong model cannot silently relabel a class.
# To pin by ANG object id instead (wins over these), read it on the console:
#     oid = ANGConnGetObjectIdByType(AKIConvertFromAsciiString("bus"),
#                                    AKIConvertFromAsciiString("GKVehicle"), False)
#     print(oid, AKIVehGetVehTypeInternalPosition(oid))
# then set VEH_TYPE_ID_BUS = oid here. Never guess that id.
# ---------------------------------------------------------------------------
VEH_TYPE_POS_CAR = {car}
VEH_TYPE_POS_TRUCK = {truck}
VEH_TYPE_POS_BUS = {bus}
'''


def patch(rel, label, car, truck, bus):
    p = os.path.join(HERE, rel)
    if not os.path.isfile(p):
        print('  MISSING %s' % rel)
        return False
    with open(p, 'rb') as fh:
        data = fh.read()
    if MARK in data:
        print('  ALREADY_PINNED %s' % rel)
        return False
    E = b'\r\n' if b'\r\n' in data else b'\n'
    if data and not data.endswith(E):
        data += E
    block = TEMPLATE.format(label=label, car=car, truck=truck, bus=bus)
    data += block.replace('\n', E.decode()).encode('utf-8')
    with open(p, 'wb') as fh:
        fh.write(data)
    print('  PINNED %s  car=%d truck=%d bus=%d' % (rel, car, truck, bus))
    return True


def main():
    n = 0
    for rel, label, car, truck, bus in TARGETS:
        n += 1 if patch(rel, label, car, truck, bus) else 0
    print('CHANGED %d file(s)' % n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
