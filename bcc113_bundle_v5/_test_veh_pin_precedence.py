"""Prove the patched _resolve_type precedence without Aimsun.

Extracts the (patched) nested _resolve_type out of each corridor's
Simulation_Stats.py and runs it against stubs, so the ordering is tested rather
than assumed:

    VEH_TYPE_ID_* (explicit ANG id) > VEH_TYPE_POS_* > current position > name

Also checks the stale-pin guard (pin > model's type count must be ignored, not
applied) and that a pin of 0 leaves the old behaviour untouched.
"""
from __future__ import print_function

import io
import os
import re
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ('logan_road_new/Simulation_Stats.py', 'kg/Simulation_Stats.py')
FAIL = []


def check(name, got, want):
    ok = got == want
    print('  %-46s %s (got %r, want %r)'
          % (name, 'ok' if ok else 'FAIL', got, want))
    if not ok:
        FAIL.append(name)


def _san(p):
    """Mirror Simulation_Stats._sanitize_type_pos: any junk -> -1, never raises."""
    try:
        v = int(p)
    except Exception:
        return -1
    return v if v > 0 else -1


class FakeSelf(object):
    def __init__(self):
        self.msgs = []

    def _print(self, m):
        self.msgs.append(m)


def extract(path):
    src = io.open(path, encoding='utf-8', errors='replace').read().splitlines()
    start = next(i for i, s in enumerate(src) if 'def _resolve_type(' in s)
    end = None
    for i in range(start + 1, min(len(src), start + 80)):
        if src[i].strip() == 'return cur_pos':      # final line of the nested def
            end = i + 1
            break
    assert end, 'could not find the end of _resolve_type in %s' % path
    body = textwrap.dedent('\n'.join(src[start:end]))
    assert 'pos_key' in body, 'patch missing in %s' % path
    return body


def harness(path, pos_pin, id_pos, cur, name_pos, nb_types=6):
    """Run the extracted resolver with the given configuration."""
    self_ = FakeSelf()
    ns = {
        'self': self_,
        'AKIVehGetNbVehTypes': lambda: nb_types,
        '_sanitize_type_pos': _san,
        '_pos_from_id': lambda i: (id_pos if int(i) > 0 else -1),
        '_fallback_type_pos': lambda nm: name_pos,
        'VEH_TYPE_POS_BUS': pos_pin,
        'VEH_TYPE_ID_BUS': (1 if id_pos > 0 else 0),
        'VEH_TYPE_NAME_BUS': '',
    }
    code = extract(path)
    exec(compile(code, path, 'exec'), ns)
    got = ns['_resolve_type'](cur, 'VEH_TYPE_ID_BUS', 'VEH_TYPE_NAME_BUS',
                              ('Bus - bcc', 'Bus-bcc'), 'VEH_TYPE_POS_BUS')
    return got, self_.msgs


def main():
    for path in FILES:
        p = os.path.join(HERE, path)
        if not os.path.isfile(p):
            print('MISSING %s' % p)
            return 1
        print('### %s' % path)
        # 1. pin wins over an unresolved scan (cur=-1) and over the name lookup
        got, _ = harness(p, 3, -1, -1, name_pos=5)
        check('pin 3, no id, cur -1, name->5', got, 3)
        # 2. explicit ANG id wins over the pin
        got, _ = harness(p, 3, 4, -1, name_pos=5)
        check('id->4 beats pin 3', got, 4)
        # 3. stale pin above the model type count is ignored, name still applies
        got, msgs = harness(p, 9, -1, -1, name_pos=5, nb_types=6)
        check('stale pin 9 > nb 6 is ignored', got, 5)
        check('stale pin warns', any('WARNING' in m for m in msgs), True)
        # 4. pin 0 = old behaviour: keep an already-good position
        got, _ = harness(p, 0, -1, 2, name_pos=5)
        check('pin 0 keeps cur=2', got, 2)
        # 5. pin 0, nothing resolved, name applies
        got, _ = harness(p, 0, -1, -1, name_pos=5)
        check('pin 0, unresolved, name->5', got, 5)
        # 6. non-numeric pin is sanitised away, not crashed on
        got, _ = harness(p, 'abc', -1, 2, name_pos=5)
        check('garbage pin falls through to cur=2', got, 2)
        print('')

    print('RESULT: %d failure(s)%s' % (len(FAIL), (': ' + ', '.join(FAIL)) if FAIL else ''))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
