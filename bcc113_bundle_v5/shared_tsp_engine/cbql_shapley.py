r"""cbql_shapley.py -- CBQL-TSP core (Qin & Zhang, arXiv:2404.19683).

STANDALONE, pure-Python, offline-testable core of the cooperative-game +
Q-learning controller the operator asked to replicate. It holds NO Aimsun
dependency so it can be unit-tested on Windows (RULE 1 safe); the engine wires
it in as controller mode ``CBQL_SHAPLEY`` in a later step.

What it implements from the paper
---------------------------------
* Intersection-dependent PHASE DERIVATION (Sec. 3.3, Fig. 4/5): classify every
  phase of a junction from its real movements and tag the PRIORITY phases (the
  ones carrying the bus route). Works for ANY phase set -- KG's 8-phase and
  Logan's different structure both -- because it reads the junction's own
  phases, it does not assume a fixed template.
* MDP state S_k = {psi, lambda, T, Q[phase]}  (eq. 6); actions = switch to
  phase i (Sec. 4.1).
* TWO QL controllers per junction (Sec. 4.1/4.2): "P" for the priority
  signals and "N" for the non-priority signals, each with its own Q-table,
  policy and reward.
* The cooperative game DEFINED BY Q (Sec. 4.2): marginal contribution C
  (eq. 19) and Shapley value (eqs. 20-21) over the two controllers, computed
  on their Q-values (see coalition_cost_fn for the characteristic function).
* Shapley-RATIO transition probabilities: the joint next-phase distribution
  is the Shapley-ratio-weighted mix of the two policies (Sec. 6).
* Shapley Q-update  H Q(s,a) = (1-a)Q + a[R + g*v_Shapley(s')]  (eq. 22),
  with v_Shapley taken at the NEXT state, in place of max Q(s').
* Policy hill-climbing (eq. 18).
* REWARDS = the paper's two objectives (Sec. 3.1): P gets -(priority-phase
  delay + w * max bus delay), N gets -(non-priority-phase delay).

Where the paper is silent (characteristic function, how ratios become
probabilities, eq. 17) the choice made here is documented at that code.

The engine supplies: (1) a JunctionSpec built from the live phase/signal-group
data, (2) per-phase measured delay and the max bus delay for the rewards,
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
    # CTM feed (optional). When phase_queue is given, Q[j] in the key is the
    # CTM standing queue of phase j (veh) instead of the measured flow, and
    # bus_level (0/1/2 = none / one / several buses on the priority
    # approaches, from the CTM bus density) is added -- the paper's "presence
    # and urgency of priority vehicles" (Sec. 4.1).
    phase_queue: Optional[Tuple[float, ...]] = None
    bus_level: int = 0
    queue_bin_veh: float = 4.0
    queue_levels: int = 5

    def encode(self, flow_bin: float = 300.0,
               ratio_bins: int = 5, cycle_bin: float = 20.0) -> tuple:
        """Discretise to a hashable Q-table key (keeps the table finite)."""
        lam = min(ratio_bins - 1, int(self.green_ratio * ratio_bins))
        cyc = int(round(self.cycle_s / cycle_bin))
        if self.phase_queue is not None:
            b = max(float(self.queue_bin_veh), 1e-6)
            top = max(int(self.queue_levels) - 1, 0)
            q = tuple(min(top, int(max(0.0, x) // b)) for x in self.phase_queue)
            return (self.green_phase, lam, cyc, q, min(int(self.bus_level), 2))
        q = tuple(int(f // flow_bin) for f in self.phase_flow)
        return (self.green_phase, lam, cyc, q)


# --------------------------------------------------------------------------- #
# Cooperative game primitives: marginal contribution, Shapley value            #
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


# --------------------------------------------------------------------------- #
# The Q-defined cooperative game (Sec. 4.2, eqs. 19-21)                        #
# --------------------------------------------------------------------------- #
# Players are the two QL controllers: "P" (priority signals -- the phases that
# carry the bus route) and "N" (non-priority signals). Paper: "Using the
# Shapley Value function to calculate the marginal contributions C of the
# members in the current game as defined by Q."
#
# INTERPRETATION (the paper gives no formula for the characteristic function;
# this is ours and must be stated as such). We use the COST form of the game,
# because every Q here is a discounted sum of NEGATIVE rewards (delays):
#
#     cost_i(s, a) = max(0, -Q_i(s, a))          (expected delay-to-go for i)
#     c(T)         = min_a  sum_{i in T} cost_i(s, a),   c({}) = 0
#
# i.e. the delay a coalition is left with when its members agree on ONE next
# phase. Only one phase can be green, so P and N alone each get their own best
# phase, but together they must share one -- c({P,N}) >= max(c(P), c(N)).
# That shared-phase constraint is exactly the P/N conflict the paper models;
# it makes the game non-additive, so the Shapley value is non-trivial (the
# earlier delay-sum game was additive: phi_i was just -delay_i).
#
# Shapley COST shares psi_i >= 0 (proof: psi_P = 0.5[c(P) + c(PN) - c(N)]
# >= 0.5 c(P) since c(PN) >= c(N)). The paper's "Shapley value ratios" are
# then psi_i / sum(psi): the share of the coalition's delay attributable to
# each player. A literal ratio is well-defined here (all shares >= 0), so no
# softmax/temperature is needed.
PLAYERS = ("P", "N")


def coalition_cost_fn(q_by_player: Dict[str, Dict[int, float]]
                      ) -> Callable[[frozenset], float]:
    """c(T) = min over the shared next phase of the coalition's summed cost."""
    actions = None
    for row in q_by_player.values():
        actions = set(row) if actions is None else actions & set(row)
    actions = sorted(actions or ())

    def c(T: frozenset) -> float:
        if not T or not actions:
            return 0.0
        return min(sum(max(0.0, -float(q_by_player[i][a])) for i in T)
                   for a in actions)

    return c


def shapley_cost_shares(q_by_player: Dict[str, Dict[int, float]]) -> Dict:
    """Shapley cost share psi_i of each player (eqs. 19-21 on the cost game)."""
    return shapley_values(list(q_by_player), coalition_cost_fn(q_by_player))


def shapley_ratios(psi: Dict, floor: float = 0.05) -> Dict:
    """psi_i / sum(psi), floored so neither player's policy is ever silenced.

    All-zero shares (fresh table, or no delay anywhere) -> uniform.
    """
    if not psi:
        return {}
    n = len(psi)
    tot = sum(max(0.0, float(v)) for v in psi.values())
    if tot <= 0.0:
        return {p: 1.0 / n for p in psi}
    raw = {p: max(0.0, float(v)) / tot for p, v in psi.items()}
    f = min(max(float(floor), 0.0), 1.0 / n)
    return {p: f + (1.0 - n * f) * r for p, r in raw.items()}


# --------------------------------------------------------------------------- #
# Q-update (eq. 22) and policy hill-climbing (eq. 18)                          #
# --------------------------------------------------------------------------- #
def shapley_q_update(q_sa: float, reward: float, shapley_v: float,
                     alpha: float, gamma: float) -> float:
    """H Q(s,a) = (1-a) Q(s,a) + a [ R + g * v_Shapley ]   (eq. 22).

    v_Shapley is the player's Shapley VALUE at the NEXT state s' of the game
    defined by Q -- it plays the role max_a' Q(s', a') plays in plain
    Q-learning. In the cost form v_Shapley = -psi_i(s').
    """
    return (1.0 - alpha) * q_sa + alpha * (reward + gamma * shapley_v)


def policy_hill_climb(pi_row: Dict[int, float], q_row: Dict[int, float],
                      lr: float, floor: float = 0.01) -> Dict[int, float]:
    """eq. 18: +lr on argmax_a Q(s,a), -lr/(|A|-1) on every other action,
    then clip to [floor, 1] and renormalise so pi stays a distribution and
    no action can be extinguished for good. Ties go to the lowest phase id.
    """
    acts = sorted(pi_row)
    if len(acts) < 2:
        return {a: 1.0 for a in acts}
    best = max(acts, key=lambda a: (q_row.get(a, 0.0), -a))
    step_other = lr / (len(acts) - 1)
    new = {a: pi_row[a] + (lr if a == best else -step_other) for a in acts}
    new = {a: min(1.0, max(float(floor), p)) for a, p in new.items()}
    tot = sum(new.values())
    return {a: p / tot for a, p in new.items()}


# --------------------------------------------------------------------------- #
# Rewards (item 3): both of the paper's objectives                             #
# --------------------------------------------------------------------------- #
def player_rewards(structure: PhaseStructure, phase_delay: Dict[int, float],
                   bus_delay_s: float = 0.0, bus_w: float = 1.0
                   ) -> Dict[str, float]:
    """R_P = -(mean delay on priority phases + bus_w * max bus delay)
       R_N = -(mean delay on non-priority phases)

    The paper's two objectives (Sec. 3.1): minimise total delay, and minimise
    the MAXIMUM delay of priority vehicles. Each QL controller is rewarded on
    the vehicles it serves; the bus term goes to the priority player.
    Per-group MEAN, not sum, so the group with more phases is not penalised
    merely for its phase count. Missing phases are skipped, not read as 0.
    """
    def _mean(phs):
        vals = [float(phase_delay[p]) for p in phs if p in phase_delay]
        return (sum(vals) / len(vals)) if vals else 0.0

    return {
        "P": -(_mean(structure.priority_phases)
               + float(bus_w) * max(0.0, float(bus_delay_s or 0.0))),
        "N": -_mean(structure.non_priority_phases),
    }


def player_rewards_ctm(structure: PhaseStructure,
                       car_delay_vs: Dict[int, float],
                       bus_delay_vs: Dict[int, float],
                       horizon_s: float, bus_w: float = 1.0
                       ) -> Dict[str, float]:
    """Rewards from the two-class CTM's predicted delay (veh.s over the
    horizon) for the action taken -- R(s,a) = E[R | s, a] (eq. 9) with the
    CTM as the model.

       R_P = -( mean_{p in P} car_delay_p + bus_w * sum_{p in P} bus_delay_p ) / H
       R_N = -( mean_{p in N} car_delay_p ) / H

    Dividing by the horizon H gives "average vehicles held back", so the scale
    does not move when the horizon is changed. Cars: per-group MEAN (same
    reason as player_rewards). Buses: SUM over the priority phases -- each bus
    is a discrete priority vehicle, and averaging would dilute one late bus.
    bus_w is the bus-vs-car weight (e.g. BusOcc / CarOcc for passengers).
    """
    H = max(float(horizon_s), 1e-6)

    def _mean(phs):
        vals = [float(car_delay_vs[p]) for p in phs if p in car_delay_vs]
        return (sum(vals) / len(vals)) if vals else 0.0

    bus = sum(float(bus_delay_vs.get(p, 0.0)) for p in structure.priority_phases)
    return {
        "P": -(_mean(structure.priority_phases) + float(bus_w) * bus) / H,
        "N": -_mean(structure.non_priority_phases) / H,
    }


# --------------------------------------------------------------------------- #
# The CBQL-TSP controller for one junction (Fig. 6 loop)                       #
# --------------------------------------------------------------------------- #
@dataclass
class CbqlTspController:
    """Two QL controllers (P, N) + the Shapley game that mixes their policies.

    Loop per decision step (Fig. 6):
      1. learn(prev_state, prev_action, rewards, state):
           psi(s') from the Q-defined game -> eq. 22 for EACH player with its
           own reward and v_Shapley = -psi_i(s'); then eq. 18 on that
           player's policy at prev_state.
      2. act(state):
           ratios w_i = psi_i(s) / sum psi (floored); the joint transition
           distribution  p(a) = sum_i w_i * pi_i(s, a)  -- "Shapley value
           ratios determine the MDP state transition probabilities" --
           and the next phase is sampled from it.

    Not implemented from the paper: eq. 17 (the a_t estimate of the share of
    returns hitting Q_max). It feeds nothing else the paper defines and its
    three cases are not mutually consistent as printed.
    """
    structure: PhaseStructure
    alpha: float = 0.3
    gamma: float = 0.9
    policy_lr: float = 0.05
    policy_floor: float = 0.01
    ratio_floor: float = 0.05
    sample: bool = True
    seed: int = 12345
    q: Dict[str, Dict[tuple, Dict[int, float]]] = field(default_factory=dict)
    pi: Dict[str, Dict[tuple, Dict[int, float]]] = field(default_factory=dict)

    def __post_init__(self):
        self.rng = random.Random(self.seed)
        for p in PLAYERS:
            self.q.setdefault(p, {})
            self.pi.setdefault(p, {})

    @property
    def actions(self) -> List[int]:
        return sorted(self.structure.phase_types)

    def _q_row(self, player: str, key: tuple) -> Dict[int, float]:
        return self.q[player].setdefault(key, {a: 0.0 for a in self.actions})

    def _pi_row(self, player: str, key: tuple) -> Dict[int, float]:
        n = len(self.actions) or 1
        return self.pi[player].setdefault(
            key, {a: 1.0 / n for a in self.actions})

    def game(self, state: CbqlState) -> Tuple[Dict, Dict]:
        """(psi cost shares, floored ratios) of the game at `state`."""
        key = state.encode()
        psi = shapley_cost_shares({p: self._q_row(p, key) for p in PLAYERS})
        return psi, shapley_ratios(psi, self.ratio_floor)

    def learn(self, prev_state: CbqlState, prev_action: int,
              rewards: Dict[str, float], state: CbqlState) -> Dict:
        """eq. 22 + eq. 18 for both players. Returns psi at the new state."""
        if int(prev_action) not in self.structure.phase_types:
            return {}
        psi_next, _ = self.game(state)
        pkey = prev_state.encode()
        for p in PLAYERS:
            row = self._q_row(p, pkey)
            row[prev_action] = shapley_q_update(
                row[prev_action], float(rewards.get(p, 0.0)),
                -float(psi_next.get(p, 0.0)), self.alpha, self.gamma)
            self.pi[p][pkey] = policy_hill_climb(
                self._pi_row(p, pkey), row, self.policy_lr, self.policy_floor)
        return psi_next

    def joint_policy(self, state: CbqlState) -> Tuple[Dict[int, float], Dict]:
        key = state.encode()
        _psi, w = self.game(state)
        mix = {a: 0.0 for a in self.actions}
        for p in PLAYERS:
            row = self._pi_row(p, key)
            for a in self.actions:
                mix[a] += w[p] * row[a]
        return mix, w

    def act(self, state: CbqlState) -> Tuple[int, Dict[int, float], Dict]:
        """(next phase, joint transition distribution, Shapley ratios)."""
        mix, w = self.joint_policy(state)
        acts = self.actions
        if not acts:
            return int(state.green_phase), mix, w
        if self.sample:
            r = self.rng.random()
            acc = 0.0
            for a in acts:
                acc += mix[a]
                if r < acc:
                    return a, mix, w
            return acts[-1], mix, w
        return max(acts, key=lambda a: (mix[a], -a)), mix, w


# --------------------------------------------------------------------------- #
# Self-test (run locally: python -I cbql_shapley.py)                           #
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
    return JunctionSpec(17308, phases, cycle_s=150.0,
                        bus_movements=(("W", "through"),))


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _test_game() -> None:
    # Fresh table: no delay anywhere -> uniform ratios, never a 0/1 lock.
    _check(shapley_ratios(shapley_cost_shares(
        {"P": {1: 0.0, 2: 0.0}, "N": {1: 0.0, 2: 0.0}})) == {"P": 0.5, "N": 0.5},
        "fresh table must give 0.5/0.5")
    # Conflict: P wants phase 1, N wants phase 2. Each alone pays 10; together
    # they must share one phase and pay 10 + 40 = 50. Symmetric -> 25/25.
    q = {"P": {1: -10.0, 2: -50.0}, "N": {1: -40.0, 2: -10.0}}
    c = coalition_cost_fn(q)
    _check(c(frozenset("P")) == 10.0 and c(frozenset("PN")) == 50.0,
           "coalition costs %r" % ({k: c(frozenset(k)) for k in ("P", "N", "PN")},))
    psi = shapley_cost_shares(q)
    _check(abs(psi["P"] - 25.0) < 1e-9 and abs(psi["N"] - 25.0) < 1e-9, psi)
    # NOT additive: psi_P != P's own best cost (the old game gave exactly that).
    _check(abs(psi["P"] - 10.0) > 1.0, "game must be non-additive")
    # Asymmetric: N's queue much worse -> N carries the larger share.
    psi = shapley_cost_shares({"P": {1: -10.0, 2: -20.0},
                               "N": {1: -90.0, 2: -30.0}})
    r = shapley_ratios(psi)
    _check(r["N"] > r["P"] and min(r.values()) >= 0.05 - 1e-12, r)
    _check(abs(sum(r.values()) - 1.0) < 1e-9, r)
    print("   game: conflict psi=%s  asymmetric ratios=%s"
          % ({k: round(v, 1) for k, v in shapley_cost_shares(q).items()},
             {k: round(v, 3) for k, v in r.items()}))


def _test_policy() -> None:
    pi = {1: 0.25, 2: 0.25, 3: 0.25, 4: 0.25}
    q = {1: -5.0, 2: -1.0, 3: -9.0, 4: -7.0}
    for _ in range(100):
        pi = policy_hill_climb(pi, q, lr=0.05, floor=0.01)
    _check(abs(sum(pi.values()) - 1.0) < 1e-9, pi)
    _check(pi[2] > 0.9 and min(pi.values()) > 0.0, pi)
    print("   policy hill-climb after 100 steps:",
          {k: round(v, 3) for k, v in pi.items()})


def _test_rewards() -> None:
    st = PhaseStructure(1, 4, {1: PHASE_THROUGH, 2: PHASE_THROUGH,
                               3: PHASE_THROUGH, 4: PHASE_THROUGH},
                        (1,), (2, 3, 4), 120.0)
    r = player_rewards(st, {1: 20.0, 2: 30.0, 3: 60.0, 4: 30.0},
                       bus_delay_s=15.0, bus_w=2.0)
    _check(r == {"P": -50.0, "N": -40.0}, r)
    r = player_rewards(st, {1: 20.0, 2: 30.0})   # phases 3/4 unmeasured
    _check(r == {"P": -20.0, "N": -30.0}, r)
    r = player_rewards_ctm(st, {1: 40.0, 2: 20.0, 3: 60.0},
                           {1: 10.0, 2: 99.0}, horizon_s=20.0, bus_w=3.0)
    _check(r == {"P": -(40.0 + 30.0) / 20.0, "N": -(40.0) / 20.0}, r)
    print("   rewards: P=-(dP + w*bus), N=-dN  ok (measured and CTM forms)")


def _test_state_key() -> None:
    a = CbqlState(1, 0.4, 120.0, (900.0, 300.0), phase_queue=(3.0, 30.0),
                  bus_level=5)
    _check(a.encode() == (1, 2, 6, (0, 4), 2), a.encode())   # capped bins
    b = CbqlState(1, 0.4, 120.0, (900.0, 300.0))
    _check(b.encode() == (1, 2, 6, (3, 1)), b.encode())      # flow form kept
    print("   state key: CTM form", a.encode(), " flow form", b.encode())


def _test_learning() -> None:
    """A toy junction where the bus phase (1) is the right call whenever the
    bus is delayed: P must learn to want phase 1, and the joint policy must
    shift toward it -- without ever pinning any action to exactly 0."""
    st = PhaseStructure(7, 3, {1: PHASE_THROUGH, 2: PHASE_THROUGH,
                               3: PHASE_PROTECTED_LEFT}, (1,), (2, 3), 90.0)
    ctl = CbqlTspController(st, seed=7)
    s = CbqlState(green_phase=1, green_ratio=0.4, cycle_s=90.0,
                  phase_flow=(600.0, 600.0, 300.0))
    for _ in range(400):
        a, _mix, _w = ctl.act(s)
        d = {1: 10.0, 2: 25.0, 3: 25.0}
        bus = 0.0 if a == 1 else 40.0        # bus waits unless phase 1 runs
        ctl.learn(s, a, player_rewards(st, d, bus, 1.0), s)
    mix, w = ctl.joint_policy(s)
    _check(max(mix, key=mix.get) == 1, "joint policy should favour phase 1: %r" % mix)
    _check(min(mix.values()) > 0.0, mix)
    _check(abs(sum(mix.values()) - 1.0) < 1e-9, mix)
    print("   learning: joint policy", {k: round(v, 3) for k, v in mix.items()},
          " ratios", {k: round(v, 3) for k, v in w.items()})


def _selftest() -> None:
    for spec, label in ((_demo_kg_junction(), "KG-8phase"),
                        (_demo_logan_junction(), "Logan-6phase")):
        st = derive_phase_structure(spec)
        print("\n[%s] junction=%d  n_phases=%d  cycle=%.0fs"
              % (label, st.junction_id, st.n_phases, st.cycle_s))
        for ph in sorted(st.phase_types):
            tag = "  <== PRIORITY (bus)" if st.is_priority(ph) else ""
            print("   phase %d: %-14s%s" % (ph, st.phase_types[ph], tag))
        _check(st.priority_phases, "priority phase not found for " + label)
        ctl = CbqlTspController(st)
        s = CbqlState(0, 0.4, st.cycle_s,
                      tuple(300.0 * (i + 1) for i in range(st.n_phases)))
        d = {ph: 100.0 + 20.0 * ph for ph in st.phase_types}
        for _ in range(50):
            a, mix, w = ctl.act(s)
            ctl.learn(s, a, player_rewards(st, d, 30.0), s)
        _check(abs(sum(mix.values()) - 1.0) < 1e-9, mix)
        print("   after 50 steps: ratios", {k: round(v, 3) for k, v in w.items()})
    print("")
    _test_game()
    _test_policy()
    _test_rewards()
    _test_state_key()
    _test_learning()
    print("\nOK: phase derivation, Q-defined Shapley game, eq.22 update, "
          "eq.18 policy, rewards -- all pass for both corridors.")


if __name__ == "__main__":
    _selftest()
