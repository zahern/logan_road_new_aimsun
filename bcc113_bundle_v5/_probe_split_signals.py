"""Read-only probe: do the two split crossings run one signal program?

    n10158157 <-> n10158160   (12.1 m apart)
    n11118206 <-> n11127644   (15.2 m apart)

Paste into the Aimsun console once the model is loaded (a running simulation is
not required for the plan structure; current phase/clock need a run):

    exec(open(r"C:/Users/ahernz/github_for_aimsun/bcc113_bundle_v5/_probe_split_signals.py").read())

Nothing here writes to the model, changes a phase, or touches the controller:
every call is a getter. Run it twice a few seconds apart while the sim is live
and the second call also prints how the phase clocks moved, which is what
separates "one coordinated program" from "two independent ones". The previous
clock samples are kept in split_signal_probe_state.json under the temp dir so
they survive a re-paste; delete that file to start the comparison over.

What it prints per junction
    control type   Aimsun's control type; 2 or 3 = External (what the TSP engine
                   requires), anything else = the node is not externally driven
    phases         count and the normal duration of each phase, plus the cycle
    signal groups  count per phase and the group ids, if the API exposes them

How to read the verdict line
    same phase count AND same durations -> the two halves run the same plan
    different durations                -> they cannot be one program
    offsets stay fixed across calls    -> coordinated (fixed offset)
    offsets drift                      -> independent controllers
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

PAIRS = [(10158157, 10158160), (11118206, 11127644)]

# Clock samples must survive a fresh namespace: exec'ing this file again builds a
# new module dict, so an in-memory dict would never see the previous call.
_STATE = os.path.join(tempfile.gettempdir(), 'split_signal_probe_state.json')


def _load_prev():
    try:
        with open(_STATE) as fh:
            return {int(k): float(v) for k, v in json.load(fh).items()}
    except Exception:                           # noqa: BLE001 - absent file is normal
        return {}


def _save_prev(d):
    try:
        with open(_STATE, 'w') as fh:
            json.dump({str(k): v for k, v in d.items()}, fh)
    except Exception:                           # noqa: BLE001 - never fail the probe
        pass


def _resolve(name):
    """Find an Aimsun API symbol without assuming which namespace holds it.

    The engine is exec'd into some module's globals depending on how the run was
    started, so scan sys.modules for the first namespace that has the symbol.
    """
    for mod in list(sys.modules.values()):
        d = getattr(mod, '__dict__', None)
        if isinstance(d, dict) and name in d:
            return d[name]
    for d in (globals(), vars(sys.modules['__main__'])):
        if name in d:
            return d[name]
    raise NameError(name)


def _try(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:                      # noqa: BLE001 - report, never raise
        return 'ERR:%r' % (e,)


def _durations(jid, n_phases):
    """Normal/min/max duration for each phase, via the signature the engine uses."""
    out = []
    try:
        doublep = _resolve('doublep')
        get_dur = _resolve('ECIGetDurationsPhase')
    except NameError:
        return ['n/a (doublep or ECIGetDurationsPhase not in any namespace)']
    for ph in range(n_phases):
        try:
            normal, dmax, dmin = doublep(), doublep(), doublep()
            get_dur(jid, ph, 0.0, normal, dmax, dmin)
            out.append((round(float(normal.value()), 1),
                        round(float(dmin.value()), 1),
                        round(float(dmax.value()), 1)))
        except Exception as e:                  # noqa: BLE001
            out.append('ERR:%r' % (e,))
    return out


def _describe(jid):
    rec = {'id': jid}
    ct = _try(_resolve('ECIGetControlType'), jid)
    rec['control_type'] = ct
    n = _try(_resolve('ECIGetNumberPhases'), jid)
    rec['n_phases'] = n
    rec['durations'] = _durations(jid, n) if isinstance(n, int) and n > 0 else []
    rec['phase'] = _try(_resolve('ECIGetCurrentPhase'), jid)
    rec['clock'] = _try(_resolve('ECIGetStartingTimePhase'), jid)

    # groups per phase: the 3-argument form the engine itself calls (14 sites)
    if isinstance(n, int) and n > 0:
        try:
            ng = _resolve('ECIGetNbSignalGroupsPhaseofJunction')
            rec['groups_per_phase'] = [_try(ng, jid, p, 0.0) for p in range(n)]
        except NameError:
            rec['groups_per_phase'] = 'n/a (reader not in any namespace)'
    return rec


def main():
    try:
        _resolve('ECIGetControlType')
    except NameError:
        print('[SPLIT] Aimsun API not in scope - load the model, or paste this '
              'after the engine has been exec\'d, then call it again.')
        return

    try:
        build = _resolve('ENGINE_BUILD')
    except NameError:
        build = '?'
    print('[SPLIT] engine=%s' % build)
    prev = _load_prev()
    cur = dict(prev)          # accumulate across pairs: one save, not one per pair

    for a, b in PAIRS:
        recs = [_describe(a), _describe(b)]
        for r in recs:
            print('\n[SPLIT] junction %d' % r['id'])
            print('   control type : %s   (2/3 = External; engine needs External)'
                  % r['control_type'])
            print('   phases       : %s' % r['n_phases'])
            if r['durations']:
                total = sum(d[0] for d in r['durations'] if isinstance(d, tuple))
                for i, d in enumerate(r['durations']):
                    print('     phase %-2d normal=%-6s min=%-6s max=%-6s'
                          % (i, d[0], d[1], d[2]) if isinstance(d, tuple)
                          else '     phase %-2d %s' % (i, d))
                print('   cycle (sum of normals) : %.1f s' % total)
            if 'groups_per_phase' in r:
                print('   signal groups/phase    : %s' % r['groups_per_phase'])
            print('   current phase : %s   phase clock : %s'
                  % (r['phase'], r['clock']))

        d0 = [d[0] for d in recs[0]['durations'] if isinstance(d, tuple)]
        d1 = [d[0] for d in recs[1]['durations'] if isinstance(d, tuple)]
        if not d0 or not d1:
            verdict = ('INCONCLUSIVE - durations could not be read, so this call '\
                       'says nothing about the controllers')
        elif d0 == d1 and len(d0) == len(d1):
            verdict = 'SAME phase count and durations -> same plan structure'
        else:
            verdict = ('DIFFERENT durations (%s vs %s) -> two distinct programs'
                       % (d0, d1))
        print('\n[SPLIT] %d vs %d : %s' % (a, b, verdict))

        # clock movement between calls: fixed offset = coordinated
        for r in recs:
            if isinstance(r['clock'], (int, float)):
                cur[r['id']] = float(r['clock'])
                if r['id'] in prev:
                    print('   %d clock moved %.1f s since the previous call'
                          % (r['id'], float(r['clock']) - prev[r['id']]))
        c0, c1 = recs[0]['clock'], recs[1]['clock']
        if isinstance(c0, (int, float)) and isinstance(c1, (int, float)):
            print('   relative phase-clock offset (a-b): %.1f s'
                  % (float(c0) - float(c1)))
        print('\n[SPLIT] run this again a few seconds later: a constant relative\n'
              '        offset means one coordinated master; a drifting one means\n'
              '        the two nodes are on independent controllers.')

    _save_prev(cur)


main()
