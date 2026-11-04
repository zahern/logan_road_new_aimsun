r"""tsp_games.py -- one candidate set, many games. Pure stdlib, no Aimsun.

Every game-theoretic TSP arm decides the same thing: which (if any) of the
candidate actions at a junction to commit, against the disagreement point
NO_ACTION (the plan as it runs). This module separates the SOLUTION CONCEPT
from the candidate generation and the payoff model, so arms differ ONLY in the
concept and can be compared like for like.

Candidate payoffs (pax.s, relative to NO_ACTION), as dctsp_nash_bargain
builds them:
    B   = phase-total benefit of the action (bus + mainline through traffic)
    C   = cross-street cost it imposes (>= 0)
    b   = bus-only part of B
so the two players' gains are
    u_bus = b
    u_car = (B - b) - C          mainline car gain minus cross-street cost
    joint = B - C = u_bus + u_car

Concepts (GAME_SOLUTION):
  nash               Asymmetric Nash bargaining, exactly the legacy M4 rule
                     (_nash_bargain_pick, no threat): over B > r*C, maximise
                     B^pB * (B - C)^pC.
  utilitarian        Cooperative TU game: maximise joint (legacy coop 'joint').
  nash_welfare       Cooperative: maximise max(0,u_bus)*max(0,u_car) (legacy
                     coop 'nash').
  egalitarian        Cooperative Rawlsian: maximise min(u_bus, u_car)
                     (legacy coop 'maxmin').
  kalai_smorodinsky  Bargaining with proportional gains: over the feasible set,
                     normalise each player's gain by its range from the
                     worst feasible / disagreement payoff to its ideal, and
                     maximise the smaller normalised gain.
  stackelberg_bus    Leader-follower, bus leads: maximise u_bus subject to the
                     cars (follower) accepting -- u_car within the tolerance.
  stackelberg_car    Leader-follower, cars lead: maximise u_car subject to the
                     action still helping the bus (u_bus > 0).
  noncoop_grant      Non-cooperative request/allowance game per action family
                     (GE, INS, ...): the bus requests r seconds, the cross
                     street allows c seconds, the grant is min(r, c). Players
                     best-respond until a pure Nash equilibrium is reached;
                     the equilibrium grant is committed (none if 0 or cycling).

Feasibility shared by every cooperative / leader-follower concept (the same
side-payment coalition rule GAME_COOP uses): joint > 0, and each player may
lose at most  tol_abs + tol_frac * joint  (a transfer the winner can fund).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

CONCEPTS = ('nash', 'utilitarian', 'nash_welfare', 'egalitarian',
            'kalai_smorodinsky', 'stackelberg_bus', 'stackelberg_car',
            'noncoop_grant')


@dataclass
class Cand:
    family: str          # 'GE', 'INS', 'GREEN_REALLOC', 'EARLY_RED', ...
    duration: float
    B: float             # phase-total benefit (pax.s)
    C: float             # cross cost (pax.s)
    b: float             # bus-only benefit (pax.s)

    @property
    def u_bus(self) -> float:
        return float(self.b)

    @property
    def u_car(self) -> float:
        return float(self.B) - float(self.b) - float(self.C)

    @property
    def joint(self) -> float:
        return float(self.B) - float(self.C)


@dataclass
class Params:
    p_bus: float = 1.0
    p_car: float = 1.0
    net_ratio: float = 1.0       # nash: admit only B > net_ratio * C
    tol_bus_abs: float = 0.0
    tol_car_abs: float = 0.0
    tol_bus_frac: float = 0.25
    tol_car_frac: float = 0.25
    fair_w: float = 0.0          # utilitarian: - fair_w * |u_bus - u_car|
    max_iter: int = 50


def _feasible(c: Cand, p: Params) -> bool:
    j = c.joint
    if j <= 0.0:
        return False
    return (c.u_bus >= -(p.tol_bus_abs + p.tol_bus_frac * j)
            and c.u_car >= -(p.tol_car_abs + p.tol_car_frac * j))


def _argmax(scores: Dict[int, float]) -> Optional[int]:
    if not scores:
        return None
    return max(sorted(scores), key=lambda i: scores[i])   # ties -> lowest index


def solve(concept: str, cands: Sequence[Cand], p: Params = None
          ) -> Tuple[Optional[int], dict]:
    """Return (index into cands or None = NO_ACTION, diagnostics)."""
    p = p or Params()
    concept = (concept or '').strip().lower()
    diag = {'concept': concept, 'n': len(cands), 'nfeas': 0, 'score': None,
            'reason': ''}
    if concept not in CONCEPTS:
        raise ValueError('unknown GAME_SOLUTION %r (one of %s)' % (concept, CONCEPTS))
    if not cands:
        diag['reason'] = 'no candidates'
        return None, diag

    if concept == 'nash':
        sc = {}
        for i, c in enumerate(cands):
            B, C = max(0.0, c.B), max(0.0, c.C)
            if B > 1e-6 and B - C > 1e-6 and B >= p.net_ratio * C:
                sc[i] = (B ** p.p_bus) * ((B - C) ** p.p_car)
        diag['nfeas'] = len(sc)
        i = _argmax(sc)
        diag['score'] = sc.get(i)
        diag['reason'] = '' if i is not None else 'no action with B > r*C'
        return i, diag

    if concept == 'noncoop_grant':
        return _noncoop_grant(cands, p, diag)

    feas = [i for i, c in enumerate(cands) if _feasible(c, p)]
    diag['nfeas'] = len(feas)
    if not feas:
        diag['reason'] = 'no action passes the side-payment feasibility'
        return None, diag

    if concept == 'utilitarian':
        sc = {i: cands[i].joint - p.fair_w * abs(cands[i].u_bus - cands[i].u_car)
              for i in feas}
    elif concept == 'nash_welfare':
        sc = {i: max(0.0, cands[i].u_bus) * max(0.0, cands[i].u_car) for i in feas}
    elif concept == 'egalitarian':
        sc = {i: min(cands[i].u_bus, cands[i].u_car) for i in feas}
    elif concept == 'kalai_smorodinsky':
        ub = [cands[i].u_bus for i in feas]
        uc = [cands[i].u_car for i in feas]
        lo_b, lo_c = min(min(ub), 0.0), min(min(uc), 0.0)     # incl. disagreement
        hi_b, hi_c = max(ub), max(uc)
        rb = max(hi_b - lo_b, 1e-9)
        rc = max(hi_c - lo_c, 1e-9)
        sc = {i: min((cands[i].u_bus - lo_b) / rb, (cands[i].u_car - lo_c) / rc)
              for i in feas}
    elif concept == 'stackelberg_bus':
        sc = {i: cands[i].u_bus for i in feas}               # follower acceptance = feas
    elif concept == 'stackelberg_car':
        sc = {i: cands[i].u_car for i in feas if cands[i].u_bus > 0.0}
        if not sc:
            diag['reason'] = 'no feasible action helps the bus'
            return None, diag
    else:  # pragma: no cover
        raise ValueError(concept)
    i = _argmax(sc)
    diag['score'] = sc.get(i)
    return i, diag


def _noncoop_grant(cands, p, diag):
    """Pure Nash equilibrium of the request/allowance game, per family.

    Strategies are the family's durations plus 0. Outcome = the candidate whose
    duration is min(request, allowance) (0 -> NO_ACTION, payoff (0, 0)).
    Bus utility u_bus, cross utility u_car of that outcome. Best-response
    iteration from (request = longest, allowance = longest). A family whose
    iteration cycles has no pure equilibrium and is dropped. Across families
    the bus (the requester) chooses the family whose equilibrium it prefers.
    """
    fams: Dict[str, List[int]] = {}
    for i, c in enumerate(cands):
        fams.setdefault(c.family, []).append(i)
    best = None          # (u_bus, -index, index)
    eq_info = {}
    for fam, idx in fams.items():
        by_d = {}
        for i in idx:
            by_d.setdefault(round(float(cands[i].duration), 3), i)
        durs = [0.0] + sorted(by_d)

        def outcome(r, c):
            g = min(r, c)
            return None if g <= 0.0 else by_d.get(round(g, 3))

        def pay(i):
            return (0.0, 0.0) if i is None else (cands[i].u_bus, cands[i].u_car)

        r, a = durs[-1], durs[-1]
        seen = set()
        ok = False
        for _ in range(int(p.max_iter)):
            if (r, a) in seen:
                break
            seen.add((r, a))
            r_new = max(durs, key=lambda x: (pay(outcome(x, a))[0], -x))
            a_new = max(durs, key=lambda x: (pay(outcome(r_new, x))[1], -x))
            if r_new == r and a_new == a:
                ok = True
                break
            r, a = r_new, a_new
        if not ok:
            eq_info[fam] = 'no pure equilibrium'
            continue
        i = outcome(r, a)
        eq_info[fam] = 'grant %.0fs' % min(r, a) if i is not None else 'grant 0'
        if i is not None:
            diag['nfeas'] += 1
            key = (cands[i].u_bus, -i)
            if best is None or key > best[:2]:
                best = (cands[i].u_bus, -i, i)
    diag['equilibria'] = eq_info
    if best is None:
        diag['reason'] = 'every family equilibrium grants 0 s'
        return None, diag
    diag['score'] = best[0]
    return best[2], diag


# --------------------------------------------------------------------------- #
# Self-test                                                                    #
# --------------------------------------------------------------------------- #
def _check(c, m):
    if not c:
        raise AssertionError(m)


def _legacy_nash_pick(frontier, p_T, p_C, ratio=1.0):
    """Mirror of specialized_modes._nash_bargain_pick with threat 0."""
    best, bv = None, 0.0
    for i, (bps, cpc) in enumerate(frontier):
        bps, cpc = max(0.0, bps), max(0.0, cpc)
        sur = bps - cpc
        if bps > 1e-6 and sur > 1e-6 and bps >= ratio * cpc:
            v = (bps ** p_T) * (sur ** p_C)
            if best is None or v > bv:
                best, bv = i, v
    return best


def _legacy_coop_pick(frontier, obj, p):
    best, bj = None, -1e18
    for i, (bt, cpc, bus) in enumerate(frontier):
        joint = bt - cpc
        car = joint - bus
        tb = p.tol_bus_abs + p.tol_bus_frac * max(joint, 0.0)
        tc = p.tol_car_abs + p.tol_car_frac * max(joint, 0.0)
        if bus < -tb or car < -tc or joint <= 0.0:
            continue
        if obj == 'maxmin':
            s = min(bus, car)
        elif obj == 'nash':
            s = max(0.0, bus) * max(0.0, car)
        else:
            s = joint - p.fair_w * abs(bus - car)
        if s > bj:
            bj, best = s, i
    return best


def _selftest():
    import random
    rng = random.Random(7)
    p = Params()
    # 1. equivalence with the legacy engine rules on random frontiers
    for _ in range(2000):
        n = rng.randint(1, 8)
        cs = []
        for k in range(n):
            b = rng.uniform(-50, 400)
            B = b + rng.uniform(-100, 600)
            C = rng.uniform(0, 700)
            cs.append(Cand(rng.choice(['GE', 'INS']), float(rng.randint(1, 12)), B, C, b))
        fr2 = [(c.B, c.C) for c in cs]
        fr3 = [(c.B, c.C, c.b) for c in cs]
        _check(solve('nash', cs, p)[0] == _legacy_nash_pick(fr2, 1.0, 1.0), 'nash != legacy')
        _check(solve('utilitarian', cs, p)[0] == _legacy_coop_pick(fr3, 'joint', p), 'joint')
        _check(solve('nash_welfare', cs, p)[0] == _legacy_coop_pick(fr3, 'nash', p), 'nash_w')
        _check(solve('egalitarian', cs, p)[0] == _legacy_coop_pick(fr3, 'maxmin', p), 'maxmin')
        for k in ('kalai_smorodinsky', 'stackelberg_bus', 'stackelberg_car'):
            i, d = solve(k, cs, p)
            _check(i is None or _feasible(cs[i], p), '%s picked infeasible' % k)
    print('  2000 random frontiers: nash / utilitarian / nash_welfare / egalitarian '
          'match the engine\'s legacy rules; new concepts stay feasible')

    # 2. one frontier where the concepts DISAGREE (they are distinct games)
    cs = [
        Cand('GE', 2.0, 300.0, 100.0, 280.0),   # bus-heavy, cars lose a little
        Cand('GE', 6.0, 900.0, 300.0, 700.0),   # biggest joint, cars lose
        Cand('GE', 4.0, 500.0, 150.0, 200.0),   # balanced: both gain
        Cand('INS', 8.0, 400.0, 350.0, 380.0),  # bus gains, cars lose a lot
    ]
    picks = {k: solve(k, cs, p)[0] for k in CONCEPTS}
    print('  picks on the demo frontier:', picks)
    _check(picks['stackelberg_bus'] in (1, 3) and picks['utilitarian'] == 1, picks)
    _check(picks['egalitarian'] == 2 and picks['nash_welfare'] == 2, picks)
    _check(picks['stackelberg_car'] == 2, picks)
    _check(len(set(picks.values())) >= 3, 'concepts should not all coincide')

    # 3. non-cooperative grant game: equilibrium = the shorter preferred grant
    g = [Cand('GE', d, B, C, b) for d, B, C, b in
         ((1, 120, 10, 100), (2, 260, 40, 200), (3, 330, 120, 260), (4, 360, 260, 300))]
    i, d = solve('noncoop_grant', g, p)
    _check(i == 1, (i, d))       # bus wants 4 s, cars best at 2 s -> grant 2 s
    print('  non-cooperative grant equilibrium:', d['equilibria'])

    # 4. NO_ACTION when nothing is feasible / beneficial
    bad = [Cand('GE', 3.0, 100.0, 400.0, 90.0)]
    for k in CONCEPTS:
        _check(solve(k, bad, p)[0] is None, '%s acted on a net-harmful action' % k)
    print('OK: legacy equivalence, distinct concepts, non-cooperative equilibrium, '
          'NO_ACTION on net-harmful sets.')


if __name__ == '__main__':
    _selftest()
