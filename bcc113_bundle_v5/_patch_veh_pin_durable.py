"""Make the vehicle-type position pins durable and correctly ordered.

TWO DEFECTS IN THE FIRST PASS, BOTH FOUND BY CHECKING INSTEAD OF ASSUMING:

1. ORDER. The pin block was inserted BEFORE the ANG-id check, so a
   VEH_TYPE_ID_* override would be ignored -- the opposite of what the comment,
   the run_config note and the patch header all claim. Fix: check the id first.

2. DURABILITY. run_config.py is the wrong home for a pin:
     * batch_runner.write_run_config() builds that file from scratch (content,
       then all mode toggles) and rewrites it on every sweep, so an appended
       pin is lost the next time a ladder runs;
     * run_config is propagated into engine.py's globals, NOT into
       Simulation_Stats', and _resolve_type reads globals().get(...) in ITS OWN
       module -- so VEH_TYPE_ID_BUS has never been visible there at all.
   Fix: keep the pin as a module constant in each corridor's Simulation_Stats.py
   (that file is never regenerated, and it is already per-corridor). A run_config
   value still wins if propagation is ever extended to this module, because the
   exec would simply rebind the same global.

Idempotent, CRLF-aware, backed up per file.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# per corridor: (file, label, car, truck, bus)
TARGETS = (
    ('logan_road_new/Simulation_Stats.py', 'Logan', 1, 2, 3),
    ('kg/Simulation_Stats.py', 'KG', 1, 3, 4),
)

ORDER_OLD = b'''            if pos_key:
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
            _p = _pos_from_id(globals().get(id_key, 0))
            if _p > 0:
                return _p                       # explicit ID wins outright'''

ORDER_NEW = b'''            _p = _pos_from_id(globals().get(id_key, 0))
            if _p > 0:
                return _p                       # explicit ANG id wins outright
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
                        return _pp'''

CONST_MARK = b'VEH_TYPE_POS_CONSTANTS_20261109'

CONST_BLOCK = b'''# VEHICLE-TYPE POSITION PINS (2026-11-09) -- see _resolve_type in finalise_init.
# Permanent per-corridor constants, because run_config.py cannot carry them:
# batch_runner.write_run_config() rewrites that file from scratch on every sweep
# (an appended pin is lost), and run_config is propagated into engine.py's
# globals rather than this module's -- which is also why the pre-existing
# VEH_TYPE_ID_BUS lookup in _resolve_type has always read 0 here.
# Measured, not guessed: (car,bus,truck) = __TUPLE__, unanimous across every
# per-intersection result CSV in this corridor since 2026-08-27 (CarTypePos/
# BusTypePos/TruckTypePos, written from these very attributes), with zero
# non-positive and zero colliding rows. A run_config value, if ever propagated
# into this module, rebinds these and wins.
VEH_TYPE_POS_CONSTANTS_20261109 = True
VEH_TYPE_POS_CAR = __CAR__
VEH_TYPE_POS_TRUCK = __TRUCK__
VEH_TYPE_POS_BUS = __BUS__
'''

ANCHORS = (b'_MAX_BUS_TRIP_S = 1200.0', b'_CAR_SCAN_INTERVAL_S = 5.0')


def patch(rel, label, car, truck, bus):
    p = os.path.join(HERE, rel)
    if not os.path.isfile(p):
        print('  MISSING %s' % rel)
        return False
    with open(p, 'rb') as fh:
        data = fh.read()
    E = b'\r\n' if b'\r\n' in data else b'\n'

    def L(b):
        return b.replace(b'\n', E)

    changed = False

    if L(ORDER_NEW) not in data:
        n = data.count(L(ORDER_OLD))
        if n != 1:
            raise SystemExit('%s: precedence anchor count=%d' % (rel, n))
        data = data.replace(L(ORDER_OLD), L(ORDER_NEW), 1)
        changed = True
        print('  ORDER  %s: ANG id now checked before the pin' % rel)

    if CONST_MARK not in data:
        anchor = None
        for a in ANCHORS:
            if data.count(L(a)) == 1:
                anchor = L(a)
                break
        if anchor is None:
            raise SystemExit('%s: no unique constant anchor' % rel)
        # Distinct tokens, NOT bare words: 'CAR' also matches inside
        # 'VEH_TYPE_POS_CAR' and would produce VEH_TYPE_POS_1.
        block = L(CONST_BLOCK)
        for tok, val in ((b'__TUPLE__', b'(%d,%d,%d)' % (car, bus, truck)),
                         (b'__CAR__', str(car).encode()),
                         (b'__TRUCK__', str(truck).encode()),
                         (b'__BUS__', str(bus).encode())):
            assert tok in block, tok
            block = block.replace(tok, val)
        assert b'__' not in block, 'unsubstituted token left in block'
        data = data.replace(anchor, block + anchor, 1)
        changed = True
        print('  CONST  %s: pins car=%d truck=%d bus=%d' % (rel, car, truck, bus))

    if not changed:
        print('  ALREADY_DURABLE %s' % rel)
        return False

    bak = p + '.bak_vehpin2_20261109'
    if not os.path.exists(bak):
        shutil.copy2(p, bak)
    tmp = p + '.vehpin2.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, p)
    print('  WROTE  %s' % rel)
    return True


def main():
    n = 0
    for t in TARGETS:
        n += 1 if patch(*t) else 0
    print('CHANGED %d file(s)' % n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
