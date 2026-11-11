"""bench_plan_select.py -- does the trained plan-selector (+ Layer-2 bus overlay)
beat the commissioned plan on matched seeds?

Arms, all on the same scenario / seed / demand / horizon (AGENTS RULE 3):
  commissioned    the network's own program, no overlay            (baseline)
  commissioned_ge the same program + _bus_ge()                     (Layer 2 alone)
  selector_ge     the trained shared-parameter selector chooses the plan each
                  decision period, + _bus_ge()                     (Layer 1 + 2)

Reported per arm:
  obj              pax_srv / total_delay_hrs        (higher is better)
  completed        trips in tripinfo (finished only -- unfinished are not
                   written, so this IS the completion count)
  inserted         vehicles SUMO admitted (statistic-output)
  per_veh_delay_s  total timeLoss / completed trip  (lower is better)

Usage:
  python bench_plan_select.py --sumocfg .../kg.sumocfg --seeds 0,1,2 --end 1200 \
      --period 60 --weights plan_marl_bench_marlq.npy --csv bench_plan_select.csv
"""
import argparse
import csv
import os
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_select_env import PlanSelectPaxParallelEnv, DEFAULT_PLANS   # noqa: E402

BUS_OCC = 40.0
CAR_OCC = 1.2
ARMS = ("commissioned", "commissioned_ge", "selector_ge")


def _is_bus(vtype):
    return "bus" in str(vtype).lower()


def run_one(sumocfg, seed, arm, end, period, W=None):
    tip = os.path.abspath("tripinfo_ps_%s_s%d.xml" % (arm, seed))
    stat = os.path.abspath("stats_ps_%s_s%d.xml" % (arm, seed))
    for f in (tip, stat):
        if os.path.exists(f):
            os.remove(f)
    plans = list(DEFAULT_PLANS) if arm == "selector_ge" else ["commissioned"]
    env = PlanSelectPaxParallelEnv(
        os.path.abspath(sumocfg), seed=seed, max_steps=float(end),
        period_s=float(period), plans=plans,
        bus_priority=(arm != "commissioned"),
        sumo_args=["--tripinfo-output", tip, "--statistic-output", stat])
    obs, _ = env.reset()
    t0 = time.time()
    steps = 0
    while env.agents:
        if arm == "selector_ge":
            acts = {}
            for a in env.agents:
                f = np.concatenate([obs[a], [1.0]]).astype(np.float32)
                acts[a] = int(np.argmax(W @ f)) % env._K
        else:
            acts = {a: 0 for a in env.agents}      # hold the commissioned plan
        obs, _rew, _term, _trunc, _info = env.step(acts)
        steps += 1
    wall = time.time() - t0
    ge = env.ge_report()
    env.close()

    pax = delay = 0.0
    nb = nc = 0
    bus_d = 0.0
    if os.path.exists(tip):
        for tr in ET.parse(tip).getroot().findall("tripinfo"):
            loss = float(tr.get("timeLoss", 0.0) or 0.0)
            if _is_bus(tr.get("vType", "")):
                nb += 1
                pax += BUS_OCC
                bus_d += loss * BUS_OCC / 3600.0
                delay += loss * BUS_OCC / 3600.0
            else:
                nc += 1
                pax += CAR_OCC
                delay += loss * CAR_OCC / 3600.0
    completed = nb + nc
    obj = (pax / delay) if delay > 0 else 0.0

    loaded = inserted = waiting = tele = 0
    if os.path.exists(stat):
        root = ET.parse(stat).getroot()
        v = root.find("vehicles")
        if v is not None:
            loaded = int(v.get("loaded", 0) or 0)
            inserted = int(v.get("inserted", 0) or 0)
            waiting = int(v.get("waiting", 0) or 0)
        t = root.find("teleports")
        if t is not None:
            tele = int(t.get("total", 0) or 0)

    return {"arm": arm, "seed": seed, "end": end, "period": period,
            "steps": steps, "completed": completed, "bus_trips": nb,
            "car_trips": nc, "inserted": inserted, "loaded": loaded,
            "waiting": waiting, "teleports": tele,
            "pax": round(pax, 1), "delay_hrs": round(delay, 3),
            "bus_delay_hrs": round(bus_d, 3),
            "obj": round(obj, 4),
            "per_veh_delay_s": round(delay * 3600.0 / completed, 1) if completed else 0.0,
            "ge_fires": ge["ge_fires"], "ge_seconds": ge["ge_seconds"],
            "ge_junctions": ge["ge_junctions"], "wall_s": round(wall, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sumocfg", required=True)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--end", type=float, default=1200.0)
    ap.add_argument("--period", type=float, default=60.0)
    ap.add_argument("--weights", default="", help="shared linear-Q .npy")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--csv", required=True)
    a = ap.parse_args()

    arms = [x for x in a.arms.split(",") if x]
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]

    W = None
    if "selector_ge" in arms:
        if not a.weights or not os.path.exists(a.weights):
            raise SystemExit("selector_ge needs --weights (missing %r)" % a.weights)
        W = np.load(a.weights)
        print("[bench] selector weights %s shape=%s" % (a.weights, W.shape), flush=True)

    rows = []
    for seed in seeds:
        for arm in arms:
            if arm == "selector_ge" and W.shape[1] != 1 + _obs_dim(a.sumocfg, a.end, a.period):
                raise SystemExit("weights %d cols != obs+1 (%d)"
                                 % (W.shape[1],
                                    1 + _obs_dim(a.sumocfg, a.end, a.period)))
            r = run_one(a.sumocfg, seed, arm, a.end, a.period, W)
            rows.append(r)
            print("[PS] seed=%d %-16s obj=%7.4f completed=%4d inserted=%4d "
                  "per_veh=%6.1fs bus_d=%7.3fh fires=%d ge_s=%.0f wall=%.0fs"
                  % (seed, arm, r["obj"], r["completed"], r["inserted"],
                     r["per_veh_delay_s"], r["bus_delay_hrs"], r["ge_fires"],
                     r["ge_seconds"], r["wall_s"]), flush=True)
            with open(a.csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)

    print("\n%-16s %8s %10s %10s %12s %9s" % (
        "arm", "obj", "completed", "inserted", "per_veh_delay", "bus_delay_h"))
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm]
        print("%-16s %8.4f %10.1f %10.1f %12.1f %9.3f" % (
            arm, np.mean([r["obj"] for r in rs]),
            np.mean([r["completed"] for r in rs]),
            np.mean([r["inserted"] for r in rs]),
            np.mean([r["per_veh_delay_s"] for r in rs]),
            np.mean([r["bus_delay_hrs"] for r in rs])))

    base = "commissioned"
    if base in arms:
        b = {r["seed"]: r for r in rows if r["arm"] == base}
        print("\nvs %s (mean over seeds)" % base)
        for arm in arms:
            if arm == base:
                continue
            rs = [r for r in rows if r["arm"] == arm]
            d_obj = np.mean([(r["obj"] - b[r["seed"]]["obj"]) / b[r["seed"]]["obj"] * 100.0
                             for r in rs])
            d_comp = np.mean([(r["completed"] - b[r["seed"]]["completed"])
                              / max(1, b[r["seed"]]["completed"]) * 100.0 for r in rs])
            d_veh = np.mean([r["per_veh_delay_s"] - b[r["seed"]]["per_veh_delay_s"]
                             for r in rs])
            print("  %-16s obj %+6.1f%%   completed %+5.1f%%   per_veh %+6.1f s"
                  % (arm, d_obj, d_comp, d_veh))
    print("rows written: %s" % a.csv)


def _obs_dim(sumocfg, end, period):
    """Obs width the selector was trained on (K plans + 2*MAXL + bus term)."""
    env = PlanSelectPaxParallelEnv(os.path.abspath(sumocfg), max_steps=120.0,
                                   period_s=float(period), plans=list(DEFAULT_PLANS),
                                   bus_priority=False)
    env.reset()
    dim = env._obs_dim
    env.close()
    return dim


if __name__ == "__main__":
    main()
