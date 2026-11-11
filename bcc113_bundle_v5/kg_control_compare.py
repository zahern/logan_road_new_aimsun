"""Fixed-time vs queue-actuated signals on the KG corridor (LightSim CTM).

Two controllers, five demand seeds, one horizon:

* ``fixed 60 s``  -- every node holds each phase for 60 s of green, then
  advances to the next phase in its own plan.  This is the "fixed 60 s green
  cycling" arm.
* ``webster``     -- static Webster (1958) splits: cycle ``C = (1.5L + 5) / (1 - Y)``
  and greens proportional to the critical flow ratio ``y_i``, where ``y_i`` is the
  measured degree of saturation of each phase's busiest approach.  Measured once
  on a 600 s nominal-demand survey run, then held unchanged for the whole
  evaluation -- one off-line plan, applied to all seeds.  LightSim ships a
  ``WebsterController``, but its ``_optimize`` caps ``Y`` at 0.9 without rescaling
  the greens and compares per-lane flow against total movement capacity, so under
  oversaturation its realised cycle comes out ~12x the clamped ``C`` (34-1777 s on
  this network); the splits below use counted arrivals with the cycle enforced.
* ``actuated``    -- at every decision point each phase is scored by the queue
  on its approach cells, ``sum max(0, k - k_crit) * L * lanes``.  Green is held
  for at least 20 s, switched to the best phase once it beats the current phase
  by 10 %, and forced over at 60 s.  Same 60 s ceiling, different allocation.
* ``phase 0``     -- reference arm: phase 0 held forever (the floor).

Seeds vary the *demand*, not the RNG: ``SimulationEngine`` is deterministic when
``stochastic=False``, so re-running a seed with the same demand reproduces the
run exactly.  Each seed draws a log-normal factor (sigma = 0.15) per origin
link, which is the only sampling in the experiment.

Reported per arm: ``mean block`` (positive, = -reward, mean over agent-steps),
``entered`` (vehicles injected at the origins) and ``exited`` (vehicles that
reached a sink).  Same seed = same demand, so arms are compared paired.

Demand level is ``VPH`` veh/h/lane, overridable with ``KG_VPH=<n>`` so the same
four arms can be swept across demand.

Run: ``KG_VPH=300 python kg_control_compare.py`` (writes
``kg_control_compare_vph<vph>.json``).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from kg_lightsim_env import DT, build_network, origin_links
from lightsim.core.demand import DemandProfile
from lightsim.envs.multi_agent import LightSimParallelEnv

ACTIONS = 180          # 180 actions x 5 sim steps x 2 s = 1800 s
SIM_S = ACTIONS * 5 * DT
SEEDS = [0, 1, 2, 3, 4]
VPH = float(os.environ.get("KG_VPH", "600"))   # veh/h/lane at every origin
SIGMA = 0.15           # per-origin log-normal spread between seeds

GREEN_FIXED_S = 60.0
WEBSTER_SURVEY_ACTIONS = 60     # 600 s nominal-demand survey used to tune the plan
WEBSTER_MIN_GREEN_S = 10.0      # 10 s floor (the vendored optimiser uses 5 s)
WEBSTER_LOST_PER_PHASE_S = 5.0  # 3 s yellow + 2 s all-red, as the sim charges it
WEBSTER_Y_CAP = 0.90            # Webster's practical saturation ceiling
WEBSTER_MIN_CYCLE_S = 40.0
WEBSTER_MAX_CYCLE_S = 120.0
MIN_GREEN_S = 20.0
MAX_GREEN_S = 60.0
SWITCH_MARGIN = 1.10


def profiles(net, vph: float | None = None, rng=None) -> list:
    """One constant profile per origin; *rng* None means nominal (no spread)."""
    vph = VPH if vph is None else float(vph)
    out = []
    for lnk in origin_links(net):
        lanes = lnk.cells[0].lanes if lnk.cells else 1
        factor = 1.0 if rng is None else float(np.exp(rng.normal(0.0, SIGMA)))
        out.append(DemandProfile(lnk.link_id, [0.0],
                                 [vph * lanes * factor / 3600.0]))
    return out


def demand_for(net, seed: int, vph: float | None = None) -> list:
    """One constant profile per origin, scaled by a per-seed log-normal factor."""
    return profiles(net, vph, np.random.default_rng(seed))


def nominal_demand(net, vph: float | None = None) -> list:
    """Seed-free demand, used only to tune the fixed-time Webster plan."""
    return profiles(net, vph)


def phase_queue(net, density, phase_id: int) -> float:
    """Vehicles queued on the approach cells served by *phase_id*."""
    q = 0.0
    for mid in net.phase_movements.get(phase_id, []):
        cell = int(net.mov_from_cell[mid])
        k = float(density[cell])
        k_crit = float(net.Q[cell] / net.vf[cell]) if net.vf[cell] > 1e-9 else 0.0
        if k > k_crit:
            q += (k - k_crit) * float(net.length[cell]) * float(net.lanes[cell])
    return q


class BasePolicy:
    name = "base"

    def __init__(self, env) -> None:
        self.env = env
        self.net = env.engine.net
        self.nodes = dict(env._agent_to_node)
        self.pending = {a: 0 for a in env.possible_agents}

    def _state(self, agent):
        return self.env.engine.signal_manager.states[self.nodes[agent]]

    def act(self) -> dict:
        raise NotImplementedError


class FixedCycle(BasePolicy):
    """Hold each phase 60 s, then advance -- classic fixed-time plan."""

    name = "fixed 60 s"

    def __init__(self, env, green_s: float = GREEN_FIXED_S) -> None:
        super().__init__(env)
        self.green_s = green_s

    def act(self) -> dict:
        out = {}
        for agent in self.env.possible_agents:
            st = self._state(agent)
            if st.in_yellow or st.in_all_red:          # let the transition finish
                out[agent] = self.pending[agent]
                continue
            phases = self.net.node_phases[self.nodes[agent]]
            if len(phases) > 1 and st.time_in_phase >= self.green_s:
                self.pending[agent] = (st.current_phase_idx + 1) % len(phases)
            else:
                self.pending[agent] = st.current_phase_idx
            out[agent] = self.pending[agent]
        return out


class WebsterCycle(BasePolicy):
    """Hold each phase for its static Webster green, fixed for the whole run."""

    name = "webster"

    def __init__(self, env, plan) -> None:
        super().__init__(env)
        self.plan = plan

    def act(self) -> dict:
        out = {}
        for agent in self.env.possible_agents:
            node = self.nodes[agent]
            st = self._state(agent)
            phases = self.net.node_phases[node]
            greens = self.plan.get(node)
            if greens is None or len(phases) < 2:
                self.pending[agent] = 0
                out[agent] = 0
                continue
            if st.in_yellow or st.in_all_red:          # let the transition finish
                out[agent] = self.pending[agent]
                continue
            idx = st.current_phase_idx % len(greens)
            if st.time_in_phase >= greens[idx] - 1e-9:
                self.pending[agent] = (st.current_phase_idx + 1) % len(phases)
            else:
                self.pending[agent] = st.current_phase_idx
            out[agent] = self.pending[agent]
        return out


class QueueActuated(BasePolicy):
    """Green goes to the phase with the longest queue, 20-60 s holds."""

    name = "actuated"

    def __init__(self, env, min_green: float = MIN_GREEN_S,
                 max_green: float = MAX_GREEN_S,
                 margin: float = SWITCH_MARGIN) -> None:
        super().__init__(env)
        self.min_green = min_green
        self.max_green = max_green
        self.margin = margin

    def act(self) -> dict:
        out = {}
        density = self.env.engine.state.density
        for agent in self.env.possible_agents:
            node = self.nodes[agent]
            st = self._state(agent)
            if st.in_yellow or st.in_all_red:
                out[agent] = self.pending[agent]
                continue
            phases = self.net.node_phases[node]
            cur = st.current_phase_idx
            if len(phases) < 2:
                self.pending[agent] = 0
                out[agent] = 0
                continue

            if st.time_in_phase < self.min_green:
                chosen = cur
            else:
                queues = [phase_queue(self.net, density, pid) for pid in phases]
                best = int(np.argmax(queues))
                if max(queues) <= 0.0:
                    chosen = cur
                elif best == cur:
                    chosen = cur
                elif st.time_in_phase >= self.max_green:
                    chosen = best
                elif queues[best] > self.margin * queues[cur] + 0.5:
                    chosen = best
                else:
                    chosen = cur
            self.pending[agent] = chosen
            out[agent] = chosen
        return out


class HoldPhase0(BasePolicy):
    """Reference: one phase served forever, everything else starved."""

    name = "phase 0"

    def act(self) -> dict:
        return {a: 0 for a in self.env.possible_agents}


def survey_flow_ratios(net, actions: int = WEBSTER_SURVEY_ACTIONS):
    """Measure approach arrival rates on nominal demand; return ``y_i`` per phase.

    Arrivals are counted cell by cell -- upstream intra-link flow, movement
    inflow and demand injection -- so this is a detector count *upstream* of the
    stop line and needs no green-ratio correction.  ``y_i`` is the degree of
    saturation of the phase's busiest approach,
    ``arrival rate / (Q * lanes)``, measured once on seed-free demand.
    """
    env = LightSimParallelEnv(network=net, dt=DT, reward_fn="ctm_block",
                              max_steps=actions,
                              demand_profiles=nominal_demand(net))
    env.reset(seed=0)
    compiled = env.engine.net
    eng = env.engine
    arrivals = np.zeros(len(compiled.Q))

    # cell -> its upstream neighbour inside the same link
    upstream = {}
    for cells in compiled.link_cells.values():
        for a, b in zip(cells[:-1], cells[1:]):
            upstream[int(b)] = int(a)
    ups = np.array(list(upstream.keys()), dtype=int)
    src = np.array(list(upstream.values()), dtype=int)
    mov_to = np.asarray(compiled.mov_to_cell, dtype=int)

    orig_flow = eng.flow_model.compute_flow

    def patched_flow(*args, **kwargs):
        out = orig_flow(*args, **kwargs)
        arrivals[ups] += out[0][src]
        np.add.at(arrivals, mov_to, out[1])
        return out

    orig_inj = eng.demand_manager.get_injection

    def patched_inj(*args, **kwargs):
        out = orig_inj(*args, **kwargs)
        arrivals[:] += out
        return out

    eng.flow_model.compute_flow = patched_flow
    eng.demand_manager.get_injection = patched_inj
    policy = FixedCycle(env)
    for _ in range(actions):
        env.step(policy.act())
    eng.flow_model.compute_flow = orig_flow
    eng.demand_manager.get_injection = orig_inj

    rate = arrivals / (actions * DT)           # veh/s arriving at each cell
    cap = compiled.Q * compiled.lanes
    ratios = {}
    for node_id, phases in compiled.node_phases.items():
        if len(phases) < 2:
            continue
        ys = []
        for pid in phases:
            best = 0.0
            for mid in compiled.phase_movements.get(pid, []):
                cell = int(compiled.mov_from_cell[mid])
                if cap[cell] > 1e-9:
                    best = max(best, float(rate[cell]) / float(cap[cell]))
            ys.append(max(best, 0.01))
        ratios[node_id] = ys
    return ratios


def webster_splits(y, effective_green: float,
                   min_green: float = WEBSTER_MIN_GREEN_S):
    """Greens proportional to ``y``, floored at *min_green*, summing to budget."""
    n = len(y)
    if effective_green <= n * min_green:
        return [effective_green / n] * n
    fixed = [False] * n
    while True:
        free = [i for i in range(n) if not fixed[i]]
        budget = effective_green - min_green * sum(fixed)
        denom = sum(y[i] for i in free) or 1.0
        g = [min_green if fixed[i] else budget * y[i] / denom for i in range(n)]
        low = [i for i in free if g[i] < min_green - 1e-9]
        if not low:
            return g
        for i in low:
            fixed[i] = True


def webster_plan(ratios, min_green: float = WEBSTER_MIN_GREEN_S):
    """Static Webster plan: cycle from ``Y``, greens from ``y_i``, normalised.

    ``C = (1.5L + 5) / (1 - Y)`` with ``L = 5 s`` per phase -- exactly the
    transition time this simulator charges -- clamped to a practical range, then
    the effective green is divided by ``y_i`` and floored at *min_green*.
    """
    plan = {}
    for node_id, y in ratios.items():
        n = len(y)
        lost = WEBSTER_LOST_PER_PHASE_S * n
        Y = min(sum(y), WEBSTER_Y_CAP)
        cycle = (1.5 * lost + 5.0) / (1.0 - Y)
        cycle = float(np.clip(cycle, WEBSTER_MIN_CYCLE_S, WEBSTER_MAX_CYCLE_S))
        cycle = max(cycle, n * (min_green + WEBSTER_LOST_PER_PHASE_S))
        plan[node_id] = webster_splits(y, cycle - lost, min_green)
    return plan


def cycle_of(greens) -> float:
    """Realised cycle: greens plus the lost time charged at every change."""
    return float(sum(greens) + WEBSTER_LOST_PER_PHASE_S * len(greens))


def rollout(make_policy, net, seed: int) -> dict:
    env = LightSimParallelEnv(network=net, dt=DT, reward_fn="ctm_block",
                              max_steps=ACTIONS,
                              demand_profiles=demand_for(net, seed))
    env.reset(seed=seed)
    policy = make_policy(env)

    blocks = []
    for _ in range(ACTIONS):
        _obs, rewards, _term, _trunc, _info = env.step(policy.act())
        blocks.append(-float(np.mean(list(rewards.values()))))

    metrics = env.engine.get_network_metrics()
    compiled = env.engine.net
    total_queue = sum(env.engine.get_link_queue(lid) for lid in compiled.link_cells)
    return {
        "mean_block": float(np.mean(blocks)),
        "block_last_third": float(np.mean(blocks[-ACTIONS // 3:])),
        "entered": float(metrics["total_entered"]),
        "exited": float(metrics["total_exited"]),
        "vehicles_at_end": float(metrics["total_vehicles"]),
        "queue_at_end": float(total_queue),
    }


def main() -> None:
    t0 = time.perf_counter()
    net = build_network()
    widths = {}
    for node in net.nodes.values():
        if not node.phases:
            continue
        widths[len(node.phases)] = widths.get(len(node.phases), 0) + 1
    print("network : %d links, %d nodes, %d signalised, horizon %d s, demand %.0f veh/h/lane"
          % (len(net.links), len(net.nodes), sum(widths.values()), SIM_S, VPH))
    print("phases per signalised node:", dict(sorted(widths.items())))

    t_survey = time.perf_counter()
    ratios = survey_flow_ratios(net)
    plan = webster_plan(ratios)
    cycles = [cycle_of(g) for g in plan.values()]
    assert all(WEBSTER_MIN_CYCLE_S - 1e-6 <= c <= WEBSTER_MAX_CYCLE_S + 1e-6
               for c in cycles), "webster cycle out of range"
    assert all(g >= WEBSTER_MIN_GREEN_S - 1e-9 for v in plan.values() for g in v), \
        "webster green below floor"
    print("webster : survey %d s on nominal demand (%.1fs) -> %d plans, "
          "cycle %.0f-%.0f s (median %.0f), green %.0f-%.0f s"
          % (WEBSTER_SURVEY_ACTIONS * 5 * DT, time.perf_counter() - t_survey,
             len(plan), min(cycles), max(cycles), float(np.median(cycles)),
             min(min(g) for g in plan.values()),
             max(max(g) for g in plan.values())))
    ys = [y for v in ratios.values() for y in v]
    print("webster : y_i %.2f-%.2f (median %.2f); %d/%d nodes at the Y cap"
          % (min(ys), max(ys), float(np.median(ys)),
             sum(1 for v in ratios.values() if sum(v) >= WEBSTER_Y_CAP),
             len(ratios)))

    arms = [("fixed 60 s", lambda env: FixedCycle(env)),
            ("webster", lambda env: WebsterCycle(env, plan)),
            ("actuated", lambda env: QueueActuated(env)),
            ("phase 0", lambda env: HoldPhase0(env))]

    rows = []
    for label, factory in arms:
        for seed in SEEDS:
            res = rollout(factory, net, seed)
            res.update(arm=label, seed=seed)
            rows.append(res)
        got = [r for r in rows if r["arm"] == label]
        print("%-10s block %.4f | entered %6.0f | exited %6.0f | queue %6.1f  (%.1fs)"
              % (label, np.mean([r["mean_block"] for r in got]),
                 np.mean([r["entered"] for r in got]),
                 np.mean([r["exited"] for r in got]),
                 np.mean([r["queue_at_end"] for r in got]),
                 time.perf_counter() - t0))

    print("\nper seed")
    print("%-10s %4s %8s %8s %8s %8s" % ("arm", "seed", "block", "entered", "exited", "queue"))
    for r in rows:
        print("%-10s %4d %8.4f %8.0f %8.0f %8.1f"
              % (r["arm"], r["seed"], r["mean_block"], r["entered"],
                 r["exited"], r["queue_at_end"]))

    print("\nmean +- sd over %d seeds, paired against fixed 60 s"
          % len(SEEDS))
    summary = {}
    base = {r["seed"]: r for r in rows if r["arm"] == "fixed 60 s"}
    for label, _factory in arms:
        got = [r for r in rows if r["arm"] == label]
        entry = {}
        for key in ("mean_block", "block_last_third", "entered", "exited", "queue_at_end"):
            vals = np.array([r[key] for r in got], dtype=float)
            entry[key] = (float(vals.mean()), float(vals.std(ddof=1)))
        d_block = [r["mean_block"] - base[r["seed"]]["mean_block"] for r in got]
        d_enter = [r["entered"] - base[r["seed"]]["entered"] for r in got]
        entry["paired_d_block"] = (float(np.mean(d_block)), float(np.std(d_block, ddof=1)))
        entry["paired_d_entered"] = (float(np.mean(d_enter)), float(np.std(d_enter, ddof=1)))
        entry["wins_block"] = sum(1 for d in d_block if d < 0)   # lower block wins
        entry["wins_entered"] = sum(1 for d in d_enter if d > 0)
        summary[label] = entry
        print("%-10s block %7.4f +- %.4f | last-third %7.4f | entered %6.0f +- %5.0f "
              "| exited %6.0f +- %5.0f | queue %6.1f"
              % (label, *entry["mean_block"], entry["block_last_third"][0],
                 *entry["entered"], *entry["exited"], entry["queue_at_end"][0]))
        print("%-10s paired d_block %+7.4f +- %.4f (%d/%d seeds lower) | "
              "d_entered %+6.0f +- %5.0f (%d/%d seeds higher)"
              % ("", *entry["paired_d_block"], entry["wins_block"], len(SEEDS),
                 *entry["paired_d_entered"], entry["wins_entered"], len(SEEDS)))

    print("\npaired: webster vs actuated, same seeds")
    web = {r["seed"]: r for r in rows if r["arm"] == "webster"}
    act = {r["seed"]: r for r in rows if r["arm"] == "actuated"}
    if web and act:
        for key, lower_better in (("mean_block", True), ("exited", False),
                                  ("queue_at_end", True)):
            d = np.array([web[s][key] - act[s][key] for s in web], dtype=float)
            wins = sum(1 for x in d if (x < 0 if lower_better else x > 0))
            print("  %-13s webster - actuated %+8.4f +- %6.4f  (%d/%d seeds webster better)"
                  % (key, d.mean(), d.std(ddof=1), wins, len(d)))

    plan_json = {str(k): {"greens_s": [round(g, 1) for g in v],
                          "cycle_s": round(cycle_of(v), 1)}
                 for k, v in plan.items()}
    out = {"horizon_s": SIM_S, "seeds": SEEDS, "vph_per_lane": VPH,
           "sigma": SIGMA, "webster_plan": plan_json,
           "summary": summary, "rows": rows}
    out_path = Path("kg_control_compare_vph%d.json" % int(round(VPH)))
    out_path.write_text(json.dumps(out, indent=2))
    print("\nwrote %s  (%.1fs)" % (out_path, time.perf_counter() - t0))


if __name__ == "__main__":
    main()
