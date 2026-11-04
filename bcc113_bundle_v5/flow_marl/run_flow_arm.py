"""Run the exported Flow rules policy in SUMO vs NO_TSP and report KPIs.

This is the missing Flow-arm test. It loads
`<bundle>/kg/flow_policy.json` through the same bridge Aimsun uses
(`shared_tsp_engine.flow_policy`), evaluates the NONE/GE/ER/INS actions online
in the KG SUMO scenario, and compares against a NO_TSP baseline on the same
seed/horizon.

    python run_flow_arm.py --horizon 1800 --seed 300
    python run_flow_arm.py --horizon 4500 --seed 300 --policy ..\\kg\\flow_policy.json

Outputs: `flow_arm_eval.csv` next to this file, plus a console summary.
"""
import argparse
import csv
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

import traci

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.dirname(HERE)
for p in (BUNDLE, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from shared_tsp_engine import flow_policy  # noqa: E402
from configs import kg as K  # noqa: E402

GE_S = 5.0
ER_S = 5.0
MIN_GREEN = 6.0
ACTION_EVERY = 5


def _main_phases():
    out = {}
    for a in K.AGENTS:
        try:
            prog = traci.trafficlight.getAllProgramLogics(a)[0]
            best = max(prog.phases, key=lambda ph: float(ph.duration))
            out[a] = int(best.minDur if hasattr(best, "minDur") else 0)
            out[a] = int(prog.phases.index(best))
        except Exception:
            out[a] = 2
    return out


def _phase_edges(agent, phase_index, n_phases):
    """From-edges served by a phase (green links), deduped."""
    try:
        state = traci.trafficlight.getRedYellowGreenState(agent)
        links = traci.trafficlight.getControlledLinks(agent)
    except Exception:
        return []
    # SUMO returns the CURRENT phase state; for another phase, approximate with
    # the current green set (the bridge only needs a queue proxy).
    edges = []
    for i, lk in enumerate(links):
        if i >= len(state) or state[i] not in ("G", "g"):
            continue
        if not lk:
            continue
        e = traci.lane.getEdgeID(lk[0][0])
        if e not in edges:
            edges.append(e)
    return edges


def _queue(edges):
    q = 0.0
    for e in edges:
        try:
            q += float(traci.edge.getLastStepHaltingNumber(e))
        except Exception:
            pass
    return q


def _state(agent, main_phase):
    try:
        ph = int(traci.trafficlight.getPhase(agent))
        dur = float(traci.trafficlight.getPhaseDuration(agent))
        nxt = float(traci.trafficlight.getNextSwitch(agent))
        now = float(traci.simulation.getTime())
        elapsed = max(0.0, dur - max(0.0, nxt - now))
        n = max(1, len(traci.trafficlight.getAllProgramLogics(agent)[0].phases))
    except Exception:
        ph, dur, elapsed, n = 0, 30.0, 0.0, 4
    edges = _phase_edges(agent, ph, n)
    q_cur = _queue(edges)
    q_main = q_cur if ph == main_phase else q_cur * 0.5
    q_next = q_cur * 0.5
    cap = max(1.0, 20.0 * 3)
    return {
        "queue_cur": q_cur, "queue_main": q_main, "queue_next": q_next,
        "ds_cur": q_cur / cap, "ds_main": q_main / cap, "ds_next": q_next / cap,
        "arrivals_cur": q_cur, "elapsed_s": elapsed, "dur_s": dur,
        "cycle_s": 120.0, "phase": ph, "main_phase": main_phase,
        "phase_is_main": 1 if ph == main_phase else 0,
    }


def _apply(agent, action):
    if action in (None, "NONE"):
        return
    try:
        st = traci.trafficlight.getRedYellowGreenState(agent)
        if "y" in st or "Y" in st:
            return
        now = float(traci.simulation.getTime())
        nxt = float(traci.trafficlight.getNextSwitch(agent))
        rem = max(0.0, nxt - now)
        if action == "GE":
            traci.trafficlight.setPhaseDuration(agent, rem + GE_S)
        elif action == "ER":
            traci.trafficlight.setPhaseDuration(agent, max(MIN_GREEN, rem - ER_S))
        elif action == "INS":
            ph = int(traci.trafficlight.getPhase(agent))
            n = len(traci.trafficlight.getAllProgramLogics(agent)[0].phases)
            traci.trafficlight.setPhase(agent, (ph + 1) % n)
    except Exception:
        pass


def _kpis(tripinfo_path, sim_hours):
    n = 0
    unfinished = 0
    tloss = 0.0
    try:
        root = ET.parse(tripinfo_path).getroot()
        for tr in root.findall("tripinfo"):
            n += 1
            arr = tr.get("arrival")
            if arr is None or float(arr) < 0:
                unfinished += 1
            tloss += float(tr.get("timeLoss", 0.0))
    except Exception:
        pass
    completed = n - unfinished
    delay_h = tloss / 3600.0
    return {
        "trips": n,
        "completed": completed,
        "unfinished": unfinished,
        "delay_hrs": delay_h,
        "mean_delay_s": (tloss / n) if n else 0.0,
        "objective_trips_per_delay_hr": (completed / delay_h) if delay_h > 0 else 0.0,
        "sim_hours": sim_hours,
    }


def run_once(use_policy, policy, horizon, seed, warmup):
    trip = os.path.join(tempfile.gettempdir(),
                        "flow_arm_trip_%s_%d.xml" % ("flow" if use_policy else "base", seed))
    try:
        os.remove(trip)
    except Exception:
        pass
    cmd = [K.SUMO_BINARY, "-c", K.SUMOCFG, "--seed", str(seed),
           "--end", str(horizon), "--tripinfo-output", trip,
           "--tripinfo-output.write-unfinished", "true",
           "--no-step-log", "true", "--duration-log.disable", "true",
           "--start"]
    traci.start(cmd)
    try:
        main_phase = _main_phases()
        n_actions = {"NONE": 0, "GE": 0, "ER": 0, "INS": 0}
        while traci.simulation.getTime() < horizon:
            t = float(traci.simulation.getTime())
            if use_policy and t >= warmup:
                for a in K.AGENTS:
                    act = flow_policy.choose(_state(a, main_phase.get(a, 2)), policy)
                    n_actions[act or "NONE"] = n_actions.get(act or "NONE", 0) + 1
                    _apply(a, act)
            for _ in range(ACTION_EVERY):
                traci.simulationStep()
                if traci.simulation.getTime() >= horizon:
                    break
    finally:
        try:
            traci.close()
        except Exception:
            pass
    k = _kpis(trip, horizon / 3600.0)
    k["actions"] = n_actions if use_policy else {}
    k["arm"] = "FLOW_RULES" if use_policy else "NO_TSP"
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default=os.path.join(BUNDLE, "kg", "flow_policy.json"))
    ap.add_argument("--horizon", type=int, default=1800)
    ap.add_argument("--warmup", type=int, default=300)
    ap.add_argument("--seed", type=int, default=300)
    a = ap.parse_args()

    pol = flow_policy.load(a.policy)
    if not pol:
        raise SystemExit("cannot load policy: %s" % a.policy)
    print("policy:", a.policy, "| rules:", len(pol.get("rules") or []))

    base = run_once(False, None, a.horizon, a.seed, a.warmup)
    flow = run_once(True, pol, a.horizon, a.seed, a.warmup)

    print("\n%-12s %8s %8s %10s %12s %18s" %
          ("arm", "trips", "done", "delay_h", "mean_d_s", "obj(completed/delay-h)"))
    for k in (base, flow):
        print("%-12s %8d %8d %10.2f %12.2f %18.2f" %
              (k["arm"], k["trips"], k["completed"], k["delay_hrs"],
               k["mean_delay_s"], k["objective_trips_per_delay_hr"]))
        if k["unfinished"] > 0.05 * max(1, k["completed"]):
            print("             WARNING: %d unfinished trips ? objective is "
                  "distorted by unserved demand" % k["unfinished"])
    rel = (100.0 * (flow["objective_trips_per_delay_hr"]
                    - base["objective_trips_per_delay_hr"])
           / base["objective_trips_per_delay_hr"]) \
        if base["objective_trips_per_delay_hr"] else 0.0
    print("\nFlow vs NO_TSP objective: %+.1f%%" % rel)
    print("actions:", flow["actions"])

    out = os.path.join(HERE, "flow_arm_eval.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["arm", "seed", "horizon_s", "trips",
                                           "completed", "unfinished",
                                           "delay_hrs", "mean_delay_s",
                                           "objective_trips_per_delay_hr",
                                           "actions"])
        w.writeheader()
        for k in (base, flow):
            w.writerow({"arm": k["arm"], "seed": a.seed, "horizon_s": a.horizon,
                        "trips": k["trips"], "completed": k["completed"],
                        "unfinished": k["unfinished"], "delay_hrs": k["delay_hrs"],
                        "mean_delay_s": k["mean_delay_s"],
                        "objective_trips_per_delay_hr":
                            k["objective_trips_per_delay_hr"],
                        "actions": k["actions"]})
    print("wrote", out)


if __name__ == "__main__":
    main()
