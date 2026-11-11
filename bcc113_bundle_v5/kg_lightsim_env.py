"""Build the KG corridor as a LightSim ``Network``; add the CTM-block reward.

The KG twins score a signal plan by how much it blocks the downstream cell:
``ocf = clamp(1 - gamma * block)``.  LightSim's env API wants a reward, so this
module registers ``ctm_block`` = ``-gamma * block`` (the penalty half of ocf)
and hands back a PettingZoo ``LightSimParallelEnv`` over the same topology.

Run ``python kg_lightsim_env.py`` for the build + smoke test.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

VENDOR = Path("Z:/tsp/sumo_hpc/_lightsim_probe/vendor/LightSim")
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from lightsim.core.network import Network
from lightsim.core.types import NodeType, TurnType
from lightsim.core.demand import DemandProfile
from lightsim.envs.rewards import RewardFunction, register_reward, get_reward_function

NET_XML = Path("_sumo_snaps/kg.net.xml")
DT = 2.0          # s -- same step as the twins' CTM
VF = 13.89        # m/s -- 50 km/h free flow, gives L = vf*dt = 27.78 m
WAVE_FRAC = 0.36  # w / vf, matches ctm_lightsim._geom_parts
KJ = 0.15         # veh/m/lane
QSAT = 0.5        # veh/s/lane


@register_reward("ctm_block")
class CTMBlockReward(RewardFunction):
    """Negative normalised occupancy of the cells a node discharges into.

    ``block`` is ``max(density / jam_density)`` over the first ``cells`` cells of
    each outgoing link -- the same "can the exit absorb it" readout the twins use
    when they compute ``ocf``.  Reward is ``-gamma * block`` so that maximising it
    minimises blocking, i.e. maximises ``clamp(1 - gamma*block)``.
    """

    def __init__(self, gamma: float = 1.0, cells: int = 1, side: str = "out") -> None:
        self.gamma = float(gamma)
        self.cells = max(1, int(cells))
        self.side = side

    def compute(self, engine, node_id) -> float:
        net = engine.net
        table = (net.node_outgoing_links if self.side == "out"
                 else net.node_incoming_links)
        block = 0.0
        for lid in table.get(node_id, []):
            cids = net.link_cells.get(lid, [])
            window = cids[: self.cells] if self.side == "out" else cids[-self.cells:]
            for cid in window:
                kj = float(net.kj[cid])
                if kj > 0.0:
                    block = max(block, float(engine.state.density[cid]) / kj)
        return -self.gamma * block


def parse_net_xml(path: Path = NET_XML):
    """Return (junctions, edges, connections, tl_logics) from a SUMO net."""
    root = ET.parse(str(path)).getroot()

    junctions = {}
    for j in root.findall("junction"):
        jid = j.get("id", "")
        if jid.startswith(":"):
            continue
        junctions[jid] = (float(j.get("x", 0.0)), float(j.get("y", 0.0)))

    edges = {}
    for e in root.findall("edge"):
        eid = e.get("id", "")
        if eid.startswith(":") or e.get("function") == "internal":
            continue
        lanes = e.findall("lane")
        if not lanes:
            continue
        edges[eid] = {
            "from": e.get("from"),
            "to": e.get("to"),
            "lanes": int(e.get("numLanes") or len(lanes)),
            "length": float(e.get("length") or lanes[0].get("length") or 0.0),
            "speed": float(lanes[0].get("speed") or VF),
        }

    conns = []
    for c in root.findall("connection"):
        frm, to = c.get("from"), c.get("to")
        if not frm or not to or frm.startswith(":") or to.startswith(":"):
            continue
        if frm not in edges or to not in edges:
            continue
        conns.append({"from": frm, "to": to, "tl": c.get("tl"),
                      "li": c.get("linkIndex")})

    tls = {}
    for tl in root.findall("tlLogic"):
        tls[tl.get("id")] = [p.get("state", "") for p in tl.findall("phase")]

    return junctions, edges, conns, tls


def build_network(path: Path = NET_XML, dt: float = DT) -> Network:
    """Port ``kg.net.xml`` (junctions, edges, connections, tlLogic) to LightSim."""
    junctions, edges, conns, tls = parse_net_xml(path)
    net = Network()

    ids = {name: i for i, name in enumerate(sorted(junctions))}
    link_ids = {eid: 1000 + i for i, eid in enumerate(sorted(edges))}

    deg_in, deg_out = {}, {}
    for e in edges.values():
        deg_out[e["from"]] = deg_out.get(e["from"], 0) + 1
        deg_in[e["to"]] = deg_in.get(e["to"], 0) + 1

    signalised = {c["tl"] for c in conns if c["tl"] in tls}
    for name in sorted(junctions):
        x, y = junctions[name]
        if name in signalised:
            kind = NodeType.SIGNALIZED
        elif deg_in.get(name, 0) == 0:
            kind = NodeType.ORIGIN
        elif deg_out.get(name, 0) == 0:
            kind = NodeType.DESTINATION
        else:
            kind = NodeType.UNSIGNALIZED
        net.add_node(ids[name], kind, x, y)

    for eid in sorted(edges):
        e = edges[eid]
        if e["from"] not in ids or e["to"] not in ids:
            continue
        vf = max(1.0, e["speed"])
        x = vf * dt
        if e["length"] <= x:                     # keep the CFL condition valid
            n_cells = 1
            vf = max(1e-3, 0.999 * e["length"] / dt)
        else:
            n_cells = max(1, int(e["length"] / x))
            while n_cells > 1 and e["length"] / n_cells < x:   # float epsilon
                n_cells -= 1
        net.add_link(link_ids[eid], ids[e["from"]], ids[e["to"]], e["length"],
                     lanes=e["lanes"], n_cells=n_cells, free_flow_speed=vf,
                     wave_speed=WAVE_FRAC * vf, jam_density=KJ, capacity=QSAT)

    # movements: one per distinct from->to pair, turn ratios normalised per link
    pairs, seen = [], set()
    for c in conns:
        key = (c["from"], c["to"], c["tl"], c["li"])
        if key in seen:
            continue
        seen.add(key)
        pairs.append(c)

    per_from: dict[str, int] = {}
    for c in pairs:
        per_from[c["from"]] = per_from.get(c["from"], 0) + 1

    li_to_mid: dict[str, dict[int, int]] = {}
    for c in pairs:
        node = edges[c["from"]]["to"]
        mov = net.add_movement(link_ids[c["from"]], link_ids[c["to"]], ids[node],
                               turn_type=TurnType.THROUGH,
                               turn_ratio=1.0 / per_from[c["from"]])
        if c["tl"] in tls and c["li"] is not None:
            li_to_mid.setdefault(c["tl"], {})[int(c["li"])] = mov.movement_id

    # phases: a G/g at linkIndex i means that connection's movement is served
    for tl_id, states in tls.items():
        if tl_id not in ids:
            continue
        mapping = li_to_mid.get(tl_id, {})
        for state in states:
            served = [mapping[i] for i, ch in enumerate(state)
                      if i in mapping and ch in "Gg"]
            if served:
                net.add_phase(ids[tl_id], served, min_green=5.0, max_green=60.0,
                              yellow=3.0, all_red=2.0)

    return net


def origin_links(net: Network) -> list:
    """Links whose upstream node has in-degree zero -- the corridor's entries."""
    return [lnk for lnk in net.links.values()
            if net.nodes[lnk.from_node].node_type == NodeType.ORIGIN]


def make_demand(net: Network, vph_per_lane: float = 600.0) -> list:
    """One constant DemandProfile per origin link (veh/s = vph * lanes / 3600)."""
    profiles = []
    for lnk in origin_links(net):
        lanes = lnk.cells[0].lanes if lnk.cells else 1
        profiles.append(DemandProfile(lnk.link_id, [0.0],
                                      [max(vph_per_lane, 0.0) * lanes / 3600.0]))
    return profiles


def make_env(demand_vph: float = 600.0, **kwargs):
    """PettingZoo parallel env over the KG network with the ctm_block reward.

    ``demand_vph`` is vehicles/hour/lane loaded at every origin link; pass 0.0
    for an empty corridor.
    """
    from lightsim.envs.multi_agent import LightSimParallelEnv

    net = build_network()
    kwargs.setdefault("dt", DT)
    kwargs.setdefault("reward_fn", "ctm_block")
    kwargs.setdefault("max_steps", 20)
    if demand_vph > 0:
        kwargs.setdefault("demand_profiles", make_demand(net, demand_vph))
    return LightSimParallelEnv(network=net, **kwargs), net


if __name__ == "__main__":
    net = build_network()
    errs = net.validate()
    print("network :", net)
    print("validate:", (errs or ["ok"])[:3], "| n_errors:", len(errs))

    print("compiled:", net.compile(DT).summary())

    env, _ = make_env(max_steps=60, demand_vph=600.0)
    obs, info = env.reset(seed=0)
    agents = list(env.agents)
    print("agents  :", len(agents), agents[:3], "...")
    print("demand  : %d origin profiles" % len(env.engine.demand_profiles or []))

    def rollout(cycle: bool, steps: int = 40):
        env.reset(seed=0)
        actors = list(env.agents)
        tot, nz = 0.0, 0
        for t in range(steps):
            act = {a: (t % 2 if cycle else 0) for a in actors}
            _o, rew, _te, _tr, _i = env.step(act)
            tot += sum(rew.values())
            nz += sum(1 for v in rew.values() if abs(v) > 1e-12)
        m = env.engine.get_network_metrics()
        return (tot / (steps * len(actors)),
                nz / (steps * len(actors)), m.get("total_entered", float("nan")))

    for label, cyc in (("phase 0 ", False), ("cycling ", True)):
        mean_r, frac, entered = rollout(cyc)
        print("%s: mean reward %+.4f | non-zero %3.0f%% | entered %.0f veh"
              % (label, mean_r, 100 * frac, entered))

    nid = env._agent_to_node[agents[0]]
    print("compare : ctm_block %.4f | queue %.4f"
          % (get_reward_function("ctm_block").compute(env.engine, nid),
             get_reward_function("queue").compute(env.engine, nid)))
