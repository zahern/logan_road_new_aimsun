"""Correct the run_config pin block: documentation, not the effective pin.

The first pass appended the pins to run_config.py as if that made them take
effect. It does not, for two independent reasons:

  * batch_runner.write_run_config() rebuilds run_config.py from scratch on every
    sweep, so an appended line survives only until the next ladder run;
  * run_config is exec'd into engine.py's namespace, but _resolve_type lives in
    Simulation_Stats and reads globals() of ITS OWN module, so the names are not
    visible there -- the pre-existing VEH_TYPE_ID_BUS hook has therefore never
    fired.

The values stay (harmless, and effective if propagation is ever extended), but
the comment now says where the real pin lives. Idempotent, CRLF-aware.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = b'VEH_TYPE_POS_NOTE_20261109'

TARGETS = (('logan_road_new/run_config.py', 3), ('kg/run_config.py', 4))

NOTE = b'''
# NOTE (2026-11-09): these lines are DOCUMENTATION, not the effective pin.
# batch_runner.write_run_config() rewrites this file from scratch on every
# sweep, and this file is propagated into engine.py's globals -- while
# _resolve_type reads globals() of Simulation_Stats, where these names are not
# visible. The effective per-corridor pins are the VEH_TYPE_POS_CAR/_TRUCK/_BUS
# constants at the top of Simulation_Stats.py. Keep the two in sync.
VEH_TYPE_POS_NOTE_20261109 = True
'''


def main():
    n = 0
    for rel, bus in TARGETS:
        p = os.path.join(HERE, rel)
        if not os.path.isfile(p):
            print('  MISSING %s' % rel)
            continue
        with open(p, 'rb') as fh:
            data = fh.read()
        if MARK in data:
            print('  ALREADY_NOTE %s' % rel)
            continue
        E = b'\r\n' if b'\r\n' in data else b'\n'
        anchor = b'VEH_TYPE_POS_BUS = ' + str(bus).encode()
        if data.count(anchor) != 1:
            print('  ANCHOR_PROBLEM %s count=%d' % (rel, data.count(anchor)))
            continue
        i = data.index(anchor)
        eol = data.index(E, i) + len(E)
        note = NOTE.replace(b'\n', E)
        bak = p + '.bak_rcnote_20261109'
        if not os.path.exists(bak):
            shutil.copy2(p, bak)
        data = data[:eol] + note + data[eol:]
        tmp = p + '.rcnote.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, p)
        print('  NOTED %s' % rel)
        n += 1
    print('CHANGED %d file(s)' % n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
