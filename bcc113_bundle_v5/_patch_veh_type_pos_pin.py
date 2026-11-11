"""Pin vehicle-type POSITIONS in both corridors' Simulation_Stats.py.

WHY NOT VEH_TYPE_ID_BUS
    VEH_TYPE_ID_BUS is consumed as _pos_from_id(AKIVehGetVehTypeInternalPosition(id)),
    i.e. it needs the Aimsun GKVehicle ANG object id. The only such id recorded in
    this repo is Logan's CAR ("Car - bcc" = 74453); no bus id was ever written
    down, and the model stores its vehicle types in the binary .ang. A guessed id
    either resolves to -1 (inert) or to another type's position (catastrophic:
    the car/bus split drives every passenger-weighted metric).

WHAT THIS DOES INSTEAD
    Adds VEH_TYPE_POS_CAR/_TRUCK/_BUS: the measured INTERNAL POSITION of each
    type, validated against AKIVehGetNbVehTypes() so a model swap cannot silently
    label the wrong class. Precedence inside _resolve_type becomes

        VEH_TYPE_ID_* (explicit ANG id)  >  VEH_TYPE_POS_* (measured pin)
        >  already-resolved position     >  name lookup

    and a pin collision across car/bus/truck is reported loudly.

    Measured positions (union of every per-intersection result CSV, 2026-08-27 ..
    2026-11-09): Logan (car,bus,truck) = (1,3,2); KG = (1,4,3). Zero non-positive
    or colliding rows in 57,588 intersection-rows.

Idempotent, CRLF-aware, byte-anchored, temp file + os.replace, backup per file.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ('logan_road_new/Simulation_Stats.py', 'kg/Simulation_Stats.py')
MARK = b"'VEH_TYPE_POS_CAR'"

SIG_OLD = b'''        def _resolve_type(cur_pos, id_key, name_key, extra_names):
            _p = _pos_from_id(globals().get(id_key, 0))'''

SIG_NEW = b'''        def _resolve_type(cur_pos, id_key, name_key, extra_names, pos_key=''):
            # POSITION PIN (VEH_TYPE_POS_* in run_config, 2026-11-09): the measured
            # internal position of this type, so resolution stops depending on
            # SWIG name decoding and on the corridor folder basename that keys
            # VEH_TYPE_POS_OVERRIDE. Order: explicit ANG object id (VEH_TYPE_ID_*)
            # > this pin > the already-resolved position > name lookup. A pin that
            # exceeds the model's type count is ignored, so swapping models cannot
            # silently label the wrong class.
            if pos_key:
                _pp = _sanitize_type_pos(globals().get(pos_key, 0))
                if _pp > 0:
                    try:
                        _nb = int(AKIVehGetNbVehTypes())
                    except Exception:
                        _nb = 0
                    if _nb > 0 and _pp > _nb:
                        self._print(f"[STATS] WARNING {pos_key}={_pp} exceeds the "
                                    f"{_nb} vehicle types in this model -- ignoring "
                                    f"the pin")
                    else:
                        return _pp
            _p = _pos_from_id(globals().get(id_key, 0))'''

CAR_OLD = b'''        self._car_pos   = _resolve_type(self._car_pos,   'VEH_TYPE_ID_CAR',
                                        'VEH_TYPE_NAME_CAR',   ('Car - bcc', 'Car-bcc'))'''
CAR_NEW = b'''        self._car_pos   = _resolve_type(self._car_pos,   'VEH_TYPE_ID_CAR',
                                        'VEH_TYPE_NAME_CAR',   ('Car - bcc', 'Car-bcc'),
                                        'VEH_TYPE_POS_CAR')'''

TRUCK_OLD = b'''        self._truck_pos = _resolve_type(self._truck_pos, 'VEH_TYPE_ID_TRUCK',
                                        'VEH_TYPE_NAME_TRUCK', ('Truck - bcc', 'Truck-bcc'))'''
TRUCK_NEW = b'''        self._truck_pos = _resolve_type(self._truck_pos, 'VEH_TYPE_ID_TRUCK',
                                        'VEH_TYPE_NAME_TRUCK', ('Truck - bcc', 'Truck-bcc'),
                                        'VEH_TYPE_POS_TRUCK')'''

BUS_OLD_A = b"'VEH_TYPE_NAME_BUS',   ('Bus - bcc', 'Bus-bcc'))"
BUS_NEW_A = (b"'VEH_TYPE_NAME_BUS',   ('Bus - bcc', 'Bus-bcc'),\n"
             b"                                        'VEH_TYPE_POS_BUS')")
BUS_OLD_B = b"('Bus - bcc', 'Bus-bcc', 'bus', 'BUS', 'Bus'))"
BUS_NEW_B = (b"('Bus - bcc', 'Bus-bcc', 'bus', 'BUS', 'Bus'),\n"
             b"                                        'VEH_TYPE_POS_BUS')")

GUARD = b'''        # Colliding pins are worse than no pin: the car/bus split drives every
        # passenger-weighted metric, so report it instead of trusting it.
        if len({self._car_pos, self._bus_pos, self._truck_pos}) < 3:
            self._print("[STATS] WARNING vehicle-type positions COLLIDE "
                        f"(car={self._car_pos} bus={self._bus_pos} "
                        f"truck={self._truck_pos}) -- check VEH_TYPE_POS_* pins")
        if self._bus_pos > 0 and not self._bus_type_name:
            _ppin = int(globals().get('VEH_TYPE_POS_BUS', 0) or 0)
            self._bus_type_name = (f'bus(pos pin {_ppin})'
                                   if _ppin == self._bus_pos else 'bus(override)')
'''

# where the guard goes: after bus/ car / truck resolution, before the names are
# backfilled (Logan) or before the override names are set (KG)
GUARD_ANCHORS = (
    b'        # Logan Road: known Aimsun GKVehicle ANG id for "Car - bcc" (74453) as a',
    b"        if self._car_pos > 0 and not self._car_type_name:\n"
    b"            self._car_type_name = 'car(override)'",
)


def patch(path):
    with open(path, 'rb') as fh:
        data = fh.read()
    if MARK in data:
        print('  ALREADY_PATCHED %s' % path)
        return False
    E = b'\r\n' if b'\r\n' in data else b'\n'

    def L(b):
        return b.replace(b'\n', E)

    def swap(name, old, new):
        old, new = L(old), L(new)
        n = data.count(old)
        if n != 1:
            raise SystemExit('%s: anchor %s count=%d' % (path, name, n))
        return data.replace(old, new, 1)

    before = len(data)
    data = swap('_resolve_type signature', SIG_OLD, SIG_NEW)
    data = swap('car call', CAR_OLD, CAR_NEW)
    data = swap('truck call', TRUCK_OLD, TRUCK_NEW)
    if data.count(L(BUS_OLD_A)) == 1:
        data = data.replace(L(BUS_OLD_A), L(BUS_NEW_A), 1)
    elif data.count(L(BUS_OLD_B)) == 1:
        data = data.replace(L(BUS_OLD_B), L(BUS_NEW_B), 1)
    else:
        raise SystemExit('%s: bus call anchor count=%d/%d'
                         % (path, data.count(L(BUS_OLD_A)), data.count(L(BUS_OLD_B))))
    placed = 0
    for anc in GUARD_ANCHORS:
        if data.count(L(anc)) == 1:
            data = data.replace(L(anc), L(GUARD) + L(anc), 1)
            placed = 1
            break
    if not placed:
        raise SystemExit('%s: guard anchor not found' % path)

    bak = path + '.bak_vehpin_20261109'
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    tmp = path + '.vehpin.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, path)
    print('  PATCHED %s  %d -> %d bytes  (EOL=%r, backup %s)'
          % (path, before, len(data), E, os.path.basename(bak)))
    return True


def main():
    changed = 0
    for f in FILES:
        p = os.path.join(HERE, f)
        if not os.path.isfile(p):
            print('  MISSING %s' % f)
            continue
        changed += 1 if patch(p) else 0
    print('CHANGED %d file(s)' % changed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
