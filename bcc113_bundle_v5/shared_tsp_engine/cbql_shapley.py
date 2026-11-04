r"""cbql_shapley.py -- CBQL-TSP core (Qin & Zhang, arXiv:2404.19683).

STANDALONE, pure-Python, offline-testable core of the cooperative-game +
Q-learning controller the operator asked to replicate. It holds NO Aimsun
dependency so it can be unit-tested on Windows (RULE 1 safe); the engine wires
it in as controller mode ``CBQL_SHAPLEY`` in a later step.

What it implements from the paper
---------------------------------
* Intersection-dependent PHASE DERIVATION (Sec. 3.3, Fig. 4/5): classify every
  phase of a junction from its real movements and tag the PRIORITY phase (the
  one carrying the bus route). Works for ANY phase set -- KG's 8-phase and
  Logan's different structure both -- because it reads the junction's own
  phases, it does not assume a fixed template.
* MDP state S_k = {psi, lambda, T, Q[phase]}  (eq. 6).
* Cooperative game: marginal contribution C (eq. 19), Shapley value
  v_Shapley (eqs. 20-21), and the Shapley-RATIO state-transition probabilities
  (the paper's novel mechanism: Shapley ratios set P(s'|s,a)).
* Shapley Q-update  H Q(s,a) = (1-a)Q + a[R + g*v_Shapley]  (eq. 22).
* REWARD = delay, single metric (eq. 9; the agent minimises its delay),
  matching the operator's delay-only decision.

The engine, when wiring CBQL_SHAPLEY, supplies: (1) a JunctionSpec built from
the live phase/signal-group data, (2) per-phase measured delay for the reward,
(3) the measured per-phase flow Q for the state. This module owns the policy.
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Movement / phase description -- corridor-agnostic                            #
# --------------------------------------------------------------------------- #
# A movement is (approach, turn): approach is a compass/label string, turn is
# one of 'through', 'left', 'right'. A phase serves a set of movements.
Movement = Tuple[str, str]


@dataclass
class PhaseSpec:
    idx: int
    movements: Tuple[Movement, ...]
    min_green_s: float = 6.0
    max_green_s: float = 60.0


@dataclass
class JunctionSpec:
    """What the engine hands this module for one intersection."""
    junction_id: int
    phases: Tuple[PhaseSpec, ...]
    cycle_s: float
    # movements the bus route uses at this junction (0+); empty => no bus phase
    bus_movements: Tuple[Movement, ...] = ()


# --------------------------------------------------------------------------- #
# Intersection-dependent phase derivation (Sec. 3.3)                           #
# --------------------------------------------------------------------------- #
PHASE_THROUGH = "through"
PHASE_PROTECTED_LEFT = "protected_left"
PHASE_FREE_LEFT = "free_left"       # permissive left shared with opposing through
PHASE_MIXED = "mixed"
PHASE_RIGHT = "right_only"


@dataclass
class PhaseStructure:
    junction_id: int
    n_phases: int
    phase_types: Dict[int, str]              # phase idx -> classification
    priority_phases: Tuple[int, ...]         # phases serving a bus movement
    non_priority_phases: Tuple[int, ...]
    cycle_s: float

    def is_priority(self, phase_idx: int) -> bool:
        return phase_idx in self.priority_phases


def _classify_phase(ph: PhaseSpec) -> str:
    turns = {t for (_a, t) in ph.movements}
    approaches_through = {a for (a, t) in ph.movements if t == PHASE_THROUGH}
    has_left = "left" in turns
    has_through = PHASE_THROUGH in turns
    if not ph.movements:
        return PHASE_MIXED
    if turns == {"right"}:
        return PHASE_RIGHT
    if has_left and not has_through:
        # a left served without any through in the same phase == protected left
        return PHASE_PROTECTED_LEFT
    if has_left and has_through:
        # left shares green with a through movement => permissive / free left,
        # UNLESS the through is on the SAME approach(es) only (then still
        # protected for the cross direction). Heuristic: if the through comes
        # from a different approach than the left, it is opposing => free left.
        left_apps = {a for (a, t) in ph.movements if t == "left"}
        if approaches_through - left_apps:
            return PHASE_FREE_LEFT
        return PHASE_PROTECTED_LEFT
    if has_through and not has_left:
        return PHASE_THROUGH
    return PHASE_MIXED


def derive_phase_structure(spec: JunctionSpec) -> PhaseStructure:
    """Derive the phase set / classification / priority phase for ONE junction.

    Intersection-dependent: reads this junction's own phases, so it works for
    any corridor (KG, Logan, ...) without a fixed 8-phase assumption.
    """
    types = {ph.idx: _classify_phase(ph) for ph in spec.phases}
    bus_set = set(spec.bus_movements)
    priority = tuple(
        ph.idx for ph in spec.phases
        if bus_set and bus_set.intersection(ph.movements)
    )
    non_priority = tuple(ph.idx for ph in spec.phases if ph.idx not in priority)
    return PhaseStructure(
        junction_id=spec.junction_id,
        n_phases=len(spec.phases),
        phase_types=types,
        priority_phases=priority,
        non_priority_phases=non_priority,
        cycle_s=spec.cycle_s,
    )


# --------------------------------------------------------------------------- #
# MDP state  S_k = {psi, lambda, T, Q[phase]}  (eq. 6)                         #
# --------------------------------------------------------------------------- #
@dataclass
class CbqlState:
    green_phase: int                 # psi : current green phase index
    green_ratio: float               # lambda : green/cycle of current phase
    cycle_s: float                   # T
    phase_flow: Tuple[float, ...]    # Q[0..P-1] measured per-phase flow (veh/h)

    def encode(self, flow_bin: float = 300.0,
               ratio_bins: int = 5, cycle_bin: float = 20.0) -> tuple:
        """Discretise to a hashable Q-table key (keeps the table finite)."""
        lam = min(ratio_bins - 1, int(self.green_ratio * ratio_bins))
        cyc = int(round(self.cycle_s / cycle_bin))
        q = tuple(int(f // flow_bin) for f in self.phase_flow)
        return (self.green_phase, lam, cyc, q)


# --------------------------------------------------------------------------- #
# Cooperative game: marginal contribution, Shapley value, transition ratios    #
# --------------------------------------------------------------------------- #
def marginal_contribution(player, coalition: Sequence,
                          v: Callable[[frozenset], float]) -> float:
    """C = v(S) - v(S \\ {i})   (eq. 19)."""
    S = frozenset(coalition)
    return v(S) - v(S - {player})


def shapley_values(players: Sequence,
                   v: Callable[[frozenset], float]) -> Dict:
    """Shapley value of every player (eqs. 20-21).

    v is the characteristic function: value (e.g. negative total delay, higher
    == better) of a coalition. Exact over all permutations; players is small
    (phase groups or a handful of signals), so this is cheap.
    """
    players = list(players)
    n = len(players)
    phi = {p: 0.0 for p in players}
    if n == 0:
        return phi
    # weight omega(|S|) = |S|!(n-|S|-1)!/n!  for the coalition S not containing i
    fact = [math.factorial(k) for k in range(n + 1)]
    others = {p: [q for q in players if q != p] for p in players}
    for p in players:
        acc = 0.0
        rest = others[p]
        for k in range(len(rest) + 1):
            w = fact[k] * fact[n - k - 1] / fact[n]
            for combo in itertools.combinations(rest, k):
                S = frozenset(combo)
                acc += w * (v(S | {p}) - v(S))
        phi[p] = acc
    return phi


def transition_probs_from_shapley(phi: Dict) -> Dict:
    """Shapley RATIOS -> state-transition probabilities (the paper's mechanism).

    Shift so the smallest value is >=0 (Shapley values can be negative), then
    normalise. Degenerate all-equal case falls back to uniform.
    """
    if not phi:
        return {}
    lo = min(phi.values())
    shifted = {p: (val - lo) + 1e-9 for p, val in phi.items()}
    tot = sum(shifted.values()) or 1.0
    return {p: s / tot for p, s in shifted.items()}


# --------------------------------------------------------------------------- #
# Shapley Q-update (eq. 22) and the agent                                      #
# --------------------------------------------------------------------------- #
def shapley_q_update(q_sa: float, reward: float, shapley_v: float,
                     alpha: float, gamma: float) -> float:
    """H Q(s,a) = (1-a) Q(s,a) + a [ R + g * v_Shapley ]   (eq. 22)."""
    return (1.0 - alpha) * q_sa + alpha * (reward + gamma * shapley_v)


@dataclass
class CbqlShapleyAgent:
    """One intersection's CBQL-TSP controller (policy only).

    REWARD = delay, single metric: callers pass reward = -delay (or -delay
    delta) so that maximising Q minimises delay, per eq. 9 and the operator's
    delay-only decision.
    """
    structure: PhaseStructure
    alpha: float = 0.3
    gamma: float = 0.9
    epsilon: float = 0.05
    q: Dict[tuple, Dict[int, float]] = field(default_factory=dict)
    rng: random.Random = field(default_factory=lambda: random.Random(12345))

    def _row(self, key: tuple) -> Dict[int, float]:
        return self.q.setdefault(
            key, {ph: 0.0 for ph in self.structure.phase_types})

    def select_phase(self, state: CbqlState,
                     shapley_bias: Optional[Dict] = None) -> int:
        """Pick the next green phase. Shapley ratios bias the choice toward the
        members (priority/non-priority) the cooperative game favours."""
        key = state.encode()
        row = self._row(key)
        if self.rng.random() < self.epsilon:
            return self.rng.choice(list(row))
        # combine learned Q with the Shapley-ratio transition bias
        def score(ph):
            s = row[ph]
            if shapley_bias:
                grp = "P" if self.structure.is_priority(ph) else "N"
                s += math.log(max(shapley_bias.get(grp, 1e-6), 1e-6))
            return s
        return max(row, key=score)

    def update(self, state: CbqlState, phase: int, reward: float,
               shapley_v: float) -> None:
        key = state.encode()
        row = self._row(key)
        row[phase] = shapley_q_update(
            row.get(phase, 0.0), reward, shapley_v, self.alpha, self.gamma)


# --------------------------------------------------------------------------- #
# Convenience: build the priority/non-priority 2-player game for a junction    #
# --------------------------------------------------------------------------- #
def priority_game_value(structure: PhaseStructure,
                        phase_delay: Dict[int, float]) -> Callable[[frozenset], float]:
    """Characteristic function for the {priority, non-priority} coalition game.

    Value of a coalition = negative summed delay of the phases that coalition
    controls (higher == less delay == better). phase_delay maps phase idx ->
    measured delay (veh*s or pax*s). This is the delay-only payoff.
    """
    pri = set(structure.priority_phases)
    non = set(structure.non_priority_phases)

    def v(coalition: frozenset) -> float:
        served = set()
        if "P" in coalition:
            served |= pri
        if "N" in coalition:
            served |= non
        return -sum(phase_delay.get(ph, 0.0) for ph in served)

    return v


# --------------------------------------------------------------------------- #
# Self-test (run locally: python cbql_shapley.py)                              #
# --------------------------------------------------------------------------- #
def _demo_kg_junction() -> JunctionSpec:
    """An 8-phase junction (KG-style): N/S and E/W through + protected lefts."""
    P = PhaseSpec
    phases = (
        P(0, (("N", "through"), ("S", "through"))),
        P(1, (("N", "left"), ("S", "left"))),           # protected left
        P(2, (("E", "through"), ("W", "through"))),
        P(3, (("E", "left"), ("W", "left"))),           # protected left
        P(4, (("N", "through"), ("N", "left"))),         # single-approach
        P(5, (("S", "through"), ("S", "left"))),
        P(6, (("E", "through"), ("E", "left"))),
        P(7, (("W", "through"), ("W", "left"))),
    )
    # the bus runs N->S through the corridor: priority phase = 0 (and 4/5 touch N/S through)
    return JunctionSpec(99, phases, cycle_s=120.0,
                        bus_movements=(("N", "through"),))


def _demo_logan_junction() -> JunctionSpec:
    """A different (6-phase) junction to prove corridor-independence."""
    P = PhaseSpec
    phases = (
        P(0, (("N", "through"), ("S", "through"), ("N", "left"))),  # free left
        P(1, (("E", "through"), ("W", "through"))),
        P(2, (("E", "left"), ("W", "left"))),
        P(3, (("N", "right"),)),
        P(4, (("S", "through"),)),
        P(5, (("W", "through"), ("W", "left"))),
    )
    # bus runs E->W through: priority = phase 1
    return JunctionSpec(17308, phases, cycle_s=150.0,
                        bus_movements=(("W", "through"),))


def _selftest() -> None:
    for spec, label in ((_demo_kg_junction(), "KG-8phase"),
                        (_demo_logan_junction(), "Logan-6phase")):
        st = derive_phase_structure(spec)
        print("\n[%s] junction=%d  n_phases=%d  cycle=%.0fs"
              % (label, st.junction_id, st.n_phases, st.cycle_s))
        for ph in sorted(st.phase_types):
            tag = "  <== PRIORITY (bus)" if st.is_priority(ph) else ""
            print("   phase %d: %-14s%s" % (ph, st.phase_types[ph], tag))
        assert st.priority_phases, "priority phase not found for " + label

        # cooperative game over {priority, non-priority} with synthetic delay
        phase_delay = {ph: 100.0 + 20.0 * ph for ph in st.phase_types}
        v = priority_game_value(st, phase_delay)
        phi = shapley_values(["P", "N"], v)
        probs = transition_probs_from_shapley(phi)
        assert abs(sum(probs.values()) - 1.0) < 1e-6, "transition probs must sum to 1"
        print("   Shapley:", {k: round(x, 1) for k, x in phi.items()},
              " transition ratios:", {k: round(x, 3) for k, x in probs.items()})

        # a few Q-updates to prove the learner runs and moves
        agent = CbqlShapleyAgent(st)
        s = CbqlState(green_phase=0, green_ratio=0.4, cycle_s=st.cycle_s,
                      phase_flow=tuple(300.0 * (i + 1) for i in range(st.n_phases)))
        before = dict(agent._row(s.encode()))
        for _ in range(50):
            a = agent.select_phase(s, shapley_bias=probs)
            # reward = -delay of the chosen phase (delay-only, minimise delay)
            reward = -phase_delay[a]
            agent.update(s, a, reward, shapley_v=phi.get(
                "P" if st.is_priority(a) else "N", 0.0))
        after = agent._row(s.encode())
        moved = sum(1 for ph in after if abs(after[ph] - before.get(ph, 0.0)) > 1e-6)
        print("   learner updated %d/%d phase Q-values; chosen-phase Q now: %s"
              % (moved, st.n_phases,
                 {k: round(v2, 1) for k, v2 in list(after.items())[:4]}))
        assert moved > 0, "Q-learner did not update"
    print("\nOK: phase derivation + Shapley game + Q-update all pass "
          "for both corridors.")


if __name__ == "__main__":
    _selftest()
