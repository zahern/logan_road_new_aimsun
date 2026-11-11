"""bench_pax.py -- head-to-head on ONE SUMO process configuration.

All three controllers drive the SAME scenario, seed, demand and horizon, so the
comparison is like-for-like. This matters: the bridge's BASE_PLAN arms run a
different stack (TSP/game layer, corridor metrics), so their numbers are not
comparable to a traci-only env -- the baselines have to live in this harness.

Controllers:
  fixed : no intervention. SUMO's own commissioned program ticks, which is the
          fixed-time plan the bridge calls FIXEDTIME.
  sotl  : self-organising traffic lights on stopped VEHICLES (the bridge
          run_sotl rule: hold while demand > 1 veh and elapsed < MAX_GREEN,
          else advance to the next green).
  linq  : the trained linear-Q policy, greedy, shared by every junction.
  madqn : the shared-parameter numpy DQN (train_ma_dqn.py), greedy.
  sb3dqn: the same shared-parameter loop trained by stable-baselines3
          (train_ma_sb3.py), greedy -- the paper-implementation cross-check.

Metrics come from SUMO's tripinfo, pax-weighted the way the project scores:
  pax_srv   = sum of occupancy over finished trips   (bus 40, car 1.2)
  delay_hrs = sum(timeLoss * occupancy) / 3600       (person-hours)
  obj       = pax_srv / delay_hrs                    (higher is better)

Usage:
  python bench_pax.py --sumocfg .../kg.sumocfg --seed 0 --end 3600 \
      --weights linq_pax_linq.npy --csv bench_pax.csv
"""
import argparse
import csv
import os
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "shared_tsp_engine"))
from lightsim_pax_env import LightSimPaxParallelEnv   # noqa: E402

BUS_OCC = 40.0
CAR_OCC = 1.2
MIN_GREEN = 6.0
MAX_GREEN = 60.0
SOTL_THR = 1.0            # stopped vehicles on the served lanes


def _occ(vtype):
    """Occupancy of a finished trip from its vType id (bus vs car)."""
    return BUS_OCC if "bus" in str(vtype).lower() else CAR_OCC


def _act_fixed(env, a, obs, W):
    t = env.tls[a]
    return t.cur_green_pos            # hold: _apply() is a no-op


def _act_sotl(env, a, obs, W):
    t = env.tls[a]
    gi = t.green_idx[t.cur_green_pos]
    stopped = sum(env._lane_counts(ln)[2] for ln in t.phase_lanes.get(gi, ()))
    if t.time_since_switch < MIN_GREEN:
        return t.cur_green_pos
    if stopped > SOTL_THR and t.time_since_switch < MAX_GREEN:
        return t.cur_green_pos
    return (t.cur_green_pos + 1) % t.n_green


def _act_linq(env, a, obs, W):
    t = env.tls[a]
    f = np.concatenate([obs[a], [1.0]]).astype(np.float32)
    return int(np.argmax(W @ f)) % t.n_green


def _act_madqn(env, a, obs, W):
    """Greedy action from the shared multi-agent DQN (W is a NumpyDQN)."""
    t = env.tls[a]
    return int(W.act(np.asarray(obs[a], np.float32), explore=False)) % t.n_green


def _act_sb3dqn(env, a, obs, W):
    """Greedy action from the shared-parameter SB3 DQN (W is a zip-loaded DQN)."""
    t = env.tls[a]
    act, _ = W.predict(np.asarray(obs[a], np.float32), deterministic=True)
    return int(act) % t.n_green


ACTS = {"fixed": _act_fixed, "sotl": _act_sotl, "linq": _act_linq,
        "madqn": _act_madqn, "sb3dqn": _act_sb3dqn}


def run_one(controller, sumocfg, seed, end, weights=None):
    tip = os.path.abspath("tripinfo_%s_s%d.xml" % (controller, seed))
    stat = os.path.abspath("stats_%s_s%d.xml" % (controller, seed))
    for f in (tip, stat):
        if os.path.exists(f):
            os.remove(f)
    env = LightSimPaxParallelEnv(
        os.path.abspath(sumocfg), seed=seed, max_steps=float(end),
        sumo_args=["--tripinfo-output", tip,
                   "--tripinfo-output.write-unfinished", "true",
                   "--statistic-output", stat])
    W = None
    if controller in ("linq", "madqn", "sb3dqn") and (
            not weights or not os.path.exists(weights)):
        raise SystemExit("%s needs --weights (missing %r)"
                         % (controller, weights))
    if controller == "linq":
        W = np.load(weights)
    t0 = time.time()
    obs, _ = env.reset()
    if controller == "madqn":
        from dqn_base import NumpyDQN
        W = NumpyDQN(int(env._obs_dim), int(env._MAXG))
        W.load(weights)
    elif controller == "sb3dqn":
        from stable_baselines3 import DQN
        W = DQN.load(weights)              # accepts "x" or "x.zip"
        n_obs = int(np.prod(W.observation_space.shape))
        if n_obs != int(env._obs_dim):
            raise SystemExit("sb3dqn obs width %d != env %d"
                             % (n_obs, env._obs_dim))
    act = ACTS[controller]
    steps = 0
    while env.agents:
        acts = {a: act(env, a, obs, W) for a in env.agents}
        obs, _rew, _term, _trunc, _info = env.step(acts)
        steps += 1
    wall = time.time() - t0
    env.close()

    pax = delay = 0.0
    nveh = 0
    if os.path.exists(tip):
        for tr in ET.parse(tip).getroot().findall("tripinfo"):
            occ = _occ(tr.get("vType", ""))
            nveh += 1
            pax += occ
            delay += float(tr.get("timeLoss", 0.0) or 0.0) * occ / 3600.0
    obj = (pax / delay) if delay > 0 else 0.0
    # Admission accounting: SUMO refuses to insert a vehicle when its departure
    # edge is full, so a controller that leaves the boundary links congested
    # makes FEWER vehicles exist. A pax/delay ratio computed only over the
    # vehicles that got in then flatters it. loaded/inserted/waiting expose
    # that instead of leaving it as an argument about pax differences.
    loaded = inserted = waiting = tele = 0
    if os.path.exists(stat):
        _root = ET.parse(stat).getroot()
        _v = _root.find("vehicles")
        if _v is not None:
            loaded = int(_v.get("loaded", 0) or 0)
            inserted = int(_v.get("inserted", 0) or 0)
            waiting = int(_v.get("waiting", 0) or 0)
        _t = _root.find("teleports")
        if _t is not None:
            tele = int(_t.get("total", 0) or 0)
    per_veh = (delay * 3600.0 / nveh) if nveh else 0.0
    return {"controller": controller, "seed": seed, "end": end,
            "decisions": steps, "veh": nveh, "loaded": loaded,
            "inserted": inserted, "waiting": waiting, "teleports": tele,
            "pax": round(pax, 1), "delay_hrs": round(delay, 4),
            "obj": round(obj, 4), "per_veh_delay_s": round(per_veh, 1),
            "wall_s": round(wall, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--end", type=float, default=3600.0)
    ap.add_argument("--weights", default="")
    ap.add_argument("--controllers", default="fixed,sotl,linq")
    ap.add_argument("--csv", required=True)
    a = ap.parse_args()

    rows = []
    for c in [x for x in a.controllers.split(",") if x]:
        r = run_one(c, a.sumocfg, a.seed, a.end, a.weights)
        rows.append(r)
        print("[BENCH] %-6s seed=%d pax=%7.1f delay=%8.4f obj=%8.4f veh=%d wall=%.1fs"
              % (r["controller"], r["seed"], r["pax"], r["delay_hrs"],
                 r["obj"], r["veh"], r["wall_s"]), flush=True)
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    print("\n%-8s %9s %11s %9s" % ("ctrl", "pax", "delay_hrs", "obj"))
    for r in rows:
        print("%-8s %9.1f %11.4f %9.4f"
              % (r["controller"], r["pax"], r["delay_hrs"], r["obj"]))
    if len(rows) > 1:
        base = rows[0]
        for r in rows[1:]:
            d = ((r["obj"] - base["obj"]) / base["obj"] * 100.0
                 if base["obj"] else 0.0)
            print("  %-6s vs fixed: obj %+.1f%%" % (r["controller"], d))
    print("rows written: %s" % a.csv)


if __name__ == "__main__":
    main()
