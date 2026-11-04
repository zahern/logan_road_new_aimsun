"""End-to-end offline test of the game solution concepts THROUGH the real
decider (specialized_modes.dctsp_nash_bargain), 2026-11-05.

Pulls dctsp_nash_bargain and the legacy _nash_bargain_pick out of
specialized_modes.py with ast and drives them with a stub junction whose four
green-extension candidates have known payoffs -- no Aimsun:

    python -I _test_game_concepts.py           (exit 0 = PASS)

Checks
  1. every GAME_SOLUTION commits exactly what tsp_games picks for the same
     candidates (the wiring passes B, C, b through unchanged)
  2. every committed / held decision logs one [GAME_SOLVE] line
  3. GAME_SOLUTION='nash' == the legacy local Nash bargain (M4 rule, no
     corridor tier) and GAME_SOLUTION='' still runs the legacy path
  4. the games are behaviourally distinct on this junction
  5. a net-harmful candidate set -> NO_ACTION under every game
  6. nothing swallowed
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, 'shared_tsp_engine')
sys.path.insert(0, ENG)
import tsp_games  # noqa: E402

src = io.open(os.path.join(ENG, 'specialized_modes.py'), encoding='utf-8').read()
tree = ast.parse(src)
seg = {}
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name in ('dctsp_nash_bargain',
                                                     '_nash_bargain_pick'):
        seg[n.name] = ast.get_source_segment(src, n)
assert len(seg) == 2, seg.keys()

LOG, HELD, SWALLOWED = [], [], []
# payoffs per (type, seconds): (bus benefit b, mainline extra B-b, cross cost C)
PAY = {}


def _eval(self, at, ap, sigma, nad, eta, wrong_phase=False, remaining_red_s=0.0):
    if at == 'NO_ACTION':
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    b, extra, C = PAY.get((at, float(ap)), (0.0, 0.0, 1e9))
    return (0.0, 0.0, 0.0, b, C, 0.0, 0.0)


def _phase_total(self, at, ap, bps):
    b, extra, C = PAY.get((at, float(ap)), (0.0, 0.0, 0.0))
    return float(bps) + extra


ns = {
    '_tsp_games': tsp_games,
    'DCTSP_RL_ACTION_SPACE': [('NO_ACTION', 0.0), ('GE', 2.0), ('GE', 4.0),
                              ('GE', 6.0), ('GE', 8.0), ('INS', 8.0)],
    '_dctsp_eval_action': _eval,
    '_nash_phase_total_bps': _phase_total,
    '_xt_nash_projection': lambda self, *a: {'bus_occ': 40.0, 'eff_delay': 60.0,
                                             'wrong_phase': False, 'monitor': False,
                                             'min_delay_s': 0.0},
    '_log_func': lambda self, m, force=False: LOG.append(m),
    '_nash_held_log': lambda self, t, v, cand, d, stage: HELD.append(stage),
    '_nash_held_gate': lambda *a, **k: HELD.append('gate'),
    '_note_swallow_spm': lambda self, tag, exc=None: SWALLOWED.append((tag, repr(exc))),
    '_continuous_corridor_penalty': lambda *a, **k: None,
    '_nash_duration_search': lambda *a, **k: [],
    'action_label': lambda at, ap: '%s_%g' % (at, ap),
    # flags (read through globals().get inside the decider)
    'NASH_INTEGER_DURATIONS': False, 'NASH_CORRIDOR_MODE': False,
    'NASH_COOPERATIVE': False, 'NASH_MIN_GAIN_S': 0.0, 'NASH_NET_GATE_RATIO': 1.0,
    'NASH_BUS_WEIGHT': 1.0, 'NASH_CROSS_WEIGHT': 1.0, 'GAME_SOLUTION': '',
    'GAME_TOL_BUS_FRAC': 0.25, 'GAME_TOL_CAR_FRAC': 0.25,
}
ns['globals'] = lambda: ns
exec(seg['_nash_bargain_pick'] + '\n\n' + seg['dctsp_nash_bargain'], ns)
decide = ns['dctsp_nash_bargain']


class Jct(object):
    id = 7


J = Jct()
fails = []


def check(name, cond, detail=''):
    print('  %-4s %s %s' % ('ok' if cond else 'FAIL', name, detail))
    if not cond:
        fails.append(name)


def run(concept):
    ns['GAME_SOLUTION'] = concept
    n0 = len(LOG)
    out = decide(J, 100.0, 0.0, 0, 30.0, 11, 1, 60.0, 0.0)
    gl = [m for m in LOG[n0:] if m.startswith('[GAME_SOLVE]')]
    return (out[0], float(out[1])), gl


# A junction where the games disagree (bus benefit, mainline extra, cross cost)
PAY.update({
    ('GE', 2.0): (280.0, 20.0, 100.0),    # bus-heavy, cars lose a little
    ('GE', 4.0): (200.0, 300.0, 150.0),   # balanced: both gain
    ('GE', 6.0): (700.0, 200.0, 300.0),   # biggest joint, cars lose
    ('GE', 8.0): (300.0, 0.0, 600.0),     # net-harmful
})
cands = [tsp_games.Cand('GE', d, b + x, C, b) for (t, d), (b, x, C) in sorted(PAY.items())]
print('1-4 four GE candidates through dctsp_nash_bargain')
picks = {}
for k in tsp_games.CONCEPTS:
    (at, ap), gl = run(k)
    i, _ = tsp_games.solve(k, cands, tsp_games.Params())
    want = ('NO_ACTION', 0.0) if i is None else ('GE', cands[i].duration)
    picks[k] = (at, ap)
    check('1 %-18s commits the game pick %s' % (k, want), (at, ap) == want, (at, ap))
    check('2 %-18s logs [GAME_SOLVE]' % k, len(gl) == 1, gl[:1])
(at, ap), gl = run('')
check('3 legacy path still runs (no [GAME_SOLVE])', not gl and at == 'GE', (at, ap))
check('3b GAME_SOLUTION=nash == legacy local Nash bargain', picks['nash'] == (at, ap),
      (picks['nash'], (at, ap)))
check('4 games are distinct (>= 3 different decisions)',
      len(set(picks.values())) >= 3, picks)
print('     decisions:', {k: '%s_%g' % v for k, v in picks.items()})
print('     e.g.', [m for m in LOG if m.startswith('[GAME_SOLVE]')][1])

print('5 net-harmful candidates only')
PAY.clear()
PAY.update({('GE', 2.0): (50.0, 0.0, 400.0), ('GE', 4.0): (80.0, 0.0, 900.0)})
for k in tsp_games.CONCEPTS:
    (at, ap), gl = run(k)
    check('5 %-18s holds' % k, at == 'NO_ACTION', (at, ap))
check('6 nothing swallowed', not SWALLOWED, SWALLOWED[:3])
if fails:
    sys.exit('FAIL: %s' % fails)
print('PASS')
